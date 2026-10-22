"""Change conversations, and tell every open client: each function records
the room's events and what each ``/sync`` reads (docs/protocol.md).

This is the API of integrations: a bot answering, a WhatsApp webhook
delivering a message or a receipt, an assignment rule adding an agent.

    from django_chat_ui import content, services

    event = services.send(conversation, bot, content.text("Hi"))
    services.delivered(event, customer)
"""

from __future__ import annotations

import time
import uuid
from datetime import timedelta
from typing import TYPE_CHECKING, Any, cast

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from . import content as contents
from .matrix import (
    CAPABILITIES,
    CONVERSATION,
    DELIVERED,
    PARTICIPANT,
    ROOM_VERSION,
    STATUS,
    STREAM,
    event_id,
    parse_event,
    parse_mxc,
    redacted,
    timestamp,
    user_id,
)
from .models import (
    AbstractConversation,
    AbstractParticipant,
    Media,
    Membership,
    Receipt,
    RoomEvent,
    RoomState,
    StreamEntry,
    Typing,
    get_conversation_model,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable


def _backend() -> Any:
    from .backend import get_backend

    return get_backend()


def entry(
    kind: str,
    *,
    conversation: AbstractConversation | None = None,
    recipient: AbstractParticipant | None = None,
    event: RoomEvent | None = None,
    type: str = "",
    data: dict[str, Any] | None = None,
) -> StreamEntry:
    """Record what a ``/sync`` reads: for everyone in ``conversation``, or
    only for ``recipient``."""
    return StreamEntry.objects.create(
        kind=kind,
        conversation=conversation,
        recipient=recipient,
        event=event,
        type=type,
        data=data or {},
    )


def ephemeral(
    conversation: AbstractConversation, type: str, data: dict[str, Any]
) -> StreamEntry:
    """An ephemeral event of a room (in its ``ephemeral`` of ``/sync``): not
    of its timeline. Extensions send their own (``com.acme.progress``)."""
    return entry("ephemeral", conversation=conversation, type=type, data=data)


def after(event: RoomEvent) -> Q:
    """The events after ``event``, in the room's order."""
    return Q(id__gt=event.pk)


# Events --------------------------------------------------------------------------


def _media(conversation: AbstractConversation, content: dict[str, Any]) -> None:
    # The files a message shows are its conversation's from now on: its
    # participants may download them.
    uris = [content.get("url"), (content.get("info") or {}).get("thumbnail_url")]
    ids = [media for media in map(parse_mxc, uris) if media]
    if ids:
        Media.objects.filter(media_id__in=ids, conversation=None).update(
            conversation=conversation
        )


@transaction.atomic
def event(
    conversation: AbstractConversation,
    sender: AbstractParticipant | None,
    type: str,
    content: dict[str, Any],
    *,
    state_key: str | None = None,
    txn_id: str = "",
    meta: dict[str, Any] | None = None,
) -> RoomEvent:
    """Add an event to a room's timeline (``state_key``: a state event, the
    room's current one of its type and key from now on)."""
    relation = content.get("m.relates_to")
    relates_to = None
    rel_type = ""
    if isinstance(relation, dict):
        rel_type = str(relation.get("rel_type", ""))
        target = relation.get("event_id")
        if not rel_type and isinstance(relation.get("m.in_reply_to"), dict):
            rel_type = "m.in_reply_to"
            target = relation["m.in_reply_to"].get("event_id")
        pk = parse_event(target)
        if pk:
            relates_to = conversation.events.filter(pk=pk).first()
    created = RoomEvent.objects.create(
        conversation=conversation,
        # Any participant model (mypy only knows the settings' one).
        sender=cast(Any, sender),
        type=type,
        state_key=state_key,
        content=content,
        txn_id=txn_id,
        relates_to=relates_to,
        rel_type=rel_type if relates_to else "",
        meta=meta or {},
    )
    if state_key is not None:
        RoomState.objects.update_or_create(
            conversation=conversation,
            type=type,
            state_key=state_key,
            defaults={"event": created},
        )
    entry("event", conversation=conversation, event=created)
    return created


def member_content(participant: AbstractParticipant, membership: str) -> dict:
    """An ``m.room.member``'s content, with what this package adds (its
    kind, handle, avatar and ``ext``, as the backend serializes them)."""
    block = {
        key: value
        for key, value in {
            "kind": participant.kind,
            "handle": participant.handle,
            "avatar": participant.avatar,
            "ext": participant.ext,
        }.items()
        if value
    }
    data: dict[str, Any] = {"membership": membership}
    if participant.name:
        data["displayname"] = participant.name
    data[PARTICIPANT] = _backend().serialize_participant(participant, block)
    return data


def conversation_content(conversation: AbstractConversation) -> dict[str, Any]:
    """This package's state event of what a conversation is."""
    data: dict[str, Any] = {
        "channel": conversation.channel,
        "state": conversation.state,
    }
    if conversation.ext:
        data["ext"] = conversation.ext
    return _backend().serialize_conversation(conversation, data)


def power_levels(conversation: AbstractConversation) -> dict[str, Any]:
    """Nobody changes a room's state but the server; everybody writes, and
    redacts their own events."""
    return {
        "users_default": 0,
        "events_default": 0,
        "state_default": 100,
        "redact": 100,
        "invite": 100,
        "kick": 100,
        "ban": 100,
        "events": {},
        "users": {},
    }


# Conversations -------------------------------------------------------------------


@transaction.atomic
def create_conversation(
    participants: Iterable[AbstractParticipant],
    *,
    channel: str = "web",
    title: str = "",
    state: str = "open",
    capabilities: dict[str, Any] | None = None,
    ext: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
    creator: AbstractParticipant | None = None,
    **fields: Any,
) -> AbstractConversation:
    """A new room of ``participants``, all joined; ``fields``, those of a
    site's own model (``CHAT_UI_CONVERSATION_MODEL``): its priority, say."""
    conversation = get_conversation_model().objects.create(
        channel=channel,
        title=title,
        state=state,
        capabilities=capabilities or {},
        ext=ext or {},
        meta=meta or {},
        **fields,
    )
    members = list(dict.fromkeys(participants))
    event(
        conversation,
        creator,
        "m.room.create",
        {"room_version": ROOM_VERSION, "m.federate": False},
        state_key="",
    )
    for participant in members:
        Membership.objects.create(
            conversation=conversation, participant=cast(Any, participant)
        )
        event(
            conversation,
            participant,
            "m.room.member",
            member_content(participant, "join"),
            state_key=user_id(participant),
        )
    event(
        conversation,
        creator,
        "m.room.power_levels",
        power_levels(conversation),
        state_key="",
    )
    event(
        conversation,
        creator,
        "m.room.join_rules",
        {"join_rule": "invite"},
        state_key="",
    )
    event(
        conversation,
        creator,
        "m.room.history_visibility",
        {"history_visibility": "shared"},
        state_key="",
    )
    if title:
        event(conversation, creator, "m.room.name", {"name": title}, state_key="")
    event(
        conversation,
        creator,
        CONVERSATION,
        conversation_content(conversation),
        state_key="",
    )
    event(conversation, creator, CAPABILITIES, conversation.capabilities, state_key="")
    for participant in members:
        entry("join", conversation=conversation, recipient=participant)
    return conversation


@transaction.atomic
def add_participant(
    conversation: AbstractConversation, participant: AbstractParticipant
) -> Membership:
    membership, created = Membership.objects.get_or_create(
        conversation=conversation, participant=participant
    )
    if created:
        event(
            conversation,
            participant,
            "m.room.member",
            member_content(participant, "join"),
            state_key=user_id(participant),
        )
        entry("join", conversation=conversation, recipient=participant)
    return membership


@transaction.atomic
def remove_participant(
    conversation: AbstractConversation, participant: AbstractParticipant
) -> None:
    deleted, _ = Membership.objects.filter(
        conversation=conversation, participant=participant
    ).delete()
    if deleted:
        Typing.objects.filter(
            conversation=conversation, participant=participant
        ).delete()
        left = event(
            conversation,
            participant,
            "m.room.member",
            member_content(participant, "leave"),
            state_key=user_id(participant),
        )
        entry("leave", conversation=conversation, recipient=participant, event=left)


@transaction.atomic
def update_conversation(
    conversation: AbstractConversation, **changes: Any
) -> AbstractConversation:
    """Change ``title``, ``state``, ``capabilities``, ``ext`` or ``meta``:
    each a state event of the room (``meta`` stays on the server).

    Capabilities merge by key: to turn one off, set it to ``False`` (a
    WhatsApp window closing sets ``composer``)."""
    for field, value in changes.items():
        if field not in {"title", "state", "capabilities", "ext", "meta"}:
            raise TypeError(f"update_conversation() can't change {field!r}")
        if field == "capabilities":
            conversation.capabilities = {**conversation.capabilities, **value}
        else:
            setattr(conversation, field, value)
    conversation.updated = timezone.now()
    conversation.save()
    if "title" in changes:
        event(
            conversation,
            None,
            "m.room.name",
            {"name": conversation.title},
            state_key="",
        )
    if {"state", "ext"} & set(changes):
        event(
            conversation,
            None,
            CONVERSATION,
            conversation_content(conversation),
            state_key="",
        )
    if "capabilities" in changes:
        event(conversation, None, CAPABILITIES, conversation.capabilities, state_key="")
    return conversation


# Messages ------------------------------------------------------------------------


@transaction.atomic
def send(
    conversation: AbstractConversation,
    sender: AbstractParticipant | None,
    content: dict[str, Any],
    *,
    type: str = "m.room.message",
    txn_id: str = "",
    meta: dict[str, Any] | None = None,
) -> RoomEvent:
    """Send an event to a room as ``sender`` (None: the server, for a
    system notice): a message (``django_chat_ui.content`` has their
    contents), a reaction, an extension's event."""
    sent = event(conversation, sender, type, content, txn_id=txn_id, meta=meta)
    _media(conversation, content)
    if type == "m.room.message" and sent.rel_type != "m.replace":
        conversation.updated = sent.created
        conversation.save(update_fields=["updated"])
        others = conversation.memberships.exclude(participant=sender)
        others.update(unread=F("unread") + 1)
        for membership in others.select_related("participant"):
            entry("unread", conversation=conversation, recipient=membership.participant)
        if sender is not None:
            stopped, _ = Typing.objects.filter(
                conversation=conversation, participant=sender
            ).delete()
            if stopped:
                _typing(conversation)
    return sent


def system(conversation: AbstractConversation, text: str, code: str = "") -> RoomEvent:
    """An event in the thread, from the server: "Ana joined"."""
    return send(conversation, None, contents.system(text, code))


def edit(
    original: RoomEvent, new: dict[str, Any], sender: AbstractParticipant | None = None
) -> RoomEvent:
    """Replace a message's content (``m.replace``): its sender's, by default."""
    return send(
        original.conversation,
        original.sender if sender is None else sender,
        {
            "msgtype": new.get("msgtype", "m.text"),
            "body": f"* {new.get('body', '')}",
            "m.new_content": new,
            "m.relates_to": {"rel_type": "m.replace", "event_id": event_id(original)},
        },
    )


@transaction.atomic
def redact(
    target: RoomEvent,
    sender: AbstractParticipant | None = None,
    reason: str = "",
    *,
    txn_id: str = "",
) -> RoomEvent:
    """Delete an event (``m.room.redaction``): its content is gone for
    everyone; its place in the timeline stays."""
    data: dict[str, Any] = {"redacts": event_id(target)}
    if reason:
        data["reason"] = reason
    redaction = event(
        target.conversation,
        target.sender if sender is None else sender,
        "m.room.redaction",
        data,
        txn_id=txn_id,
    )
    target.content = redacted(target.type, target.content)
    target.redacted_by = redaction
    target.save(update_fields=["content", "redacted_by"])
    return redaction


def reactions(target: RoomEvent) -> dict[str, list[AbstractParticipant]]:
    """Who reacted to an event, with what (``m.annotation``s not redacted)."""
    result: dict[str, list[AbstractParticipant]] = {}
    for annotation in target.relations.filter(
        type="m.reaction", rel_type="m.annotation", redacted_by=None
    ).select_related("sender"):
        key = annotation.content["m.relates_to"].get("key", "")
        result.setdefault(key, []).append(annotation.sender)
    return result


def react(target: RoomEvent, sender: AbstractParticipant, key: str) -> RoomEvent:
    return send(
        target.conversation,
        sender,
        {
            "m.relates_to": {
                "rel_type": "m.annotation",
                "event_id": event_id(target),
                "key": key,
            }
        },
        type="m.reaction",
    )


def unreact(target: RoomEvent, sender: AbstractParticipant, key: str) -> None:
    """Take a reaction back: its event redacted."""
    for annotation in target.relations.filter(
        type="m.reaction",
        rel_type="m.annotation",
        sender=cast(Any, sender),
        redacted_by=None,
    ):
        if annotation.content["m.relates_to"].get("key") == key:
            redact(annotation, sender)


def stream_text(
    conversation: AbstractConversation,
    author: AbstractParticipant,
    chunks: Iterable[str],
    *,
    markdown: bool = True,
    buttons: list[dict[str, Any]] | None = None,
    every: float = 0.1,
    size: int = 200,
    clock: Callable[[], float] = time.monotonic,
) -> RoomEvent | None:
    """A message written as ``chunks`` come: what an AI model streams.

    While they come, the text so far goes as this package's ephemeral
    ``stream`` event (its clients show it growing; any Matrix client sees
    the author typing), every ``every`` seconds or ``size`` characters (a
    model's chunks are a few letters each). When they end, the message is
    sent: its text (``markdown``, or plain), with quick replies (``buttons``).
    If they fail, it's sent with what came, and the error goes on.

        with client.messages.stream(...) as stream:
            services.stream_text(conversation, bot, stream.text_stream)
    """
    stream = uuid.uuid4().hex
    sender = user_id(author)
    text = ""
    shown = ""
    sent = clock()
    typing(conversation, author, True)

    def show() -> None:
        nonlocal shown, sent
        if text != shown:
            data: dict[str, Any] = {"id": stream, "sender": sender, "body": text}
            if markdown:
                data["markdown"] = True
            ephemeral(conversation, STREAM, data)
            shown = text
        sent = clock()

    def end() -> RoomEvent | None:
        if not text and not buttons:
            ephemeral(
                conversation, STREAM, {"id": stream, "sender": sender, "done": True}
            )
            typing(conversation, author, False)
            return None
        message = contents.text(text, markdown=markdown, buttons=buttons)
        message[STREAM] = {"id": stream}
        return send(conversation, author, message)

    try:
        for chunk in chunks:
            text += chunk
            if len(text) - len(shown) >= size or clock() - sent >= every:
                show()
    except BaseException:
        end()
        raise
    return end()


# Who is typing, and who read what ------------------------------------------------


def _typing(conversation: AbstractConversation) -> None:
    now = timezone.now()
    typers = Typing.objects.filter(conversation=conversation, until__gt=now)
    ids = [user_id(pk) for pk in typers.values_list("participant_id", flat=True)]
    ephemeral(conversation, "m.typing", {"user_ids": ids})


@transaction.atomic
def typing(
    conversation: AbstractConversation,
    participant: AbstractParticipant,
    active: bool,
    timeout: int = 30000,
) -> None:
    """``participant`` is typing (for ``timeout`` milliseconds at most), or
    stopped."""
    if active:
        until = timezone.now() + timedelta(milliseconds=max(0, min(timeout, 120000)))
        Typing.objects.update_or_create(
            conversation=conversation,
            participant=participant,
            defaults={"until": until},
        )
    else:
        Typing.objects.filter(
            conversation=conversation, participant=participant
        ).delete()
    _typing(conversation)


def _receipt(
    conversation: AbstractConversation,
    participant: AbstractParticipant,
    until: RoomEvent,
    type: str,
) -> None:
    Receipt.objects.update_or_create(
        conversation=conversation,
        participant=participant,
        type=type,
        defaults={"event": until, "created": timezone.now()},
    )
    ephemeral(
        conversation,
        "m.receipt",
        {
            event_id(until): {
                type: {user_id(participant): {"ts": timestamp(timezone.now())}}
            }
        },
    )


@transaction.atomic
def read(
    conversation: AbstractConversation,
    participant: AbstractParticipant,
    until: RoomEvent,
    *,
    public: bool = True,
) -> None:
    """``participant`` read everything up to ``until``: their unread count
    follows, and, ``public``, the others see it (``m.read``; else it's
    ``m.read.private``)."""
    unread = (
        conversation.messages.filter(after(until))
        .exclude(sender=participant)
        .exclude(rel_type="m.replace")
        .count()
    )
    Membership.objects.filter(
        conversation=conversation, participant=participant
    ).update(last_read=until, unread=unread)
    if public:
        _receipt(conversation, participant, until, "m.read")
    entry("unread", conversation=conversation, recipient=participant)


def delivered(until: RoomEvent, participant: AbstractParticipant) -> None:
    """The channel delivered to ``participant`` everything up to ``until``
    (WhatsApp's two ticks)."""
    _receipt(until.conversation, participant, until, DELIVERED)


@transaction.atomic
def status(message: RoomEvent, value: str, error: dict[str, Any] | None = None) -> None:
    """A message's status that receipts don't say: ``failed`` (the channel
    rejected it), with its ``error`` (``{"errcode", "error"}``)."""
    data: dict[str, Any] = {"status": value}
    if error:
        data["error"] = error
    message.unsigned = {**message.unsigned, STATUS: data}
    message.save(update_fields=["unsigned"])
    ephemeral(message.conversation, STATUS, {"event_id": event_id(message), **data})

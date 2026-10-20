"""Change conversations, and tell every open interface: each function saves
the change and records its events (docs/protocol.md, section 7.2).

This is the API of integrations: a bot answering, a WhatsApp webhook
delivering a message or a receipt, an assignment rule adding an agent.

    from django_chat_ui import services

    message = services.post(conversation, bot, [{"type": "text", "text": "Hi"}])
    services.update_message(message, status="delivered")
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, cast

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from . import protocol
from .models import (
    AbstractConversation,
    AbstractParticipant,
    Event,
    Membership,
    Message,
    get_conversation_model,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable


def emit(
    type: str,
    data: dict[str, Any],
    *,
    conversation: AbstractConversation | None = None,
    recipient: AbstractParticipant | None = None,
) -> Event:
    """Record an event: for everyone in ``conversation``, or only for
    ``recipient``. Extensions emit their own (``acme.order.updated``)."""
    return Event.objects.create(
        type=type, data=data, conversation=conversation, recipient=recipient
    )


def after(message: Message) -> Q:
    """The messages after ``message``, in the conversation's order."""
    return Q(created__gt=message.created) | Q(
        created=message.created, id__gt=message.pk
    )


# Conversations ---------------------------------------------------------------


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
    **fields: Any,
) -> AbstractConversation:
    """A new conversation of ``participants``; ``fields``, those of a site's
    own model (``CHAT_UI_CONVERSATION_MODEL``): its priority, say."""
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
    Membership.objects.bulk_create(
        # Any participant model (mypy only knows the settings' one).
        Membership(conversation=conversation, participant=cast(Any, p))
        for p in members
    )
    data = protocol.conversation(conversation, unread=0)
    for p in members:
        emit("conversation.created", data, conversation=conversation, recipient=p)
    return conversation


@transaction.atomic
def add_participant(
    conversation: AbstractConversation, participant: AbstractParticipant
) -> Membership:
    membership, created = Membership.objects.get_or_create(
        conversation=conversation, participant=participant
    )
    if created:
        _participants_changed(conversation, exclude=participant)
        emit(
            "conversation.created",
            protocol.conversation(conversation, unread=0),
            conversation=conversation,
            recipient=participant,
        )
    return membership


@transaction.atomic
def remove_participant(
    conversation: AbstractConversation, participant: AbstractParticipant
) -> None:
    deleted, _ = Membership.objects.filter(
        conversation=conversation, participant=participant
    ).delete()
    if deleted:
        emit(
            "conversation.removed", {"id": str(conversation.pk)}, recipient=participant
        )
        _participants_changed(conversation)


def _participants_changed(
    conversation: AbstractConversation, exclude: AbstractParticipant | None = None
) -> None:
    participants = [protocol.participant(p) for p in conversation.participants.all()]
    for membership in conversation.memberships.exclude(participant=exclude):
        emit(
            "conversation.updated",
            {"id": str(conversation.pk), "participants": participants},
            conversation=conversation,
            recipient=membership.participant,
        )


@transaction.atomic
def update_conversation(
    conversation: AbstractConversation, **changes: Any
) -> AbstractConversation:
    """Change ``title``, ``state``, ``capabilities``, ``ext`` or ``meta``.

    Capabilities merge by key, as clients merge them: to turn one off, set
    it to ``False`` (a WhatsApp window closing sets ``composer``)."""
    data: dict[str, Any] = {"id": str(conversation.pk)}
    for field, value in changes.items():
        if field not in {"title", "state", "capabilities", "ext", "meta"}:
            raise TypeError(f"update_conversation() can't change {field!r}")
        if field == "capabilities":
            conversation.capabilities = {**conversation.capabilities, **value}
        else:
            setattr(conversation, field, value)
        data[field] = value
    conversation.updated = timezone.now()
    conversation.save()
    data["updatedAt"] = protocol.timestamp(conversation.updated)
    emit("conversation.updated", data, conversation=conversation)
    return conversation


# Messages --------------------------------------------------------------------


@transaction.atomic
def post(
    conversation: AbstractConversation,
    author: AbstractParticipant | None,
    parts: list[dict[str, Any]],
    *,
    client_id: str = "",
    reply_to: Message | None = None,
    status: str = "sent",
    streaming: bool = False,
    ext: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
) -> Message:
    """Add a message (``author`` None: a system message)."""
    message = Message.objects.create(
        conversation=conversation,
        author=author,
        parts=parts,
        client_id=client_id,
        reply_to=reply_to,
        status=status,
        streaming=streaming,
        ext=ext or {},
        meta=meta or {},
    )
    data = protocol.message(message)
    emit("message.created", data, conversation=conversation)

    conversation.last_message = data
    conversation.updated = message.created
    conversation.save(update_fields=["last_message", "updated"])
    others = conversation.memberships.exclude(participant=author)
    others.update(unread=F("unread") + 1)
    # What lists show: the last message, and each one's unread count.
    for membership in conversation.memberships.select_related("participant"):
        changes = {
            "id": str(conversation.pk),
            "lastMessage": data,
            "updatedAt": data["createdAt"],
        }
        if membership.participant_id != getattr(author, "pk", None):
            changes["unread"] = membership.unread
        emit(
            "conversation.updated",
            changes,
            conversation=conversation,
            recipient=membership.participant,
        )
    return message


def system(conversation: AbstractConversation, text: str, code: str = "") -> Message:
    """An event in the thread: "Ana joined", "Assigned to support"."""
    part: dict[str, Any] = {"type": "system", "text": str(text)}
    if code:
        part["code"] = code
    return post(conversation, None, [part])


@transaction.atomic
def update_message(message: Message, **changes: Any) -> Message:
    """Change ``status``, ``error``, ``parts``, ``streaming``, ``deleted``,
    ``reactions``, ``ext`` or ``meta``; editing ``parts`` of a message that
    isn't streaming marks it edited."""
    fields = {
        "status": "status",
        "error": "error",
        "parts": "parts",
        "streaming": "streaming",
        "deleted": "deleted",
        "reactions": "reactions",
        "ext": "ext",
        "meta": "meta",
    }
    data: dict[str, Any] = {
        "id": str(message.pk),
        "conversation": str(message.conversation_id),
    }
    if "parts" in changes and not message.streaming and not changes.get("deleted"):
        message.edited = timezone.now()
        data["editedAt"] = protocol.timestamp(message.edited)
    for field, value in changes.items():
        if field not in fields:
            raise TypeError(f"update_message() can't change {field!r}")
        setattr(message, field, value)
        data[field] = value
    message.save()
    conversation = message.conversation
    emit("message.updated", data, conversation=conversation)
    # The conversation keeps a copy of its last message: if it's this one,
    # the copy follows (read from the database: this object may be older).
    conversations = type(conversation).objects.filter(pk=conversation.pk)
    last = conversations.values_list("last_message", flat=True).first() or {}
    if last.get("id") == str(message.pk):
        snapshot = protocol.message(message)
        conversations.update(last_message=snapshot)
        conversation.last_message = snapshot
        if {"parts", "deleted"} & set(changes):
            # What lists show of it changed too (a streamed message, finished).
            emit(
                "conversation.updated",
                {"id": str(conversation.pk), "lastMessage": snapshot},
                conversation=conversation,
            )
    return message


def start_stream(
    conversation: AbstractConversation,
    author: AbstractParticipant,
    parts: list[dict[str, Any]] | None = None,
) -> Message:
    """A message a bot is still writing: then ``delta()``, then ``finish()``."""
    return post(conversation, author, parts or [], streaming=True)


@transaction.atomic
def delta(message: Message, text: str, part: int = 0) -> None:
    """Append ``text`` to part number ``part`` of a streaming message."""
    parts = message.parts
    if part < len(parts):
        parts[part]["text"] = parts[part].get("text", "") + text
    else:
        parts.append({"type": "text", "text": text})
    message.save(update_fields=["parts"])
    emit(
        "message.delta",
        {
            "id": str(message.pk),
            "conversation": str(message.conversation_id),
            "part": part,
            "text": text,
        },
        conversation=message.conversation,
    )


def finish(message: Message, parts: list[dict[str, Any]] | None = None) -> Message:
    """The end of a streamed message; ``parts`` replace what accumulated."""
    # Its parts always: a client that doesn't stream got no deltas.
    return update_message(
        message, streaming=False, parts=message.parts if parts is None else parts
    )


def stream_text(
    conversation: AbstractConversation,
    author: AbstractParticipant,
    chunks: Iterable[str],
    *,
    markdown: bool = True,
    then: list[dict[str, Any]] | None = None,
    every: float = 0.1,
    size: int = 200,
    clock: Callable[[], float] = time.monotonic,
) -> Message:
    """A message written as ``chunks`` come: what an AI model streams.

    The chunks are sent together, every ``every`` seconds or ``size``
    characters (a model's are a few letters each: one event apiece would
    fill the stream and the database). When they end, the message is
    finished: its text (``markdown``, or plain), then the parts of ``then``
    (quick replies, say). If they fail, it's finished with what came, and
    the error goes on.

        with client.messages.stream(...) as stream:
            services.stream_text(conversation, bot, stream.text_stream)
    """
    message = start_stream(conversation, author)
    text = ""
    pending = ""
    sent = clock()

    def flush() -> None:
        nonlocal pending, sent
        if pending:
            delta(message, pending)
            pending = ""
        sent = clock()

    def final() -> list[dict[str, Any]]:
        part: dict[str, Any] = {"type": "text", "text": text}
        if markdown:
            part["format"] = "markdown"
        return [part, *(then or [])] if text else list(then or [])

    try:
        for chunk in chunks:
            text += chunk
            pending += chunk
            if len(pending) >= size or clock() - sent >= every:
                flush()
    except BaseException:
        finish(message, final())
        raise
    flush()
    return finish(message, final())


# Who is typing, and who read what --------------------------------------------


def typing(
    conversation: AbstractConversation, participant: AbstractParticipant, active: bool
) -> None:
    emit(
        "typing",
        {
            "conversation": str(conversation.pk),
            "participant": str(participant.pk),
            "active": bool(active),
        },
        conversation=conversation,
    )


@transaction.atomic
def read(
    conversation: AbstractConversation, participant: AbstractParticipant, until: Message
) -> None:
    """``participant`` read everything up to ``until``: their unread count,
    and, with ``receipts``, the status of what they read."""
    unread = (
        conversation.messages.filter(after(until)).exclude(author=participant).count()
    )
    Membership.objects.filter(
        conversation=conversation, participant=participant
    ).update(last_read=until, unread=unread)
    emit(
        "read",
        {
            "conversation": str(conversation.pk),
            "participant": str(participant.pk),
            "until": str(until.pk),
        },
        conversation=conversation,
    )
    emit(
        "conversation.updated",
        {"id": str(conversation.pk), "unread": unread},
        conversation=conversation,
        recipient=participant,
    )
    if conversation.capabilities.get("receipts"):
        seen = (
            conversation.messages.exclude(after(until))
            .exclude(author=participant)
            .exclude(author=None)
            .filter(status__in=["sent", "delivered"])
        )
        for message in seen:
            update_message(message, status="read")

"""The commands of the protocol (docs/protocol.md, section 7.3): each checks
what the conversation allows, does it through ``services``, and answers.

``handle()`` returns the frames that answer a command, for its sender only:
its ``ack`` or ``error`` (``ready`` for ``hello``), after what it asked for
(the ``conversation.created`` and ``history`` of ``conversation.open``).
Events for everyone go on the stream.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from django.db import IntegrityError
from django.urls import Resolver404, resolve, reverse
from django.utils.translation import gettext as _

from . import protocol, services
from .models import Attachment, Conversation, Event, Membership, Message, Participant
from .protocol import ProtocolError, frame

if TYPE_CHECKING:
    from django.http import HttpRequest

    from .backend import ChatBackend

Answer = list[dict[str, Any]]
Handler = Callable[["Command", dict[str, Any]], Answer]

HANDLERS: dict[str, Handler] = {}

ATTACHMENTS = {"image", "video", "audio", "file"}
MAX_PARTS = 20
MAX_LIMIT = 100


def command(name: str) -> Callable[[Handler], Handler]:
    def register(handler: Handler) -> Handler:
        HANDLERS[name] = handler
        return handler

    return register


#: Where a session keeps its client's capabilities, from its ``hello``.
CLIENT_KEY = "django_chat_ui_client"


def client_capabilities(request: HttpRequest) -> dict[str, Any] | None:
    """What the client of this request said it renders (6.2), if it did."""
    session = getattr(request, "session", None)
    return session.get(CLIENT_KEY) if session is not None else None


def handle(
    backend: ChatBackend, request: HttpRequest, participant: Participant, raw: Any
) -> Answer:
    """Answer one command frame, as its client can take the answers."""
    answers = answer(backend, request, participant, raw)
    capabilities = client_capabilities(request)
    degraded = (protocol.degrade(frame, capabilities) for frame in answers)
    return [frame for frame in degraded if frame is not None]


def answer(
    backend: ChatBackend, request: HttpRequest, participant: Participant, raw: Any
) -> Answer:
    if not isinstance(raw, dict) or not isinstance(raw.get("type"), str):
        return [frame("error", ProtocolError("bad_request", _("Not a frame.")).data())]
    ref = raw.get("id")
    if not isinstance(ref, (str, int)) or isinstance(ref, bool):
        error = ProtocolError("bad_request", _("A command needs an id."))
        return [frame("error", error.data())]
    data = raw.get("data")
    if data is None:
        data = {}
    try:
        if not isinstance(data, dict):
            raise ProtocolError("bad_request", _("Its data must be an object."))
        return Command(backend, request, participant, ref).run(raw["type"], data)
    except ProtocolError as error:
        answer = error.data()
        if raw["type"] == "hello":
            answer["fatal"] = True
        return [frame("error", answer, ref)]


class Command:
    def __init__(
        self,
        backend: ChatBackend,
        request: HttpRequest,
        participant: Participant,
        ref: Any,
    ):
        self.backend = backend
        self.request = request
        self.participant = participant
        self.ref = ref

    def run(self, type: str, data: dict[str, Any]) -> Answer:
        handler = HANDLERS.get(type)
        if handler is not None:
            return handler(self, data)
        extension = self.backend.commands.get(type)
        if extension is not None and protocol.is_namespaced(type):
            return [
                self.ack(extension(self.backend, self.request, self.participant, data))
            ]
        raise ProtocolError("unknown_command", type)

    def ack(self, data: dict[str, Any] | None = None) -> dict[str, Any]:
        return frame("ack", data or {}, self.ref)

    # Lookups ---------------------------------------------------------------

    def conversation(self, data: dict[str, Any]) -> Conversation:
        pk = data.get("conversation")
        found = None
        if isinstance(pk, str) and pk.isdigit():
            found = (
                self.backend.conversations(self.participant)
                .filter(pk=pk)
                .select_related("last_message")
                .first()
            )
        if found is None:
            raise ProtocolError("not_found", _("There is no such conversation."))
        return found

    def message(self, conversation: Conversation, pk: Any) -> Message:
        found = None
        if isinstance(pk, str) and pk.isdigit():
            found = conversation.messages.filter(pk=pk).first()
        if found is None:
            raise ProtocolError("not_found", _("There is no such message."))
        return found

    def own_message(self, data: dict[str, Any], capability: str) -> Message:
        pk = data.get("id")
        found = None
        if isinstance(pk, str) and pk.isdigit():
            found = (
                Message.objects.filter(
                    pk=pk,
                    conversation__in=self.backend.conversations(self.participant),
                )
                .select_related("conversation")
                .first()
            )
        if found is None:
            raise ProtocolError("not_found", _("There is no such message."))
        require(found.conversation, capability)
        if capability != "reactions" and found.author_id != self.participant.pk:
            raise ProtocolError("forbidden", _("It isn't your message."))
        return found

    def unread(self, conversation: Conversation) -> int:
        membership = Membership.objects.filter(
            conversation=conversation, participant=self.participant
        ).first()
        return membership.unread if membership else 0

    # Parts -----------------------------------------------------------------

    def parts(self, conversation: Conversation, parts: Any) -> list[dict[str, Any]]:
        """The parts of a message ``participant`` sends, checked against the
        composer and rebuilt from what the server knows."""
        if not isinstance(parts, list) or not 0 < len(parts) <= MAX_PARTS:
            raise ProtocolError("bad_request", _("A message needs its parts."))
        if not all(
            isinstance(p, dict) and isinstance(p.get("type"), str) for p in parts
        ):
            raise ProtocolError("bad_request", _("Every part needs its type."))
        capabilities = conversation.capabilities
        composer = capabilities.get("composer") or {}
        mode = composer.get("mode", "free")
        reason = composer.get("reason")
        if conversation.state == "closed":
            raise ProtocolError("forbidden", _("This conversation is closed."))
        if mode == "templates":
            if any(p["type"] != "template" for p in parts):
                raise ProtocolError(
                    "window_closed", reason or _("Only templates can be sent now.")
                )
        elif mode != "free":
            raise ProtocolError(
                "unsupported", reason or _("Nothing can be written here now.")
            )
        checked = [self.part(conversation, part, composer) for part in parts]
        self.backend.validate_parts(conversation, self.participant, checked)
        return checked

    def part(
        self, conversation: Conversation, part: dict[str, Any], composer: dict
    ) -> dict[str, Any]:
        type = part["type"]
        if type == "text":
            text = part.get("text")
            if not isinstance(text, str) or not text.strip():
                raise ProtocolError("bad_request", _("The text is empty."))
            limit = composer.get("maxLength")
            if isinstance(limit, int) and len(text) > limit:
                raise ProtocolError("too_large", _("The text is too long."))
            checked = {"type": "text", "text": text}
            if part.get("format") == "markdown":
                checked["format"] = "markdown"
            return checked
        if type == "template":
            return template(composer, part)
        if type in ATTACHMENTS:
            return self.attachment(conversation, part)
        if protocol.is_namespaced(type):
            if not isinstance(part.get("fallback"), str) or not part["fallback"]:
                raise ProtocolError(
                    "bad_request", _("A part of an extension needs a fallback.")
                )
            return part
        raise ProtocolError("unsupported", _("That can't be sent here."))

    def attachment(
        self, conversation: Conversation, part: dict[str, Any]
    ) -> dict[str, Any]:
        """An uploaded file: only one uploaded to this conversation (its
        part is rebuilt from it: a client can't point to any other URL)."""
        allowed = conversation.capabilities.get("attachments") or {}
        if part["type"] not in allowed.get("types", []):
            raise ProtocolError("unsupported", _("Files can't be sent here."))
        upload = None
        try:
            match = resolve(urlsplit(str(part.get("url", ""))).path)
        except Resolver404:
            match = None
        if match and match.view_name == "django_chat_ui:upload":
            upload = Attachment.objects.filter(
                pk=match.kwargs["pk"],
                conversation=conversation,
                uploader=self.participant,
            ).first()
        if upload is None:
            raise ProtocolError("bad_request", _("Upload the file first."))
        return attachment_part(upload, part["type"])


def require(conversation: Conversation, capability: str) -> None:
    """A command the conversation doesn't allow is rejected (7.3)."""
    if not conversation.capabilities.get(capability):
        raise ProtocolError("unsupported", _("This conversation doesn't allow it."))


def attachment_part(upload: Attachment, type: str) -> dict[str, Any]:
    """The part of an upload, sent as ``type``."""
    part: dict[str, Any] = {"type": type, "url": upload_url(upload)}
    if type == "file":
        part.update(name=upload.name, size=upload.size, mime=upload.mime)
    elif type == "image":
        part["alt"] = upload.name
    else:
        part["mime"] = upload.mime
    part["fallback"] = upload.name
    return part


def upload_url(upload: Attachment) -> str:
    return reverse(
        "django_chat_ui:upload", kwargs={"pk": upload.pk, "name": upload.name}
    )


PLACEHOLDER = re.compile(r"\{\{(\d+)\}\}")


def template(composer: dict[str, Any], part: dict[str, Any]) -> dict[str, Any]:
    """A template of the conversation's, its text rendered by the server."""
    templates = {t.get("id"): t for t in composer.get("templates") or []}
    found = templates.get(part.get("template"))
    if found is None:
        raise ProtocolError("bad_request", _("There is no such template."))
    names = found.get("params") or []
    given = part.get("params")
    if not isinstance(given, dict):
        given = {}
    params = {name: str(given.get(name, "")) for name in names}

    def fill(match: re.Match) -> str:
        index = int(match.group(1)) - 1
        return params.get(names[index], "") if 0 <= index < len(names) else ""

    return {
        "type": "template",
        "template": found["id"],
        "params": params,
        "fallback": PLACEHOLDER.sub(fill, str(found.get("preview", ""))),
    }


def limit(data: dict[str, Any]) -> int:
    value = data.get("limit", 30)
    if not isinstance(value, int) or isinstance(value, bool):
        return 30
    return max(1, min(value, MAX_LIMIT))


def page(
    conversation: Conversation, before: Message | None, size: int
) -> dict[str, Any]:
    """A page of messages, oldest first (section 9)."""
    messages = conversation.messages.all()
    if before is not None:
        messages = messages.exclude(services.after(before)).exclude(pk=before.pk)
    rows = list(messages.order_by("-created", "-id")[: size + 1])
    more = len(rows) > size
    rows = rows[:size][::-1]
    return {
        "conversation": str(conversation.pk),
        "messages": [protocol.message(m) for m in rows],
        "before": str(rows[0].pk) if more else None,
        "more": more,
    }


# The commands ----------------------------------------------------------------


@command("hello")
def hello(self: Command, data: dict[str, Any]) -> Answer:
    spoken = data.get("protocol")
    if not isinstance(spoken, list):
        spoken = []
    common = [v for v in protocol.PROTOCOL_VERSIONS if v in spoken]
    if not common:
        raise ProtocolError("unsupported", _("No version of the protocol in common."))
    chosen = max(common, key=lambda v: tuple(int(n) for n in v.split(".")))
    capabilities = data.get("capabilities")
    session = getattr(self.request, "session", None)
    if isinstance(capabilities, dict) and session is not None:
        # What the server sends this client, from now on, is for it (6.2).
        session[CLIENT_KEY] = capabilities

    resume = data.get("resume")
    if not isinstance(resume, dict):
        resume = {}
    seq = resume.get("seq")
    oldest = Event.objects.order_by("id").values_list("id", flat=True).first()
    resumed = isinstance(seq, int) and (oldest is None or seq >= oldest - 1)

    conversations = (
        self.backend.conversations(self.participant)
        .select_related("last_message")
        .prefetch_related("participants")
        .distinct()
    )
    unread = dict(
        Membership.objects.filter(participant=self.participant).values_list(
            "conversation_id", "unread"
        )
    )
    ready = {
        "protocol": chosen,
        "me": protocol.participant(self.participant),
        "capabilities": self.backend.session_capabilities(self.participant),
        "conversations": [
            protocol.conversation(c, unread=unread.get(c.pk, 0)) for c in conversations
        ],
        "resumed": resumed,
    }
    return [frame("ready", ready, self.ref)]


@command("conversation.open")
def conversation_open(self: Command, data: dict[str, Any]) -> Answer:
    if "with" in data:
        conversation = start(self, data)
    else:
        conversation = self.conversation(data)
    return [
        frame(
            "conversation.created",
            protocol.conversation(conversation, unread=self.unread(conversation)),
            self.ref,
        ),
        frame("history", page(conversation, None, limit(data)), self.ref),
        self.ack({"conversation": str(conversation.pk)}),
    ]


def start(self: Command, data: dict[str, Any]) -> Conversation:
    ids = data.get("with")
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        raise ProtocolError("bad_request", _("`with` must list participant ids."))
    wanted = {i for i in ids if i != str(self.participant.pk)}
    others = list(Participant.objects.filter(pk__in=[i for i in wanted if i.isdigit()]))
    if len(others) != len(wanted):
        raise ProtocolError("not_found", _("There is no such participant."))
    channel = data.get("channel") or "web"
    if not isinstance(channel, str) or len(channel) > 64:
        raise ProtocolError("bad_request", _("That isn't a channel."))
    if not self.backend.can_start(self.participant, others, channel):
        raise ProtocolError("forbidden", _("You can't start that conversation."))
    return self.backend.start(self.request, self.participant, others, channel)


@command("conversation.close")
def conversation_close(self: Command, data: dict[str, Any]) -> Answer:
    # Nothing to unsubscribe from: the stream follows what one may see.
    self.conversation(data)
    return [self.ack()]


@command("message.send")
def message_send(self: Command, data: dict[str, Any]) -> Answer:
    conversation = self.conversation(data)
    client_id = data.get("clientId")
    if not isinstance(client_id, str) or not 0 < len(client_id) <= 100:
        raise ProtocolError("bad_request", _("A message needs its clientId."))
    if conversation.messages.filter(
        author=self.participant, client_id=client_id
    ).exists():
        return [self.ack()]  # Sent already: idempotent (7.3).
    parts = self.parts(conversation, data.get("parts"))
    reply_to = None
    if data.get("replyTo") is not None:
        require(conversation, "replies")
        reply_to = self.message(conversation, data["replyTo"])
    self.backend.before_send(self.request, conversation, self.participant, parts)
    try:
        message = services.post(
            conversation,
            self.participant,
            parts,
            client_id=client_id,
            reply_to=reply_to,
        )
    except IntegrityError:
        return [self.ack()]  # The same clientId, at the same time.
    self.backend.run_hook(self.backend.on_message, self.request, message)
    return [self.ack()]


@command("message.edit")
def message_edit(self: Command, data: dict[str, Any]) -> Answer:
    message = self.own_message(data, "edit")
    if message.deleted:
        raise ProtocolError("forbidden", _("That message was deleted."))
    parts = self.parts(message.conversation, data.get("parts"))
    services.update_message(message, parts=parts)
    return [self.ack()]


@command("message.delete")
def message_delete(self: Command, data: dict[str, Any]) -> Answer:
    message = self.own_message(data, "delete")
    services.update_message(message, deleted=True, parts=[{"type": "text", "text": ""}])
    return [self.ack()]


@command("message.react")
def message_react(self: Command, data: dict[str, Any]) -> Answer:
    message = self.own_message(data, "reactions")
    emoji = data.get("emoji")
    if not isinstance(emoji, str) or not 0 < len(emoji) <= 16:
        raise ProtocolError("bad_request", _("That isn't an emoji."))
    allowed = message.conversation.capabilities["reactions"]
    if isinstance(allowed, dict) and allowed.get("emojis"):
        if emoji not in allowed["emojis"]:
            raise ProtocolError("unsupported", _("That reaction isn't allowed here."))
    if message.deleted:
        raise ProtocolError("forbidden", _("That message was deleted."))
    me = str(self.participant.pk)
    reactions = {r["emoji"]: list(r.get("by", [])) for r in message.reactions}
    by = [p for p in reactions.get(emoji, []) if p != me]
    if data.get("active", True):
        by.append(me)
    reactions[emoji] = by
    services.update_message(
        message,
        reactions=[{"emoji": e, "by": b} for e, b in reactions.items() if b],
    )
    return [self.ack()]


@command("message.read")
def message_read(self: Command, data: dict[str, Any]) -> Answer:
    conversation = self.conversation(data)
    until = self.message(conversation, data.get("until"))
    services.read(conversation, self.participant, until)
    return [self.ack()]


@command("typing")
def typing(self: Command, data: dict[str, Any]) -> Answer:
    conversation = self.conversation(data)
    require(conversation, "typing")
    services.typing(conversation, self.participant, bool(data.get("active")))
    return [self.ack()]


@command("action")
def action(self: Command, data: dict[str, Any]) -> Answer:
    conversation = self.conversation(data)
    require(conversation, "buttons")
    message = self.message(conversation, data.get("message"))
    buttons = [
        button
        for part in message.parts
        if part.get("type") in {"buttons", "card"}
        for button in part.get("buttons") or []
    ]
    button = next((b for b in buttons if b.get("id") == data.get("button")), None)
    if button is None:
        raise ProtocolError("not_found", _("There is no such button."))
    self.backend.run_hook(
        self.backend.on_action, self.request, self.participant, message, button
    )
    return [self.ack()]


@command("history.fetch")
def history_fetch(self: Command, data: dict[str, Any]) -> Answer:
    conversation = self.conversation(data)
    require(conversation, "history")
    before = None
    if data.get("before") is not None:
        before = self.message(conversation, data["before"])
    return [
        frame("history", page(conversation, before, limit(data)), self.ref),
        self.ack(),
    ]

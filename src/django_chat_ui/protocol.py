"""The protocol's shapes (docs/protocol.md): models as the JSON objects of
section 4, frames, errors."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .models import Conversation, Message, Participant

PROTOCOL_VERSIONS = ["1.0"]

#: Part types of the protocol (section 5.2); others are namespaced.
PART_TYPES = {
    "text",
    "image",
    "video",
    "audio",
    "file",
    "location",
    "contact",
    "buttons",
    "link",
    "card",
    "system",
    "template",
}

#: Words a namespace can't be (section 3.2).
RESERVED = {
    "message",
    "conversation",
    "participant",
    "typing",
    "read",
    "presence",
    "action",
    "hello",
    "ready",
    "ack",
    "error",
    "history",
    "chat",
}

NAMESPACED = re.compile(r"^[a-z][a-z0-9_-]*(\.[a-z0-9_-]+)+$")


def is_namespaced(name: Any) -> bool:
    """Whether ``name`` is an extension's: ``<namespace>.<name>``."""
    return (
        isinstance(name, str)
        and bool(NAMESPACED.match(name))
        and name.split(".")[0] not in RESERVED
    )


def timestamp(value: datetime | None) -> str | None:
    """RFC 3339, in UTC, always to the millisecond (so they sort as text)."""
    if value is None:
        return None
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _compact(data: dict[str, Any]) -> dict[str, Any]:
    # Omitted and null mean the same (section 2): leave out what's empty.
    return {key: value for key, value in data.items() if value not in (None, "", {})}


def participant(p: Participant) -> dict[str, Any]:
    return _compact(
        {
            "id": str(p.pk),
            "kind": p.kind,
            "name": p.name,
            "avatar": p.avatar,
            "handle": p.handle,
            "ext": p.ext,
            "meta": p.meta,
        }
    )


def message(m: Message) -> dict[str, Any]:
    data = _compact(
        {
            "id": str(m.pk),
            "clientId": m.client_id,
            "conversation": str(m.conversation_id),
            "author": str(m.author_id) if m.author_id else None,
            "status": m.status,
            "error": m.error,
            "replyTo": str(m.reply_to_id) if m.reply_to_id else None,
            "createdAt": timestamp(m.created),
            "editedAt": timestamp(m.edited),
            "ext": m.ext,
            "meta": m.meta,
        }
    )
    data["parts"] = m.parts
    if m.deleted:
        data["deleted"] = True
    if m.streaming:
        data["streaming"] = True
    if m.reactions:
        data["reactions"] = m.reactions
    return data


def conversation(
    c: Conversation, *, unread: int | None = None, participants: bool = True
) -> dict[str, Any]:
    """A conversation as one participant sees it (``unread`` is theirs)."""
    data = _compact(
        {
            "id": str(c.pk),
            "channel": c.channel,
            "title": c.title,
            "state": c.state,
            "updatedAt": timestamp(c.updated),
            "ext": c.ext,
            "meta": c.meta,
        }
    )
    data["capabilities"] = c.capabilities
    if participants:
        data["participants"] = [participant(p) for p in c.participants.all()]
    if unread is not None:
        data["unread"] = unread
    if c.last_message_id:
        data["lastMessage"] = message(c.last_message)  # type: ignore[arg-type]
    return data


def frame(type: str, data: dict[str, Any] | None = None, ref: Any = None) -> dict:
    result: dict[str, Any] = {"type": type, "data": data or {}}
    if ref is not None:
        result["ref"] = ref
    return result


class ProtocolError(Exception):
    """A command that failed: answered with an ``error`` frame (4.4)."""

    def __init__(self, code: str, message: Any = "", *, retry: bool = False):
        super().__init__(str(message) or code)
        self.code = code
        self.message = message
        self.retry = retry

    def data(self) -> dict[str, Any]:
        data: dict[str, Any] = {"code": self.code, "retry": self.retry}
        if self.message:
            data["message"] = str(self.message)
        return data


# Degrading for a client (section 6.2) ------------------------------------------

MARKDOWN_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
MARKDOWN_MARKS = re.compile(r"[*_`]+")
MARKDOWN_LINE = re.compile(r"^\s*[-#>]+\s+", re.M)


def plain(markdown: str) -> str:
    """Markdown's text without its marks: ``[a](b)`` → a, ``**a**`` → a."""
    text = MARKDOWN_LINK.sub(r"\1", markdown)
    text = MARKDOWN_MARKS.sub("", text)
    return MARKDOWN_LINE.sub("", text).strip()


def _lines(*values: Any) -> str:
    return "\n".join(str(v) for v in values if v not in (None, ""))


def _as_text(part: dict[str, Any]) -> str:
    """What a part says, in words, for a client that can't render it."""
    type = part.get("type")
    if part.get("fallback"):
        return str(part["fallback"])
    if type == "buttons":
        return " / ".join(str(b.get("label", "")) for b in part.get("buttons") or [])
    if type == "link":
        return _lines(part.get("title"), part.get("url"))
    if type == "location":
        return _lines(part.get("name"), part.get("address")) or (
            f"{part.get('lat')}, {part.get('lng')}"
        )
    if type == "contact":
        return _lines(part.get("name"), *(part.get("phones") or []))
    if type in {"image", "video", "audio", "file"}:
        return _lines(part.get("name") or part.get("alt"), part.get("url"))
    return str(part.get("text", ""))


def degrade_parts(
    parts: list[dict[str, Any]], capabilities: dict[str, Any]
) -> list[dict[str, Any]]:
    """The parts as a client with ``capabilities`` can show them: a card as
    text (and its buttons, if it has them), markdown as plain text, any other
    part it doesn't list as its text. One it can't is left as it is (the
    client shows that it can't): never dropped (5.1)."""
    known = set(capabilities.get("parts") or []) | {"text"}
    markdown = "markdown" in (capabilities.get("formats") or ["plain"])
    result = []
    for part in parts:
        type = part.get("type")
        if type == "text":
            if part.get("format") == "markdown" and not markdown:
                part = {"type": "text", "text": plain(str(part.get("text", "")))}
            result.append(part)
        elif type in known:
            result.append(part)
        elif type == "card":
            words = _lines(part.get("title"), part.get("text"), part.get("url"))
            result.append({"type": "text", "text": words})
            if part.get("buttons") and "buttons" in known:
                result.append({"type": "buttons", "buttons": part["buttons"]})
        else:
            words = _as_text(part)
            result.append({"type": "text", "text": words} if words else part)
    return result


def degrade(frame: dict[str, Any], capabilities: Any) -> dict[str, Any] | None:
    """The frame as a client with ``capabilities`` (its ``hello``'s) takes
    it; None: not for it (deltas, to a client that doesn't stream)."""
    if not isinstance(capabilities, dict):
        return frame
    type = frame.get("type")
    if type == "message.delta" and not capabilities.get("streaming"):
        return None
    data = frame.get("data") or {}

    def message(m: dict[str, Any]) -> dict[str, Any]:
        if isinstance(m.get("parts"), list):
            return {**m, "parts": degrade_parts(m["parts"], capabilities)}
        return m

    def listed(c: dict[str, Any]) -> dict[str, Any]:
        if isinstance(c.get("lastMessage"), dict):
            return {**c, "lastMessage": message(c["lastMessage"])}
        return c

    if type in {"message.created", "message.updated"}:
        data = message(data)
    elif type in {"conversation.created", "conversation.updated"}:
        data = listed(data)
    elif type == "history":
        data = {**data, "messages": [message(m) for m in data.get("messages", [])]}
    elif type == "ready":
        data = {
            **data,
            "conversations": [listed(c) for c in data.get("conversations", [])],
        }
    else:
        return frame
    return {**frame, "data": data}

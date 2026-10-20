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

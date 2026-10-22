"""The Matrix Client-Server API's shapes (https://spec.matrix.org/v1.11/client-server-api/):
identifiers, errors, events as clients get them, and this package's
extensions, namespaced under ``io.github.rodolvbg.chat`` (docs/protocol.md).
"""

from __future__ import annotations

import html
import re
from typing import TYPE_CHECKING, Any, cast

from django.conf import settings
from django.http import JsonResponse

if TYPE_CHECKING:
    from datetime import datetime

    from .models import AbstractConversation, AbstractParticipant, RoomEvent

#: This package's namespace: every type and key it adds to Matrix.
NS = "io.github.rodolvbg.chat"

#: State events of a room: what it allows, and what it is.
CAPABILITIES = f"{NS}.capabilities"
CONVERSATION = f"{NS}.conversation"
#: The block of an ``m.room.member``'s content: kind, handle, avatar, ext.
PARTICIPANT = f"{NS}.participant"
#: Blocks of a message's content.
BUTTONS = f"{NS}.buttons"
ACTION = f"{NS}.action"
LINK = f"{NS}.link"
SYSTEM = f"{NS}.system"
#: Message types (``msgtype``) of its own.
CARD = f"{NS}.card"
TEMPLATE = f"{NS}.template"
CONTACT = f"{NS}.contact"
#: Ephemeral events: a message being written, a message's status.
STREAM = f"{NS}.stream"
STATUS = f"{NS}.status"
#: A receipt type: the channel delivered it (WhatsApp's two ticks).
DELIVERED = f"{NS}.delivered"

#: The versions of the specification it speaks (what it implements of them:
#: docs/protocol.md, section 3).
VERSIONS = ["v1.1", "v1.2", "v1.3", "v1.4", "v1.5", "v1.6", "v1.7", "v1.8", "v1.11"]
ROOM_VERSION = "11"
HTML = "org.matrix.custom.html"

#: The sender of what the server says itself (a system notice, a room's
#: creation without a creator).
SYSTEM_LOCALPART = "system"


def server_name() -> str:
    """The domain of every identifier: ``CHAT_UI["SERVER_NAME"]``."""
    return getattr(settings, "CHAT_UI", {}).get("SERVER_NAME", "localhost")


# Identifiers -------------------------------------------------------------------


def user_id(participant: AbstractParticipant | int | str | None) -> str:
    """A participant's user ID (``@p7:server``), from it or its pk; None:
    the server's own."""
    if participant is None:
        return f"@{SYSTEM_LOCALPART}:{server_name()}"
    pk = getattr(participant, "pk", participant)
    return f"@p{pk}:{server_name()}"


def room_id(conversation: AbstractConversation | Any) -> str:
    pk = getattr(conversation, "pk", conversation)
    return f"!{pk}:{server_name()}"


def event_id(event: RoomEvent | Any) -> str:
    pk = getattr(event, "pk", event)
    return f"${pk}"


def mxc(media_id: str) -> str:
    return f"mxc://{server_name()}/{media_id}"


def _local(value: Any, sigil: str, prefix: str = "") -> str | None:
    """The local part of one of its identifiers, or None (not one of ours)."""
    if not isinstance(value, str) or not value.startswith(sigil + prefix):
        return None
    local, _, domain = value[len(sigil) + len(prefix) :].partition(":")
    if domain != server_name() or not local.isdigit():
        return None
    return local


def parse_user(value: Any) -> str | None:
    """The pk of a participant's user ID (``@p7:server``)."""
    return _local(value, "@", "p")


def parse_room(value: Any) -> str | None:
    return _local(value, "!")


def parse_event(value: Any) -> str | None:
    """The pk of an event ID (``$42``)."""
    if not isinstance(value, str) or not value.startswith("$"):
        return None
    local = value[1:]
    return local if local.isdigit() else None


def parse_mxc(value: Any) -> str | None:
    """The media ID of one of its ``mxc://`` URIs."""
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"mxc://([^/]+)/([A-Za-z0-9_-]+)", value)
    if not match or match.group(1) != server_name():
        return None
    return match.group(2)


def timestamp(value: datetime) -> int:
    """Milliseconds since the epoch, as Matrix has them."""
    return int(value.timestamp() * 1000)


# Errors ------------------------------------------------------------------------

STATUS_OF = {
    "M_FORBIDDEN": 403,
    "M_UNKNOWN_TOKEN": 401,
    "M_MISSING_TOKEN": 401,
    "M_NOT_FOUND": 404,
    "M_UNRECOGNIZED": 404,
    "M_TOO_LARGE": 413,
    "M_LIMIT_EXCEEDED": 429,
    "M_UNKNOWN": 500,
}

#: Errors of its own (namespaced, as the specification asks).
UNSUPPORTED = "IO.GITHUB.RODOLVBG.CHAT.UNSUPPORTED"
WINDOW_CLOSED = "IO.GITHUB.RODOLVBG.CHAT.WINDOW_CLOSED"


class MatrixError(Exception):
    """A request that failed: ``{"errcode": …, "error": …}``, with its HTTP
    status (by ``errcode``: 400 unless the specification says otherwise)."""

    def __init__(self, errcode: str, error: Any = "", status: int | None = None):
        super().__init__(str(error) or errcode)
        self.errcode = errcode
        self.error = error
        self.status = status or STATUS_OF.get(errcode, 400)

    def data(self) -> dict[str, Any]:
        return {"errcode": self.errcode, "error": str(self.error or self.errcode)}

    def response(self) -> JsonResponse:
        return JsonResponse(self.data(), status=self.status)


# Events ------------------------------------------------------------------------


def client_event(
    event: RoomEvent, *, room: bool = True, viewer: AbstractParticipant | None = None
) -> dict[str, Any]:
    """An event as clients get it (``ClientEvent``); without ``room_id`` in
    a room of ``/sync``. Its transaction ID only for its sender."""
    data: dict[str, Any] = {
        "type": event.type,
        "content": event.content,
        "event_id": event_id(event),
        "sender": user_id(event.sender_id),
        "origin_server_ts": timestamp(event.created),
    }
    if room:
        data["room_id"] = room_id(event.conversation_id)
    if event.state_key is not None:
        data["state_key"] = event.state_key
    unsigned: dict[str, Any] = dict(event.unsigned or {})
    if event.txn_id and viewer is not None and event.sender_id == viewer.pk:
        unsigned["transaction_id"] = event.txn_id
    if event.redacted_by_id:
        # Its redaction (selected with it: no query).
        redaction = cast("RoomEvent", event.redacted_by)
        unsigned["redacted_because"] = client_event(redaction, room=room)
    if unsigned:
        data["unsigned"] = unsigned
    return data


#: What a redaction keeps of each kind of event (room version 11).
KEPT = {
    "m.room.member": {"membership", "join_authorised_via_users_server"},
    "m.room.create": None,  # Everything.
    "m.room.join_rules": {"join_rule", "allow"},
    "m.room.power_levels": {
        "ban",
        "events",
        "events_default",
        "invite",
        "kick",
        "redact",
        "state_default",
        "users",
        "users_default",
    },
    "m.room.history_visibility": {"history_visibility"},
    "m.room.redaction": {"redacts"},
}


def redacted(type: str, content: dict[str, Any]) -> dict[str, Any]:
    kept = KEPT.get(type, set())
    if kept is None:
        return content
    return {key: value for key, value in content.items() if key in kept}


# Markdown, the safe subset: **bold**, *italic*, `code`, [text](url), paragraphs,
# line breaks and "- " lists. Escaped first: raw HTML in the text stays text.

INLINE = re.compile(
    r"\*\*(?P<strong>[^*]+)\*\*"
    r"|\*(?P<em>[^*]+)\*"
    r"|`(?P<code>[^`]+)`"
    r"|\[(?P<label>[^\]]+)\]\((?P<url>https?://[^)\s]+)\)"
)


def _inline(text: str) -> str:
    out = []
    position = 0
    for match in INLINE.finditer(text):
        out.append(html.escape(text[position : match.start()], quote=False))
        if match.group("strong") is not None:
            out.append(f"<strong>{html.escape(match['strong'], quote=False)}</strong>")
        elif match.group("em") is not None:
            out.append(f"<em>{html.escape(match['em'], quote=False)}</em>")
        elif match.group("code") is not None:
            out.append(f"<code>{html.escape(match['code'], quote=False)}</code>")
        else:
            out.append(
                f'<a href="{html.escape(match["url"])}">'
                f"{html.escape(match['label'], quote=False)}</a>"
            )
        position = match.end()
    out.append(html.escape(text[position:], quote=False))
    return "".join(out)


def markdown_html(text: str) -> str:
    """The HTML of ``formatted_body`` for a markdown text."""
    blocks = []
    for block in re.split(r"\n{2,}", text.strip()):
        rows = block.split("\n")
        if all(re.match(r"^[-*] ", row) for row in rows):
            items = "".join(f"<li>{_inline(row[2:])}</li>" for row in rows)
            blocks.append(f"<ul>{items}</ul>")
        else:
            blocks.append("<p>" + "<br>".join(_inline(row) for row in rows) + "</p>")
    return "".join(blocks)


MARKDOWN_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
MARKDOWN_MARKS = re.compile(r"[*_`]+")
MARKDOWN_LINE = re.compile(r"^\s*[-#>]+\s+", re.M)


def plain(markdown: str) -> str:
    """Markdown's text without its marks: ``[a](b)`` → a, ``**a**`` → a."""
    text = MARKDOWN_LINK.sub(r"\1", markdown)
    text = MARKDOWN_MARKS.sub("", text)
    return MARKDOWN_LINE.sub("", text).strip()

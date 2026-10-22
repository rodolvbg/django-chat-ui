"""What a client may send to a room, by the conversation's capabilities
(docs/protocol.md, section 5): each event checked, and its content rebuilt
from what the server knows (an upload's type and size, a template's text, a
button's label)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from django.utils.translation import gettext as _

from .matrix import (
    ACTION,
    BUTTONS,
    HTML,
    NS,
    TEMPLATE,
    UNSUPPORTED,
    WINDOW_CLOSED,
    MatrixError,
    parse_event,
    parse_mxc,
)
from .models import Media

if TYPE_CHECKING:
    from .backend import ChatBackend
    from .models import AbstractConversation, AbstractParticipant, RoomEvent

#: The message types of files, and the capability's name of each.
MEDIA = {"m.image": "image", "m.video": "video", "m.audio": "audio", "m.file": "file"}
TEXT = {"m.text", "m.emote"}
MAX_KEY = 16
PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


@dataclass
class Checked:
    """An event as it will be sent; with ``action``, the message and the
    button it answers."""

    content: dict[str, Any]
    action: tuple[RoomEvent, dict[str, Any]] | None = None


def unsupported(message: Any = "") -> MatrixError:
    return MatrixError(
        UNSUPPORTED, message or _("This conversation doesn't allow it."), 403
    )


def require(conversation: AbstractConversation, capability: str) -> Any:
    """A capability the conversation has (its value), or the request fails."""
    value = conversation.capabilities.get(capability)
    if not value:
        raise unsupported()
    return value


def target(conversation: AbstractConversation, value: Any) -> RoomEvent:
    pk = parse_event(value)
    found = conversation.events.filter(pk=pk).first() if pk else None
    if found is None:
        raise MatrixError("M_NOT_FOUND", _("There is no such event."))
    return found


def media_kind(mime: str) -> str:
    kind = mime.split("/")[0]
    return kind if kind in {"image", "video", "audio"} else "file"


class Rules:
    def __init__(
        self,
        backend: ChatBackend,
        participant: AbstractParticipant,
        conversation: AbstractConversation,
    ):
        self.backend = backend
        self.participant = participant
        self.conversation = conversation
        self.capabilities = conversation.capabilities
        self.composer = self.capabilities.get("composer") or {}

    def check(self, type: str, content: Any) -> Checked:
        if not isinstance(content, dict):
            raise MatrixError("M_BAD_JSON", _("The content must be an object."))
        if self.conversation.state == "closed":
            raise MatrixError("M_FORBIDDEN", _("This conversation is closed."))
        if type == "m.room.message":
            return self.message(content)
        if type == "m.reaction":
            return Checked(self.reaction(content))
        if type in self.backend.event_types and not type.startswith(("m.", NS)):
            self.backend.validate_content(
                self.conversation, self.participant, type, content
            )
            return Checked(content)
        raise MatrixError("M_FORBIDDEN", _("Events of this type can't be sent here."))

    # Messages --------------------------------------------------------------------

    def message(self, content: dict[str, Any]) -> Checked:
        relation = content.get("m.relates_to")
        reply = None
        if relation is not None:
            if not isinstance(relation, dict):
                raise MatrixError("M_BAD_JSON", _("m.relates_to must be an object."))
            if relation.get("rel_type") == "m.replace":
                return Checked(self.edit(content, relation))
            if relation.get("rel_type") or not isinstance(
                relation.get("m.in_reply_to"), dict
            ):
                raise unsupported()
            require(self.conversation, "replies")
            reply = target(self.conversation, relation["m.in_reply_to"].get("event_id"))
        if isinstance(content.get(ACTION), dict):
            checked = self.action(content[ACTION])
        else:
            checked = Checked(self.composed(content))
        if reply is not None:
            checked.content["m.relates_to"] = {
                "m.in_reply_to": {"event_id": reply.event_id}
            }
        return checked

    def composed(self, content: dict[str, Any]) -> dict[str, Any]:
        """A message the composer allows, rebuilt."""
        msgtype = content.get("msgtype")
        if not isinstance(msgtype, str):
            raise MatrixError("M_BAD_JSON", _("A message needs its msgtype."))
        mode = self.composer.get("mode", "free")
        reason = self.composer.get("reason")
        if mode == "templates" and msgtype != TEMPLATE:
            raise MatrixError(
                WINDOW_CLOSED, reason or _("Only templates can be sent now."), 403
            )
        if mode not in {"free", "templates"}:
            raise unsupported(reason or _("Nothing can be written here now."))
        if msgtype == TEMPLATE:
            return self.template(content)
        if msgtype in TEXT:
            return self.text(content)
        if msgtype in MEDIA:
            return self.media(content)
        if (
            "." in msgtype
            and not msgtype.startswith(("m.", NS))
            and isinstance(content.get("body"), str)
            and content["body"]
        ):
            # An extension's (com.acme.order), with what others show of it.
            self.backend.validate_content(
                self.conversation, self.participant, "m.room.message", content
            )
            return self.foreign(content)
        raise unsupported(_("That can't be sent here."))

    def foreign(self, content: dict[str, Any]) -> dict[str, Any]:
        # This package's blocks are its server's to send: a client's would
        # pass for the server's (a system notice, quick replies).
        return {k: v for k, v in content.items() if not k.startswith(NS)}

    def text(self, content: dict[str, Any]) -> dict[str, Any]:
        body = content.get("body")
        if not isinstance(body, str) or not body.strip():
            raise MatrixError("M_BAD_JSON", _("The text is empty."))
        limit = self.composer.get("maxLength")
        if isinstance(limit, int) and len(body) > limit:
            raise MatrixError("M_TOO_LARGE", _("The text is too long."))
        checked: dict[str, Any] = {"msgtype": content["msgtype"], "body": body}
        if content.get("format") == HTML and isinstance(
            content.get("formatted_body"), str
        ):
            # Kept as sent: every client sanitizes it (the specification's
            # subset of HTML), this package's too.
            checked.update(format=HTML, formatted_body=content["formatted_body"])
        if isinstance(content.get("m.mentions"), dict):
            checked["m.mentions"] = content["m.mentions"]
        return checked

    def media(self, content: dict[str, Any]) -> dict[str, Any]:
        """A file uploaded by the sender, of a type the conversation takes;
        its info is the server's."""
        allowed = self.capabilities.get("attachments") or {}
        types = allowed.get("types", []) if isinstance(allowed, dict) else []
        media_id = parse_mxc(content.get("url"))
        upload = (
            Media.objects.filter(media_id=media_id, uploader=self.participant).first()
            if media_id
            else None
        )
        if upload is None or upload.conversation_id not in (None, self.conversation.pk):
            raise MatrixError("M_BAD_JSON", _("Upload the file first."))
        kind = MEDIA[content["msgtype"]]
        if kind not in types or (kind != "file" and media_kind(upload.mime) != kind):
            raise unsupported(_("Files of this type can't be sent here."))
        limit = allowed.get("maxSize") or self.backend.max_upload_size
        if upload.size > min(limit, self.backend.max_upload_size):
            raise MatrixError("M_TOO_LARGE", _("The file is too big."))
        body = content.get("body")
        checked: dict[str, Any] = {
            "msgtype": content["msgtype"],
            "body": body if isinstance(body, str) and body else upload.name,
            "url": content["url"],
            "info": {"mimetype": upload.mime, "size": upload.size},
        }
        if content["msgtype"] == "m.file":
            checked["filename"] = upload.name
        info: dict[str, Any] = (
            content["info"] if isinstance(content.get("info"), dict) else {}
        )
        for key in ("w", "h", "duration"):
            if isinstance(info.get(key), int) and not isinstance(info[key], bool):
                checked["info"][key] = info[key]
        if "org.matrix.msc3245.voice" in content and kind == "audio":
            checked["org.matrix.msc3245.voice"] = {}
        return checked

    def template(self, content: dict[str, Any]) -> dict[str, Any]:
        """A template of the conversation's, its text filled in by the
        server."""
        block: dict[str, Any] = (
            content[TEMPLATE] if isinstance(content.get(TEMPLATE), dict) else {}
        )
        templates = {t.get("id"): t for t in self.composer.get("templates") or []}
        found = templates.get(block.get("id"))
        if found is None:
            raise MatrixError("M_BAD_JSON", _("There is no such template."))
        names = found.get("params") or []
        given: dict[str, Any] = (
            block["params"] if isinstance(block.get("params"), dict) else {}
        )
        params = {name: str(given.get(name, "")) for name in names}

        def fill(match: re.Match) -> str:
            key = match.group(1)
            if key.isdigit():
                index = int(key) - 1
                return params.get(names[index], "") if 0 <= index < len(names) else ""
            return params.get(key, "")

        return {
            "msgtype": TEMPLATE,
            "body": PLACEHOLDER.sub(fill, str(found.get("preview", ""))),
            TEMPLATE: {"id": found["id"], "params": params},
        }

    def action(self, block: dict[str, Any]) -> Checked:
        """A button used: its answer is its label, as WhatsApp writes it."""
        require(self.conversation, "buttons")
        if self.composer.get("mode", "free") not in {"free", "actions", "templates"}:
            raise unsupported(self.composer.get("reason"))
        message = target(self.conversation, block.get("event_id"))
        buttons = (message.content.get(BUTTONS) or {}).get("buttons") or []
        button = next(
            (
                b
                for b in buttons
                if isinstance(b, dict) and b.get("id") == block.get("button")
            ),
            None,
        )
        if button is None:
            raise MatrixError("M_NOT_FOUND", _("There is no such button."))
        label = str(button.get("label", button["id"]))
        return Checked(
            {
                "msgtype": "m.text",
                "body": label,
                ACTION: {"event_id": message.event_id, "button": button["id"]},
                "m.relates_to": {"m.in_reply_to": {"event_id": message.event_id}},
            },
            action=(message, button),
        )

    def edit(self, content: dict[str, Any], relation: dict[str, Any]) -> dict[str, Any]:
        require(self.conversation, "edit")
        original = target(self.conversation, relation.get("event_id"))
        if (
            original.sender_id != self.participant.pk
            or original.type != "m.room.message"
        ):
            raise MatrixError("M_FORBIDDEN", _("It isn't your message."))
        if original.redacted_by_id:
            raise MatrixError("M_FORBIDDEN", _("That message was deleted."))
        new = content.get("m.new_content")
        if not isinstance(new, dict) or "m.relates_to" in new:
            raise MatrixError("M_BAD_JSON", _("An edit needs its new content."))
        checked = self.composed(new)
        return {
            "msgtype": checked["msgtype"],
            "body": f"* {checked['body']}",
            "m.new_content": checked,
            "m.relates_to": {"rel_type": "m.replace", "event_id": original.event_id},
        }

    # Reactions -------------------------------------------------------------------

    def reaction(self, content: dict[str, Any]) -> dict[str, Any]:
        allowed = require(self.conversation, "reactions")
        relation = content.get("m.relates_to")
        if not isinstance(relation, dict) or relation.get("rel_type") != "m.annotation":
            raise MatrixError("M_BAD_JSON", _("A reaction annotates an event."))
        key = relation.get("key")
        if not isinstance(key, str) or not 0 < len(key) <= MAX_KEY:
            raise MatrixError("M_BAD_JSON", _("That isn't an emoji."))
        if isinstance(allowed, dict) and allowed.get("emojis"):
            if key not in allowed["emojis"]:
                raise unsupported(_("That reaction isn't allowed here."))
        annotated = target(self.conversation, relation.get("event_id"))
        if annotated.redacted_by_id or annotated.type != "m.room.message":
            raise MatrixError("M_FORBIDDEN", _("That message can't be reacted to."))
        mine = annotated.relations.filter(
            type="m.reaction", sender=cast(Any, self.participant), redacted_by=None
        )
        if any(r.content["m.relates_to"].get("key") == key for r in mine):
            raise MatrixError(
                "M_DUPLICATE_ANNOTATION", _("You reacted with it already.")
            )
        return {
            "m.relates_to": {
                "rel_type": "m.annotation",
                "event_id": annotated.event_id,
                "key": key,
            }
        }

    # Redactions ------------------------------------------------------------------

    def redaction(self, redacted: RoomEvent) -> None:
        """A client redacts its own messages (with ``delete``) and its own
        reactions."""
        if redacted.sender_id != self.participant.pk or redacted.state_key is not None:
            raise MatrixError("M_FORBIDDEN", _("It isn't yours to delete."))
        if redacted.type == "m.room.message":
            require(self.conversation, "delete")
        elif (
            redacted.type != "m.reaction"
            and redacted.type not in self.backend.event_types
        ):
            raise MatrixError("M_FORBIDDEN", _("It isn't yours to delete."))

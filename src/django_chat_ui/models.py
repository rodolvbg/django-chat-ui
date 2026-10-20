"""The data of the chat UI protocol (docs/protocol.md, section 4), and the
log of events each client's stream is made of (sections 7.2 and 8.3).

Change them through ``django_chat_ui.services``, which records the events
that keep every open interface up to date; saving the models directly
changes nothing on screen.
"""

from __future__ import annotations

import uuid
from pathlib import PurePath

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class Participant(models.Model):
    """Someone or something taking part: a user of the site, an agent, a bot,
    a contact outside (a WhatsApp number, a visitor), the system."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="chat_participant",
        verbose_name=_("user"),
    )
    kind = models.CharField(
        _("kind"),
        max_length=64,
        default="user",
        help_text=_("user, agent, bot, contact, system, or an extension's."),
    )
    name = models.CharField(_("name"), max_length=200, blank=True)
    avatar = models.URLField(_("avatar"), blank=True)
    handle = models.CharField(
        _("handle"),
        max_length=200,
        blank=True,
        help_text=_("How the channel knows them: a phone number, an email…"),
    )
    ext = models.JSONField(default=dict, blank=True)
    meta = models.JSONField(default=dict, blank=True)
    created = models.DateTimeField(_("created"), default=timezone.now)

    class Meta:
        verbose_name = _("participant")
        verbose_name_plural = _("participants")

    def __str__(self) -> str:
        return self.name or f"{self.kind} {self.pk}"


class Conversation(models.Model):
    """A thread of messages between participants, on one channel."""

    channel = models.CharField(_("channel"), max_length=64, default="web")
    title = models.CharField(_("title"), max_length=200, blank=True)
    state = models.CharField(
        _("state"),
        max_length=64,
        default="open",
        help_text=_("open, pending, closed, or an extension's."),
    )
    capabilities = models.JSONField(_("capabilities"), default=dict, blank=True)
    participants = models.ManyToManyField(
        Participant,
        through="Membership",
        related_name="conversations",
        verbose_name=_("participants"),
    )
    last_message = models.ForeignKey(
        "Message",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("last message"),
    )
    ext = models.JSONField(default=dict, blank=True)
    meta = models.JSONField(default=dict, blank=True)
    created = models.DateTimeField(_("created"), default=timezone.now)
    updated = models.DateTimeField(_("updated"), default=timezone.now)

    class Meta:
        verbose_name = _("conversation")
        verbose_name_plural = _("conversations")
        ordering = ["-updated"]

    def __str__(self) -> str:
        return self.title or f"{self.channel} {self.pk}"


class Membership(models.Model):
    """A participant of a conversation, and what they haven't read."""

    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="memberships"
    )
    participant = models.ForeignKey(
        Participant, on_delete=models.CASCADE, related_name="memberships"
    )
    unread = models.PositiveIntegerField(_("unread"), default=0)
    last_read = models.ForeignKey(
        "Message",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("read until"),
    )
    joined = models.DateTimeField(_("joined"), default=timezone.now)

    class Meta:
        verbose_name = _("membership")
        verbose_name_plural = _("memberships")
        constraints = [
            models.UniqueConstraint(
                fields=["conversation", "participant"],
                name="chat_ui_membership_unique",
            )
        ]

    def __str__(self) -> str:
        return f"{self.participant} · {self.conversation}"


class Message(models.Model):
    """One entry of a conversation, made of parts (section 5)."""

    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    author = models.ForeignKey(
        Participant,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="messages",
        verbose_name=_("author"),
    )
    client_id = models.CharField(_("client id"), max_length=100, blank=True)
    parts = models.JSONField(_("parts"), default=list)
    status = models.CharField(_("status"), max_length=20, default="sent")
    error = models.JSONField(_("error"), null=True, blank=True)
    reply_to = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("reply to"),
    )
    created = models.DateTimeField(_("created"), default=timezone.now)
    edited = models.DateTimeField(_("edited"), null=True, blank=True)
    deleted = models.BooleanField(_("deleted"), default=False)
    streaming = models.BooleanField(_("streaming"), default=False)
    reactions = models.JSONField(_("reactions"), default=list, blank=True)
    ext = models.JSONField(default=dict, blank=True)
    meta = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = _("message")
        verbose_name_plural = _("messages")
        ordering = ["created", "id"]
        indexes = [models.Index(fields=["conversation", "created", "id"])]
        constraints = [
            # message.send is idempotent by clientId (section 7.3).
            models.UniqueConstraint(
                fields=["conversation", "author", "client_id"],
                condition=~models.Q(client_id=""),
                name="chat_ui_message_client_id_unique",
            )
        ]

    def __str__(self) -> str:
        texts = [part.get("text", "") for part in self.parts if "text" in part]
        return " ".join(texts)[:60] or f"{_('message')} {self.pk}"


def attachment_path(instance: Attachment, filename: str) -> str:
    # A name nobody can guess; the original is kept in `name`.
    return f"chat_ui/{uuid.uuid4().hex}{PurePath(filename).suffix.lower()}"


class Attachment(models.Model):
    """A file uploaded to a conversation, served only to its participants."""

    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="attachments"
    )
    uploader = models.ForeignKey(
        Participant, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    file = models.FileField(_("file"), upload_to=attachment_path)
    name = models.CharField(_("name"), max_length=255)
    mime = models.CharField(_("type"), max_length=100)
    size = models.PositiveBigIntegerField(_("size"))
    created = models.DateTimeField(_("created"), default=timezone.now)

    class Meta:
        verbose_name = _("attachment")
        verbose_name_plural = _("attachments")

    def __str__(self) -> str:
        return self.name


class Event(models.Model):
    """An event of the stream (section 7.2). Its id is the frame's ``seq``.

    An event goes to every participant of its conversation, or only to
    ``recipient`` (what they haven't read, a conversation they were added
    to or removed from).
    """

    created = models.DateTimeField(default=timezone.now, db_index=True)
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="+",
    )
    recipient = models.ForeignKey(
        Participant,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="+",
    )
    type = models.CharField(max_length=100)
    data = models.JSONField(default=dict)

    class Meta:
        verbose_name = _("event")
        verbose_name_plural = _("events")
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.pk} {self.type}"

    def frame(self) -> dict:
        return {"type": self.type, "seq": self.pk, "data": self.data}

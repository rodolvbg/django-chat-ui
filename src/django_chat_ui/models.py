"""Conversations as Matrix rooms (docs/protocol.md): their participants,
the events of their timelines, their current state, receipts and who is
typing, and the log that each client's ``/sync`` is read from.

Change them through ``django_chat_ui.services``, which records what keeps
every open client up to date; saving the models directly changes nothing on
screen.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from pathlib import PurePath
from typing import TYPE_CHECKING

from django.apps import apps
from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

if TYPE_CHECKING:
    from django.db.models.fields.related_descriptors import RelatedManager

#: The settings that swap the models, and their defaults.
PARTICIPANT_SETTING = "CHAT_UI_PARTICIPANT_MODEL"
CONVERSATION_SETTING = "CHAT_UI_CONVERSATION_MODEL"
DEFAULTS = {
    PARTICIPANT_SETTING: "django_chat_ui.Participant",
    CONVERSATION_SETTING: "django_chat_ui.Conversation",
}


def participant_model_name() -> str:
    """``app_label.Model`` of the participants (``CHAT_UI_PARTICIPANT_MODEL``)."""
    return getattr(settings, PARTICIPANT_SETTING, DEFAULTS[PARTICIPANT_SETTING])


def conversation_model_name() -> str:
    """``app_label.Model`` of the conversations (``CHAT_UI_CONVERSATION_MODEL``)."""
    return getattr(settings, CONVERSATION_SETTING, DEFAULTS[CONVERSATION_SETTING])


def get_participant_model() -> type[AbstractParticipant]:
    """The model of the participants: this package's, or the site's."""
    return apps.get_model(participant_model_name(), require_ready=False)


def get_conversation_model() -> type[AbstractConversation]:
    """The model of the conversations: this package's, or the site's."""
    return apps.get_model(conversation_model_name(), require_ready=False)


class AbstractParticipant(models.Model):
    """Someone or something taking part — a Matrix user: a user of the site,
    an agent, a bot, a contact outside (a WhatsApp number, a visitor).

    Subclass it to add fields (the company of a contact, their CRM id…), and
    name the subclass in ``CHAT_UI_PARTICIPANT_MODEL`` before the first
    migration."""

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

    objects = models.Manager()

    if TYPE_CHECKING:  # The relations of this package's models to it.
        memberships: RelatedManager[Membership]

    class Meta:
        abstract = True
        verbose_name = _("participant")
        verbose_name_plural = _("participants")

    def __str__(self) -> str:
        return self.name or f"{self.kind} {self.pk}"


class Participant(AbstractParticipant):
    class Meta(AbstractParticipant.Meta):
        swappable = PARTICIPANT_SETTING


class AbstractConversation(models.Model):
    """A thread of messages between participants, on one channel — a
    Matrix room. Its fields are its state: each change is a state event too
    (``m.room.name``, and this package's ``conversation`` and
    ``capabilities``).

    Subclass it to add fields (who it's assigned to, its priority, the
    order it's about…), and name the subclass in
    ``CHAT_UI_CONVERSATION_MODEL`` before the first migration. Its
    participants and events are this package's (``Membership``,
    ``RoomEvent``), pointing to it."""

    channel = models.CharField(_("channel"), max_length=64, default="web")
    title = models.CharField(_("title"), max_length=200, blank=True)
    state = models.CharField(
        _("state"),
        max_length=64,
        default="open",
        help_text=_("open, pending, closed, or an extension's."),
    )
    capabilities = models.JSONField(_("capabilities"), default=dict, blank=True)
    ext = models.JSONField(default=dict, blank=True)
    #: The site's own data: never sent to clients.
    meta = models.JSONField(default=dict, blank=True)
    created = models.DateTimeField(_("created"), default=timezone.now)
    updated = models.DateTimeField(_("updated"), default=timezone.now)

    objects = models.Manager()

    if TYPE_CHECKING:  # The relations of this package's models to it.
        memberships: RelatedManager[Membership]
        events: RelatedManager[RoomEvent]

    class Meta:
        abstract = True
        verbose_name = _("conversation")
        verbose_name_plural = _("conversations")
        ordering = ["-updated"]

    def __str__(self) -> str:
        return self.title or f"{self.channel} {self.pk}"

    @property
    def participants(self) -> models.QuerySet[AbstractParticipant]:
        """Who takes part, in the order they joined."""
        return (
            get_participant_model()
            .objects.filter(memberships__conversation=self)
            .order_by("memberships__id")
        )

    @property
    def messages(self) -> models.QuerySet[RoomEvent]:
        """Its messages (``m.room.message``), oldest first."""
        return self.events.filter(type="m.room.message").order_by("id")


class Conversation(AbstractConversation):
    class Meta(AbstractConversation.Meta):
        swappable = CONVERSATION_SETTING


class Membership(models.Model):
    """A participant of a conversation (``m.room.member``, joined), and
    what they haven't read."""

    conversation = models.ForeignKey(
        conversation_model_name(), on_delete=models.CASCADE, related_name="memberships"
    )
    participant = models.ForeignKey(
        participant_model_name(), on_delete=models.CASCADE, related_name="memberships"
    )
    unread = models.PositiveIntegerField(_("unread"), default=0)
    last_read = models.ForeignKey(
        "RoomEvent",
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
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["conversation", "participant"],
                name="chat_ui_membership_unique",
            )
        ]

    def __str__(self) -> str:
        return f"{self.participant} · {self.conversation}"


class RoomEvent(models.Model):
    """An event of a room's timeline: a message, a reaction, an edit, a
    redaction, a state event (with ``state_key``). Its pk is its order in the
    room, and its event ID (``$42``)."""

    conversation = models.ForeignKey(
        conversation_model_name(), on_delete=models.CASCADE, related_name="events"
    )
    #: None: the server's own (a system notice).
    sender = models.ForeignKey(
        participant_model_name(),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("sender"),
    )
    type = models.CharField(_("type"), max_length=255)
    # None: not a state event ("" is a state key, the room's own).
    state_key = models.CharField(  # noqa: DJ001
        _("state key"), max_length=255, null=True, blank=True
    )
    content = models.JSONField(_("content"), default=dict, blank=True)
    #: What the server adds to it (``unsigned``): a message's status.
    unsigned = models.JSONField(default=dict, blank=True)
    created = models.DateTimeField(_("created"), default=timezone.now)
    txn_id = models.CharField(_("transaction id"), max_length=255, blank=True)
    #: ``m.relates_to``: the event it annotates, replaces or answers.
    relates_to = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="relations",
    )
    rel_type = models.CharField(max_length=64, blank=True)
    redacted_by = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    #: The site's own data: never sent to clients.
    meta = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = _("event")
        verbose_name_plural = _("events")
        ordering = ["id"]
        indexes = [models.Index(fields=["conversation", "type", "id"])]
        constraints = [
            # A transaction sent again isn't sent twice (PUT …/send/…/{txnId}).
            models.UniqueConstraint(
                fields=["conversation", "sender", "txn_id"],
                condition=~models.Q(txn_id=""),
                name="chat_ui_event_txn_unique",
            )
        ]

    def __str__(self) -> str:
        body = self.content.get("body") if isinstance(self.content, dict) else None
        return str(body)[:60] if body else f"{self.type} {self.pk}"

    @property
    def event_id(self) -> str:
        return f"${self.pk}"

    @property
    def body(self) -> str:
        """The text of a message (its fallback, for any kind)."""
        return str(self.content.get("body", ""))


class RoomState(models.Model):
    """A room's current state: the latest event of each type and key."""

    conversation = models.ForeignKey(
        conversation_model_name(), on_delete=models.CASCADE, related_name="+"
    )
    type = models.CharField(max_length=255)
    state_key = models.CharField(max_length=255, blank=True)
    event = models.ForeignKey(RoomEvent, on_delete=models.CASCADE, related_name="+")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["conversation", "type", "state_key"],
                name="chat_ui_state_unique",
            )
        ]

    def __str__(self) -> str:
        return f"{self.type} {self.state_key}".strip()


class Receipt(models.Model):
    """Where a participant got to: what they read (``m.read``), or what the
    channel delivered to them (this package's ``delivered``)."""

    conversation = models.ForeignKey(
        conversation_model_name(), on_delete=models.CASCADE, related_name="+"
    )
    participant = models.ForeignKey(
        participant_model_name(), on_delete=models.CASCADE, related_name="+"
    )
    type = models.CharField(max_length=255)
    event = models.ForeignKey(RoomEvent, on_delete=models.CASCADE, related_name="+")
    created = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["conversation", "participant", "type"],
                name="chat_ui_receipt_unique",
            )
        ]

    def __str__(self) -> str:
        return f"{self.type} {self.event_id}"


class Typing(models.Model):
    """Who is typing in a room, until when."""

    conversation = models.ForeignKey(
        conversation_model_name(), on_delete=models.CASCADE, related_name="+"
    )
    participant = models.ForeignKey(
        participant_model_name(), on_delete=models.CASCADE, related_name="+"
    )
    until = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["conversation", "participant"], name="chat_ui_typing_unique"
            )
        ]

    def __str__(self) -> str:
        return f"{self.participant_id} until {self.until:%H:%M:%S}"


class StreamEntry(models.Model):
    """What a ``/sync`` reads: one change, for everyone in ``conversation``
    or only for ``recipient``. Its id is the position of ``next_batch``.

    ``kind``: ``event`` (of a timeline), ``ephemeral`` (typing, receipts, a
    message being written), ``account_data``, ``join`` and ``leave`` (of the
    recipient), ``unread`` (their count changed)."""

    created = models.DateTimeField(default=timezone.now, db_index=True)
    conversation = models.ForeignKey(
        conversation_model_name(),
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="+",
    )
    recipient = models.ForeignKey(
        participant_model_name(),
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="+",
    )
    kind = models.CharField(max_length=20)
    event = models.ForeignKey(
        RoomEvent,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="stream_entries",
    )
    type = models.CharField(max_length=255, blank=True)
    data = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = _("stream entry")
        verbose_name_plural = _("stream entries")
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.pk} {self.kind} {self.type}"


def media_path(instance: Media, filename: str) -> str:
    # A name nobody can guess; the original is kept in `name`.
    return f"chat_ui/{uuid.uuid4().hex}{PurePath(filename).suffix.lower()}"


def new_media_id() -> str:
    return secrets.token_urlsafe(18)


class Media(models.Model):
    """A file uploaded (``mxc://server/<media_id>``), served only to its
    uploader and to the participants of the conversation it was sent to."""

    media_id = models.CharField(max_length=64, unique=True, default=new_media_id)
    conversation = models.ForeignKey(
        conversation_model_name(),
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="+",
    )
    uploader = models.ForeignKey(
        participant_model_name(), on_delete=models.SET_NULL, null=True, related_name="+"
    )
    file = models.FileField(_("file"), upload_to=media_path)
    name = models.CharField(_("name"), max_length=255)
    mime = models.CharField(_("type"), max_length=100)
    size = models.PositiveBigIntegerField(_("size"))
    created = models.DateTimeField(_("created"), default=timezone.now)

    class Meta:
        verbose_name = _("media")
        verbose_name_plural = _("media")

    def __str__(self) -> str:
        return self.name


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class AccessToken(models.Model):
    """A Matrix client's login (``POST /login``): only its hash is kept."""

    participant = models.ForeignKey(
        participant_model_name(), on_delete=models.CASCADE, related_name="+"
    )
    digest = models.CharField(max_length=64, unique=True)
    device_id = models.CharField(max_length=255)
    created = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = _("access token")
        verbose_name_plural = _("access tokens")

    def __str__(self) -> str:
        return f"{self.participant} · {self.device_id}"


class AccountData(models.Model):
    """A client's own data (``m.fully_read``, a setting): global, or of a
    room."""

    participant = models.ForeignKey(
        participant_model_name(), on_delete=models.CASCADE, related_name="+"
    )
    conversation = models.ForeignKey(
        conversation_model_name(),
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="+",
    )
    type = models.CharField(max_length=255)
    content = models.JSONField(default=dict)

    def __str__(self) -> str:
        return self.type


class SyncFilter(models.Model):
    """A filter a client uploaded (``POST /user/{userId}/filter``)."""

    participant = models.ForeignKey(
        participant_model_name(), on_delete=models.CASCADE, related_name="+"
    )
    definition = models.JSONField(default=dict)

    def __str__(self) -> str:
        return f"filter {self.pk}"

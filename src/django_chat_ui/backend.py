"""What a site decides: who is chatting, what they see, what conversations
they can start and what happens when someone writes. Subclass
``ChatBackend`` and name it in the settings:

    CHAT_UI = {"BACKEND": "myapp.chat.Backend"}
"""

from __future__ import annotations

from collections.abc import Callable
from functools import cache
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils.module_loading import import_string
from django.utils.translation import gettext_lazy as _

from . import services
from .models import Conversation, Message, Participant

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from django.http import HttpRequest

SESSION_KEY = "django_chat_ui_participant"

#: A command of an extension: ``(backend, request, participant, data)`` →
#: the ``ack``'s data, or a list of frames ending with it.
CommandHandler = Callable[["ChatBackend", "HttpRequest", Participant, dict], Any]


class ChatBackend:
    #: Whether visitors who aren't logged in can chat (the "contact us"
    #: widget of a public site). Each gets a participant kept in their
    #: session.
    allow_anonymous = False

    #: Commands of extensions, by their namespaced type (section 12).
    commands: dict[str, CommandHandler] = {}

    #: Largest upload, in bytes, when a conversation's ``attachments`` don't
    #: say.
    max_upload_size = 5 * 1024 * 1024

    # Who -------------------------------------------------------------------

    def get_participant(self, request: HttpRequest) -> Participant | None:
        """The participant of this request, or None (403). Users get one on
        their first request; staff are agents."""
        user = request.user
        if user.is_authenticated:
            return self.participant_for_user(user)
        if not self.allow_anonymous:
            return None
        pk = request.session.get(SESSION_KEY)
        participant = Participant.objects.filter(pk=pk, user=None).first()
        if participant is None:
            participant = Participant.objects.create(
                kind="contact", name=str(_("Visitor"))
            )
            request.session[SESSION_KEY] = participant.pk
        return participant

    def participant_for_user(self, user: Any) -> Participant:
        participant, _ = Participant.objects.get_or_create(
            user=user,
            defaults={
                "kind": "agent" if user.is_staff else "user",
                "name": user.get_full_name() or user.get_username(),
            },
        )
        return participant

    # What they see ---------------------------------------------------------

    def conversations(self, participant: Participant) -> QuerySet[Conversation]:
        """The conversations ``participant`` sees: those they take part in.
        The stream only carries events of these."""
        return Conversation.objects.filter(memberships__participant=participant)

    def session_capabilities(self, participant: Participant) -> dict[str, Any]:
        """``ready.capabilities``: those of every conversation (8.2)."""
        return {}

    # Starting conversations ------------------------------------------------

    def can_start(
        self, participant: Participant, others: list[Participant], channel: str
    ) -> bool:
        """Whether ``participant`` may start a conversation with ``others``.
        Agents, with anyone; everybody else, only with the support team
        (``others`` empty)."""
        return participant.kind == "agent" or not others

    def start(
        self,
        request: HttpRequest,
        participant: Participant,
        others: list[Participant],
        channel: str,
    ) -> Conversation:
        """A new conversation. Without ``others`` (the "contact us" widget)
        it goes to ``support_team()`` and waits, ``pending``, for one of them
        to answer."""
        team = [] if others else self.support_team(channel)
        conversation = services.create_conversation(
            [participant, *others, *team],
            channel=channel,
            # The team's inbox names it after whoever wrote, not the team.
            title="" if others else participant.name,
            state="open" if others else "pending",
            capabilities=self.new_capabilities(channel),
        )
        self.on_start(request, conversation, participant)
        return conversation

    def support_team(self, channel: str) -> list[Participant]:
        """Who receives conversations started without anyone: every active
        staff user. Override it to route them (a queue, a bot first…)."""
        users = get_user_model().objects.filter(is_staff=True, is_active=True)
        return [self.participant_for_user(user) for user in users]

    def new_capabilities(self, channel: str) -> dict[str, Any]:
        """The capabilities of the conversations it starts (section 6.1)."""
        return {
            "typing": True,
            "receipts": True,
            "history": True,
            "replies": True,
            "attachments": {
                "types": ["image", "file"],
                "maxSize": self.max_upload_size,
            },
            "composer": {"mode": "free", "maxLength": 4096},
        }

    # What happens ----------------------------------------------------------

    def on_start(
        self, request: HttpRequest, conversation: Conversation, participant: Participant
    ) -> None:
        """After a conversation is started: a greeting, a bot…"""

    def on_message(self, request: HttpRequest, message: Message) -> None:
        """After someone sent a message: a bot's answer, sending it on to
        WhatsApp… Long work belongs in a task queue: this runs inside the
        request of the command."""

    def on_action(
        self,
        request: HttpRequest,
        participant: Participant,
        message: Message,
        button: dict[str, Any],
    ) -> None:
        """After someone used a button of ``message``. By default the
        button's label is written as their answer, as WhatsApp does."""
        services.post(
            message.conversation,
            participant,
            [{"type": "text", "text": str(button.get("label", button["id"]))}],
        )

    def validate_parts(
        self, conversation: Conversation, participant: Participant, parts: list[dict]
    ) -> None:
        """Raise ``ProtocolError`` for parts ``participant`` can't send. The
        commands already checked the composer and attachments; extension
        parts get here (allowed, with their ``fallback``)."""


@cache
def _backend_class(path: str) -> type[ChatBackend]:
    return import_string(path)


def get_backend() -> ChatBackend:
    config = getattr(settings, "CHAT_UI", {})
    path = config.get("BACKEND", "django_chat_ui.backend.ChatBackend")
    return _backend_class(path)()

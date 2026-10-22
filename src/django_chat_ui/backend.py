"""What a site decides: who is chatting, what they see, what conversations
they can start and what happens when someone writes. Subclass
``ChatBackend`` and name it in the settings:

    CHAT_UI = {"BACKEND": "myapp.chat.Backend"}
"""

from __future__ import annotations

import logging
import threading
from functools import cache
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.db import connections, transaction
from django.utils.module_loading import import_string
from django.utils.translation import gettext_lazy as _

from . import services
from .models import (
    AbstractConversation,
    AbstractParticipant,
    RoomEvent,
    get_conversation_model,
    get_participant_model,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.db.models import QuerySet
    from django.http import HttpRequest

SESSION_KEY = "django_chat_ui_participant"

logger = logging.getLogger("django_chat_ui")


class ChatBackend:
    #: Whether visitors who aren't logged in can chat (the "contact us"
    #: widget of a public site). Each gets a participant kept in their
    #: session.
    allow_anonymous = False

    #: Where the hooks that react (``on_start``, ``on_message``,
    #: ``on_action``, ``on_event``) run: ``"inline"``, inside the request
    #: that caused them, or ``"thread"``, in a thread of their own once its
    #: changes are committed, so it's answered at once (a bot that takes
    #: seconds doesn't hold the sender's message). For a task queue,
    #: override ``run_hook()``.
    hooks = "inline"

    #: The types of events of extensions that clients may send, besides
    #: messages and reactions: namespaced (``com.acme.order.cancel``). Each
    #: sent reaches ``on_event()``, after ``validate_content()``.
    event_types: frozenset[str] | set[str] = frozenset()

    #: Largest upload, in bytes, when a conversation's ``attachments`` don't
    #: say.
    max_upload_size = 5 * 1024 * 1024

    # Who -------------------------------------------------------------------

    def get_participant(self, request: HttpRequest) -> AbstractParticipant | None:
        """The participant of this request, or None (403). Users get one on
        their first request; staff are agents."""
        user = request.user
        if user.is_authenticated:
            return self.participant_for_user(user)
        if not self.allow_anonymous:
            return None
        pk = request.session.get(SESSION_KEY)
        participant = get_participant_model().objects.filter(pk=pk, user=None).first()
        if participant is None:
            participant = get_participant_model().objects.create(
                kind="contact", name=str(_("Visitor"))
            )
            request.session[SESSION_KEY] = participant.pk
        return participant

    def login(
        self, request: HttpRequest, username: str, password: str
    ) -> AbstractParticipant | None:
        """The participant of a Matrix client logging in with a password
        (``POST /login``): a user of the site's, with theirs."""
        user = authenticate(request, username=username, password=password)
        if user is None or not user.is_active:
            return None
        return self.participant_for_user(user)

    def participant_for_user(self, user: Any) -> AbstractParticipant:
        participant, _ = get_participant_model().objects.get_or_create(
            user=user,
            defaults={
                "kind": "agent" if user.is_staff else "user",
                "name": user.get_full_name() or user.get_username(),
            },
        )
        return participant

    # What they see ---------------------------------------------------------

    def conversations(
        self, participant: AbstractParticipant
    ) -> QuerySet[AbstractConversation]:
        """The conversations ``participant`` sees: those they take part in.
        The stream only carries events of these."""
        return get_conversation_model().objects.filter(
            memberships__participant=participant
        )

    def serialize_participant(
        self, participant: AbstractParticipant, data: dict[str, Any]
    ) -> dict[str, Any]:
        """This package's block of a participant's ``m.room.member`` (its
        ``kind``, ``handle``, ``avatar`` and ``ext``): add what a site's
        model has, under ``ext`` with your namespace (``{"com.acme": …}``)."""
        return data

    def serialize_conversation(
        self, conversation: AbstractConversation, data: dict[str, Any]
    ) -> dict[str, Any]:
        """This package's state event of what a conversation is (its
        ``channel``, ``state`` and ``ext``): add what a site's model has (its
        priority, who it's assigned to…), under ``ext``."""
        return data

    # Starting conversations ------------------------------------------------

    def can_start(
        self,
        participant: AbstractParticipant,
        others: list[AbstractParticipant],
        channel: str,
    ) -> bool:
        """Whether ``participant`` may start a conversation with ``others``.
        Agents, with anyone; everybody else, only with the support team
        (``others`` empty)."""
        return participant.kind == "agent" or not others

    def start(
        self,
        request: HttpRequest,
        participant: AbstractParticipant,
        others: list[AbstractParticipant],
        channel: str,
    ) -> AbstractConversation:
        """A new conversation (``POST /createRoom``). Without ``others`` (the
        "contact us" widget) it goes to ``support_team()`` and waits,
        ``pending``, for one of them to answer."""
        team = [] if others else self.support_team(channel)
        conversation = services.create_conversation(
            [participant, *others, *team],
            channel=channel,
            # The team's inbox names it after whoever wrote, not the team.
            title="" if others else participant.name,
            state="open" if others else "pending",
            capabilities=self.new_capabilities(channel),
            creator=participant,
        )
        self.run_hook(self.on_start, request, conversation, participant)
        return conversation

    def support_team(self, channel: str) -> list[AbstractParticipant]:
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

    def run_hook(self, hook: Callable[..., Any], *args: Any) -> None:
        """Run a hook that reacts to a command, as ``hooks`` says. Override
        it to send them to a task queue (Celery, ``django.tasks``…)."""
        if self.hooks == "thread":
            transaction.on_commit(
                lambda: threading.Thread(
                    target=self.run_hook_now, args=(hook, *args), daemon=True
                ).start()
            )
        else:
            hook(*args)

    def run_hook_now(self, hook: Callable[..., Any], *args: Any) -> None:
        """Run a hook away from its request: its failure is logged, and its
        thread's database connection closed."""
        try:
            hook(*args)
        except Exception:
            logger.exception("django-chat-ui: %s failed", hook.__name__)
        finally:
            connections.close_all()

    def before_send(
        self,
        request: HttpRequest,
        conversation: AbstractConversation,
        participant: AbstractParticipant,
        event_type: str,
        content: dict[str, Any],
    ) -> None:
        """Just before a client's event is added (checked against what the
        conversation allows): what must come first in the thread ("Ana
        joined"), or a last refusal (raise ``MatrixError``). Always inline."""

    def on_start(
        self,
        request: HttpRequest,
        conversation: AbstractConversation,
        participant: AbstractParticipant,
    ) -> None:
        """After a conversation is started: a greeting, a bot…"""

    def on_message(self, request: HttpRequest, message: RoomEvent) -> None:
        """After someone sent a message (not an edit, nor a button's
        answer): a bot's answer, sending it on to WhatsApp… It runs as
        ``hooks`` says."""

    def on_action(
        self,
        request: HttpRequest,
        participant: AbstractParticipant,
        message: RoomEvent,
        button: dict[str, Any],
    ) -> None:
        """After someone used a button of ``message``: their answer (the
        button's label, as WhatsApp writes it) is in the thread already."""

    def on_event(self, request: HttpRequest, event: RoomEvent) -> None:
        """After a client sent an event of ``event_types``."""

    def validate_content(
        self,
        conversation: AbstractConversation,
        participant: AbstractParticipant,
        event_type: str,
        content: dict[str, Any],
    ) -> None:
        """Raise ``MatrixError`` for an event ``participant`` can't send.
        What the conversation allows is checked already; messages of
        extensions' types (namespaced ``msgtype``, with a ``body``) and
        events of ``event_types`` get here, allowed."""


@cache
def _backend_class(path: str) -> type[ChatBackend]:
    return import_string(path)


def get_backend() -> ChatBackend:
    config = getattr(settings, "CHAT_UI", {})
    path = config.get("BACKEND", "django_chat_ui.backend.ChatBackend")
    return _backend_class(path)()

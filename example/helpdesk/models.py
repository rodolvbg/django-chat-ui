"""The shop's own models of the chat: each conversation is a ticket, with
a priority and someone of the team assigned to it, and each participant a
contact, with their company. They take the place of django_chat_ui's
(CHAT_UI_CONVERSATION_MODEL = "helpdesk.Ticket",
CHAT_UI_PARTICIPANT_MODEL = "helpdesk.Contact")."""

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from django_chat_ui.models import AbstractConversation, AbstractParticipant


class Contact(AbstractParticipant):
    company = models.CharField(max_length=200, blank=True)

    class Meta(AbstractParticipant.Meta):
        verbose_name = _("contact")
        verbose_name_plural = _("contacts")


PRIORITIES = [(0, _("Low")), (1, _("Normal")), (2, _("High"))]


class Ticket(AbstractConversation):
    priority = models.IntegerField(choices=PRIORITIES, default=1)
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tickets",
    )

    class Meta(AbstractConversation.Meta):
        verbose_name = _("ticket")
        verbose_name_plural = _("tickets")

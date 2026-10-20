from django.contrib import admin

from django_chat_ui.admin import ConversationAdmin, ParticipantAdmin

from .models import Contact, Ticket


@admin.register(Contact)
class ContactAdmin(ParticipantAdmin):
    list_display = [*ParticipantAdmin.list_display, "company"]


@admin.register(Ticket)
class TicketAdmin(ConversationAdmin):
    list_display = [*ConversationAdmin.list_display, "priority", "assignee"]
    list_filter = [*ConversationAdmin.list_filter, "priority"]
    raw_id_fields = ["assignee"]

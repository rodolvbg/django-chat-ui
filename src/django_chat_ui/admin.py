"""The conversations in the admin: to look at them, not to chat (changes
made here reach no open interface; use the services or the chat).

With models of a site's own (``CHAT_UI_CONVERSATION_MODEL``,
``CHAT_UI_PARTICIPANT_MODEL``), register them with these classes, as one
does with ``UserAdmin``:

    @admin.register(Ticket)
    class TicketAdmin(ConversationAdmin):
        list_display = [*ConversationAdmin.list_display, "priority"]
"""

from django.contrib import admin

from .models import (
    Conversation,
    Media,
    Membership,
    Participant,
    RoomEvent,
    StreamEntry,
)


class ParticipantAdmin(admin.ModelAdmin):
    list_display = ["__str__", "kind", "handle", "user", "created"]
    list_filter = ["kind"]
    search_fields = ["name", "handle"]
    raw_id_fields = ["user"]


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0
    raw_id_fields = ["participant", "last_read"]


class RoomEventInline(admin.TabularInline):
    model = RoomEvent
    fk_name = "conversation"
    extra = 0
    fields = ["created", "sender", "type", "content"]
    readonly_fields = ["created", "sender", "type", "content"]
    can_delete = False
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False


class ConversationAdmin(admin.ModelAdmin):
    list_display = ["__str__", "channel", "state", "updated"]
    list_filter = ["channel", "state"]
    search_fields = ["title"]
    inlines = [MembershipInline, RoomEventInline]


def register_models(site: admin.AdminSite) -> None:
    """This package's models, unless a site swapped them for its own."""
    if not Participant._meta.swapped:
        site.register(Participant, ParticipantAdmin)
    if not Conversation._meta.swapped:
        site.register(Conversation, ConversationAdmin)


register_models(admin.site)


@admin.register(RoomEvent)
class RoomEventAdmin(admin.ModelAdmin):
    list_display = ["__str__", "type", "conversation", "sender", "created"]
    list_filter = ["type", "conversation__channel"]
    raw_id_fields = ["conversation", "sender", "relates_to", "redacted_by"]


@admin.register(Media)
class MediaAdmin(admin.ModelAdmin):
    list_display = ["name", "conversation", "mime", "size", "created"]
    raw_id_fields = ["conversation", "uploader"]


@admin.register(StreamEntry)
class StreamEntryAdmin(admin.ModelAdmin):
    list_display = ["__str__", "kind", "type", "conversation", "recipient", "created"]
    list_filter = ["kind"]
    raw_id_fields = ["conversation", "recipient", "event"]

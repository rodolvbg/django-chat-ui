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

from .models import Attachment, Conversation, Membership, Message, Participant


class ParticipantAdmin(admin.ModelAdmin):
    list_display = ["__str__", "kind", "handle", "user", "created"]
    list_filter = ["kind"]
    search_fields = ["name", "handle"]
    raw_id_fields = ["user"]


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0
    raw_id_fields = ["participant", "last_read"]


class MessageInline(admin.TabularInline):
    model = Message
    extra = 0
    fields = ["created", "author", "parts", "status"]
    readonly_fields = ["created", "author", "parts", "status"]
    can_delete = False
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False


class ConversationAdmin(admin.ModelAdmin):
    list_display = ["__str__", "channel", "state", "updated"]
    list_filter = ["channel", "state"]
    search_fields = ["title"]
    readonly_fields = ["last_message"]
    inlines = [MembershipInline, MessageInline]


def register_models(site: admin.AdminSite) -> None:
    """This package's models, unless a site swapped them for its own."""
    if not Participant._meta.swapped:
        site.register(Participant, ParticipantAdmin)
    if not Conversation._meta.swapped:
        site.register(Conversation, ConversationAdmin)


register_models(admin.site)


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ["__str__", "conversation", "author", "status", "created"]
    list_filter = ["status", "conversation__channel"]
    raw_id_fields = ["conversation", "author", "reply_to"]


@admin.register(Attachment)
class AttachmentAdmin(admin.ModelAdmin):
    list_display = ["name", "conversation", "mime", "size", "created"]
    raw_id_fields = ["conversation", "uploader"]

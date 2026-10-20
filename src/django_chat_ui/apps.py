from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class ChatUiConfig(AppConfig):
    name = "django_chat_ui"
    verbose_name = _("Chat")
    default_auto_field = "django.db.models.BigAutoField"

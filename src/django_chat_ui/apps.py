from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class ChatUiConfig(AppConfig):
    name = "django_chat_ui"
    verbose_name = _("Chat")
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from django.conf import settings

        from .models import DEFAULTS

        # Always there, as AUTH_USER_MODEL is: migrations (this package's,
        # and a site's pointing to its models) name them.
        for name, default in DEFAULTS.items():
            if not hasattr(settings, name):
                setattr(settings, name, default)

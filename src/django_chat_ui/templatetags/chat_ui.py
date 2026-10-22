"""``{% chat_ui %}``: what a page needs for the components to chat with
this site — the stylesheet, the configuration (the homeserver's base URL,
CSRF token, translated texts) as a JSON data block, and the module that connects them.
Nothing inline runs: it works under a strict Content Security Policy.

    {% load chat_ui %}
    <head>… {% chat_ui %} …</head>
    <body>… <chat-inbox></chat-inbox> or <chat-widget></chat-widget> …</body>
"""

from __future__ import annotations

from typing import Any

from django import template
from django.middleware.csrf import get_token
from django.urls import reverse

from ..texts import texts

register = template.Library()


@register.inclusion_tag("django_chat_ui/chat_ui.html", takes_context=True)
def chat_ui(context: template.Context, poll: int = 0) -> dict[str, Any]:
    """The components sync with long polling (``GET /sync``, which under
    ASGI holds no thread); ``poll``: every that many milliseconds instead,
    where long-lived requests can't be had."""
    request = context.get("request")
    base = reverse("django_chat_ui:versions").removesuffix("/_matrix/client/versions")
    return {
        "config": {
            "baseUrl": base,
            "csrfToken": get_token(request) if request is not None else "",
            "poll": int(poll),
            "texts": texts(),
        },
    }

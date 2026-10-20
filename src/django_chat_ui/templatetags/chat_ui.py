"""``{% chat_ui %}``: what a page needs for the components to chat with
this site — the stylesheet, the configuration (endpoints, CSRF token,
translated texts) as a JSON data block, and the module that connects them.
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

TRANSPORTS = {"sse", "polling", "websocket"}


@register.inclusion_tag("django_chat_ui/chat_ui.html", takes_context=True)
def chat_ui(
    context: template.Context, transport: str = "sse", poll: int = 3000
) -> dict[str, Any]:
    """``transport``: ``sse`` (Server-Sent Events), ``polling`` (every
    ``poll`` milliseconds, where long-lived connections can't be had) or
    ``websocket`` (with Channels: ``django_chat_ui.routing``)."""
    request = context.get("request")
    commands = reverse("django_chat_ui:commands")
    return {
        "config": {
            "events": reverse("django_chat_ui:events"),
            "commands": commands,
            "websocket": commands.removesuffix("commands") + "ws",
            "uploads": reverse("django_chat_ui:uploads"),
            "csrfToken": get_token(request) if request is not None else "",
            "transport": transport if transport in TRANSPORTS else "sse",
            "poll": int(poll),
            "texts": texts(),
        },
    }

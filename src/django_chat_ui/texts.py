"""The texts of the interface, translated: what ``{% chat_ui %}`` gives the
components (``element.texts``), in the request's language.

The keys are those of ``TEXTS`` (chat-thread.js), ``INBOX_TEXTS``
(chat-inbox.js) and ``WIDGET_TEXTS`` (chat-widget.js). ``%(name)s`` and
``%(count)s`` are filled in by the components.
"""

from __future__ import annotations

from django.utils.translation import pgettext_lazy

THREAD = {
    "placeholder": pgettext_lazy("chat", "Write a message…"),
    "send": pgettext_lazy("chat", "Send"),
    "attach": pgettext_lazy("chat", "Attach"),
    "retry": pgettext_lazy("chat", "Retry"),
    "failed": pgettext_lazy("chat", "Not sent"),
    "edited": pgettext_lazy("chat", "edited"),
    "earlier": pgettext_lazy("chat", "Load earlier messages"),
    "typingOne": pgettext_lazy("chat", "%(name)s is typing…"),
    "typingMany": pgettext_lazy("chat", "Several people are typing…"),
    "actionsOnly": pgettext_lazy("chat", "Choose one of the options above."),
    "closed": pgettext_lazy("chat", "This conversation is closed."),
    "template": pgettext_lazy("chat", "Template"),
    "sendTemplate": pgettext_lazy("chat", "Send template"),
    "unsupported": pgettext_lazy("chat", "This content can't be shown here."),
    "sending": pgettext_lazy("chat", "Sending"),
    "sent": pgettext_lazy("chat", "Sent"),
    "delivered": pgettext_lazy("chat", "Delivered"),
    "read": pgettext_lazy("chat", "Read"),
    "log": pgettext_lazy("chat", "Messages"),
    "react": pgettext_lazy("chat", "React"),
    "you": pgettext_lazy("chat", "You"),
}

INBOX = {
    "search": pgettext_lazy("chat", "Search conversations"),
    "empty": pgettext_lazy("chat", "No conversations yet."),
    "noResults": pgettext_lazy("chat", "No conversation matches."),
    "back": pgettext_lazy("chat", "Back to conversations"),
    "unread": pgettext_lazy("chat", "%(count)s unread"),
    "pick": pgettext_lazy("chat", "Pick a conversation."),
    "image": pgettext_lazy("chat", "Photo"),
    "video": pgettext_lazy("chat", "Video"),
    "audio": pgettext_lazy("chat", "Audio"),
    "voice": pgettext_lazy("chat", "Voice message"),
    "location": pgettext_lazy("chat", "Location"),
    "you": pgettext_lazy("chat", "You"),
}

WIDGET = {
    "open": pgettext_lazy("chat", "Chat with us"),
    "close": pgettext_lazy("chat", "Close the chat"),
    "heading": pgettext_lazy("chat", "Chat"),
    "unread": pgettext_lazy("chat", "%(count)s unread"),
}


def texts() -> dict[str, dict[str, str]]:
    """Every text, in the active language."""
    return {
        "thread": {key: str(value) for key, value in THREAD.items()},
        "inbox": {key: str(value) for key, value in INBOX.items()},
        "widget": {key: str(value) for key, value in WIDGET.items()},
    }

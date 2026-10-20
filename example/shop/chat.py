"""The chat of the shop: an assistant greets whoever opens the widget and
answers its buttons, streaming; the staff take over from the inbox.

A real bot (or WhatsApp) would answer from a task queue; this one answers
inside the request, sleeping a little between words, to be seen writing.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from django_chat_ui import services
from django_chat_ui.backend import ChatBackend
from django_chat_ui.models import Conversation, Message, Participant

if TYPE_CHECKING:
    from django.http import HttpRequest

MENU = [
    {"id": "order", "label": "My order"},
    {"id": "sizes", "label": "Sizes"},
    {"id": "human", "label": "Talk to someone"},
]

ANSWERS = {
    "order": ["Your order ", "**A-1029** ", "ships today ", "with UPS."],
    "sizes": [
        "Our T-shirts ",
        "run true to size: ",
        "if in doubt, ",
        "take your usual one.",
    ],
    "human": ["Putting you through ", "to someone ", "on the team, ", "one moment."],
}


def assistant() -> Participant:
    bot, _ = Participant.objects.get_or_create(
        kind="bot", handle="shop-assistant", defaults={"name": "Assistant"}
    )
    return bot


def say(conversation: Conversation, chunks: list[str], delay: float = 0.12) -> Message:
    message = services.start_stream(conversation, assistant())
    for chunk in chunks:
        time.sleep(delay)
        services.delta(message, chunk)
    return services.finish(
        message, [{"type": "text", "format": "markdown", "text": "".join(chunks)}]
    )


class DemoBackend(ChatBackend):
    allow_anonymous = True
    # The assistant takes its time: the visitor's message is sent at once.
    hooks = "thread"

    def new_capabilities(self, channel: str) -> dict[str, Any]:
        return {
            **super().new_capabilities(channel),
            "buttons": True,
            "streaming": True,
            "reactions": True,
        }

    def support_team(self, channel: str) -> list[Participant]:
        return [*super().support_team(channel), assistant()]

    def on_start(self, request, conversation, participant) -> None:
        services.post(
            conversation,
            assistant(),
            [
                {
                    "type": "text",
                    "text": "Hi! I'm the shop's assistant. How can I help?",
                },
                {
                    "type": "buttons",
                    "buttons": MENU,
                    "fallback": " / ".join(b["label"] for b in MENU),
                },
            ],
        )

    def on_action(self, request, participant, message, button) -> None:
        super().on_action(request, participant, message, button)  # Their answer.
        say(message.conversation, ANSWERS.get(button["id"], ["OK."]))

    def before_send(self, request, conversation, participant, parts) -> None:
        if participant.kind == "agent" and conversation.state == "pending":
            # Someone of the team answers: it's theirs now, and it says so
            # before their first message.
            services.update_conversation(conversation, state="open")
            services.system(conversation, f"{participant.name} joined", code="joined")

    def on_message(self, request: HttpRequest, message: Message) -> None:
        conversation = message.conversation
        author = message.author
        if author is None or conversation.state != "pending":
            return
        if author.kind in {"contact", "user"}:
            say(
                conversation,
                ["Thanks. ", "Someone will ", "answer you shortly."],
            )

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
    {"id": "order", "label": "Mi pedido"},
    {"id": "sizes", "label": "Tallas"},
    {"id": "human", "label": "Hablar con alguien"},
]

ANSWERS = {
    "order": ["Tu pedido ", "**A-1029** ", "sale hoy ", "con MRW."],
    "sizes": [
        "Las camisetas ",
        "tallan normal: ",
        "si dudas, ",
        "coge tu talla de siempre.",
    ],
    "human": ["Te paso ", "con una persona ", "del equipo, ", "en un momento."],
}


def assistant() -> Participant:
    bot, _ = Participant.objects.get_or_create(
        kind="bot", handle="shop-assistant", defaults={"name": "Asistente"}
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

    def new_capabilities(self, channel: str) -> dict[str, Any]:
        return {**super().new_capabilities(channel), "buttons": True, "streaming": True}

    def support_team(self, channel: str) -> list[Participant]:
        return [*super().support_team(channel), assistant()]

    def on_start(self, request, conversation, participant) -> None:
        services.post(
            conversation,
            assistant(),
            [
                {
                    "type": "text",
                    "text": "¡Hola! Soy el asistente de la tienda. ¿En qué te ayudo?",
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
        say(message.conversation, ANSWERS.get(button["id"], ["Vale."]))

    def on_message(self, request: HttpRequest, message: Message) -> None:
        conversation = message.conversation
        author = message.author
        if author is None:
            return
        if author.kind == "agent" and conversation.state == "pending":
            # Someone of the team answered: it's theirs now.
            services.update_conversation(conversation, state="open")
            services.system(conversation, f"{author.name} se ha unido", code="joined")
        elif author.kind in {"contact", "user"} and conversation.state == "pending":
            say(
                conversation,
                ["Gracias. ", "Una persona del equipo ", "te contesta enseguida."],
            )

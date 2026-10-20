"""The chat of the shop: an assistant greets whoever opens the widget and
answers its buttons, streaming; the staff take over from the inbox.

With ANTHROPIC_API_KEY in the environment (and ``pip install anthropic``),
the assistant answers what visitors write with Claude, as it writes;
without, it says someone will answer. Its hooks run in a thread
(``hooks = "thread"``): a visitor's message is sent at once.
"""

from __future__ import annotations

import logging
import os
import time
from typing import TYPE_CHECKING, Any

from django_chat_ui import services
from django_chat_ui.backend import ChatBackend
from django_chat_ui.models import (
    AbstractConversation,
    AbstractParticipant,
    Message,
    get_participant_model,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from django.http import HttpRequest

logger = logging.getLogger(__name__)

SYSTEM = (
    "You are the assistant of a small shop of cotton T-shirts, chatting with a "
    "customer on its website. Answer briefly, in the customer's language. "
    "Orders ship in 1-2 days with UPS; the T-shirts run true to size; returns "
    "are free within 30 days. If you can't help, say that someone from the team "
    "will answer shortly."
)

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


def assistant() -> AbstractParticipant:
    bot, _ = get_participant_model().objects.get_or_create(
        kind="bot", handle="shop-assistant", defaults={"name": "Assistant"}
    )
    return bot


def slowly(chunks: list[str], delay: float) -> Iterator[str]:
    for chunk in chunks:
        time.sleep(delay)
        yield chunk


def say(
    conversation: AbstractConversation, chunks: list[str], delay: float = 0.12
) -> Message:
    """Words of its own, a little at a time (each chunk sent as it comes)."""
    return services.stream_text(
        conversation, assistant(), slowly(chunks, delay), every=0
    )


def history(conversation: AbstractConversation) -> list[dict[str, str]]:
    """The conversation as the model takes it: the assistant's turns and
    the others', starting with the customer's."""
    turns: list[dict[str, str]] = []
    for message in conversation.messages.exclude(author=None).select_related("author"):
        text = " ".join(
            str(part.get("text") or part.get("fallback") or "")
            for part in message.parts
        ).strip()
        if not text:
            continue
        role = "assistant" if message.author.kind == "bot" else "user"
        if turns and turns[-1]["role"] == role:
            turns[-1]["content"] += "\n" + text
        else:
            turns.append({"role": role, "content": text})
    while turns and turns[0]["role"] == "assistant":
        turns.pop(0)
    return turns


def ai_answer(conversation: AbstractConversation) -> bool:
    """Answer with Claude, streaming; False if there's no key (or SDK)."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False
    try:
        import anthropic
    except ImportError:
        return False
    client = anthropic.Anthropic()
    try:
        with client.messages.stream(
            model=os.environ.get("ANTHROPIC_MODEL", "claude-opus-5-5"),
            max_tokens=1024,
            system=SYSTEM,
            messages=history(conversation),
        ) as stream:
            services.stream_text(conversation, assistant(), stream.text_stream)
    except anthropic.APIError:
        logger.exception("The assistant couldn't answer")
        say(conversation, ["Sorry, ", "I can't answer now: ", "someone will shortly."])
    return True


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

    def serialize_participant(self, participant, data):
        # A contact's company (helpdesk.Contact), for the "shop" extension.
        if getattr(participant, "company", ""):
            data["ext"] = {
                **data.get("ext", {}),
                "shop": {"company": participant.company},
            }
        return data

    def serialize_conversation(self, conversation, data):
        # The fields of the shop's tickets (helpdesk.Ticket), for whoever
        # knows the "shop" extension; others ignore them.
        if hasattr(conversation, "priority"):
            assignee = conversation.assignee
            data["ext"] = {
                **data.get("ext", {}),
                "shop": {
                    "priority": conversation.get_priority_display().lower(),
                    "assignee": assignee.get_username() if assignee else None,
                },
            }
        return data

    def support_team(self, channel: str) -> list[AbstractParticipant]:
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
        conversation = message.conversation
        if button["id"] == "human":
            # The assistant leaves it to the team from now on.
            meta = {**conversation.meta, "human": True}
            services.update_conversation(conversation, meta=meta)
        say(conversation, ANSWERS.get(button["id"], ["OK."]))

    def before_send(self, request, conversation, participant, parts) -> None:
        if participant.kind == "agent" and conversation.state == "pending":
            # Someone of the team answers: it's theirs now, and it says so
            # before their first message.
            services.update_conversation(conversation, state="open")
            if hasattr(conversation, "assignee_id") and participant.user_id:
                # The ticket is theirs (a field of the shop's own model).
                type(conversation).objects.filter(pk=conversation.pk).update(
                    assignee_id=participant.user_id
                )
            services.system(conversation, f"{participant.name} joined", code="joined")

    def on_message(self, request: HttpRequest, message: Message) -> None:
        conversation = message.conversation
        author = message.author
        if author is None or conversation.state != "pending":
            return
        if author.kind in {"contact", "user"}:
            if conversation.meta.get("human") or not ai_answer(conversation):
                say(conversation, ["Thanks. ", "Someone will ", "answer you shortly."])

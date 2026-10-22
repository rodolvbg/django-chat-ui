"""An AI agent of any framework that speaks AG-UI (https://docs.ag-ui.com:
LangGraph, CrewAI, Mastra, Pydantic AI, Agno…) answering in a
conversation, as it writes.

    from django_chat_ui.agui import AgUiAgent

    agent = AgUiAgent("https://agents.example.com/shop")

    class Backend(ChatBackend):
        hooks = "thread"

        def on_message(self, request, message):
            if message.sender and message.sender.kind != "bot":
                agent.answer(message.conversation, bot)

The conversation goes to the agent as a run (``RunAgentInput``: its
messages, ``threadId`` the room's ID); each text message it streams back
(``TEXT_MESSAGE_START`` / ``_CONTENT`` / ``_END``, or ``_CHUNK``) is a
message of ``bot``, through ``services.stream_text()``. Other events reach
``handle()``, to override (tool calls, state…).
"""

from __future__ import annotations

import itertools
import json
import urllib.request
import uuid
from typing import TYPE_CHECKING, Any

from . import services
from .matrix import room_id

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator

    from .models import AbstractConversation, AbstractParticipant, RoomEvent

TEXT = {"TEXT_MESSAGE_CONTENT", "TEXT_MESSAGE_CHUNK"}


class AgUiError(Exception):
    """The agent's ``RUN_ERROR``."""

    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        self.code = code


def sse(lines: Iterable[bytes]) -> Iterator[dict[str, Any]]:
    """The events of a Server-Sent Events stream, as JSON objects."""
    data: list[str] = []
    for raw in lines:
        line = raw.decode("utf-8").rstrip("\r\n")
        if line.startswith("data:"):
            data.append(line[5:].removeprefix(" "))
        elif not line and data:
            try:
                event = json.loads("\n".join(data))
            except ValueError:
                event = None
            data = []
            if isinstance(event, dict):
                yield event
    if data:
        try:
            event = json.loads("\n".join(data))
        except ValueError:
            return
        if isinstance(event, dict):
            yield event


class AgUiAgent:
    """An AG-UI agent at ``url`` (``headers``: its authentication)."""

    def __init__(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout: float = 120,
        opener: Callable[..., Any] = urllib.request.urlopen,
    ):
        self.url = url
        self.headers = headers or {}
        self.timeout = timeout
        self.opener = opener

    def messages(
        self, conversation: AbstractConversation, bot: AbstractParticipant
    ) -> list[dict[str, Any]]:
        """The conversation as the agent takes it: the bot's messages are
        the assistant's; anyone else's, the user's (system notices left out).
        Edited messages, as they are now."""
        edits = {
            edit.relates_to_id: edit.content.get("m.new_content") or {}
            for edit in conversation.messages.filter(rel_type="m.replace")
        }
        result = []
        for message in conversation.messages.exclude(rel_type="m.replace").filter(
            redacted_by=None
        ):
            if message.sender_id is None:
                continue
            body = str(edits.get(message.pk, message.content).get("body", ""))
            if not body:
                continue
            role = "assistant" if message.sender_id == bot.pk else "user"
            result.append({"id": message.event_id, "role": role, "content": body})
        return result

    def run_input(
        self, conversation: AbstractConversation, bot: AbstractParticipant
    ) -> dict[str, Any]:
        """``RunAgentInput``: override it to give the agent tools, context or
        state."""
        return {
            "threadId": room_id(conversation),
            "runId": uuid.uuid4().hex,
            "state": {},
            "messages": self.messages(conversation, bot),
            "tools": [],
            "context": [],
            "forwardedProps": {},
        }

    def events(self, payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
        """Run the agent: its events, as they come."""
        request = urllib.request.Request(
            self.url,
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
                **self.headers,
            },
            method="POST",
        )
        with self.opener(request, timeout=self.timeout) as response:
            yield from sse(response)

    def handle(self, event: dict[str, Any], conversation: AbstractConversation) -> None:
        """An event that isn't text: ``RUN_STARTED``, tool calls, state…"""

    def answer(
        self, conversation: AbstractConversation, bot: AbstractParticipant
    ) -> list[RoomEvent]:
        """Run the agent on the conversation; its text messages, sent as
        ``bot`` as they're written. A ``RUN_ERROR`` raises ``AgUiError``,
        after sending what came."""
        error: list[AgUiError] = []

        def texts() -> Iterator[tuple[str, str]]:
            current = ""
            for event in self.events(self.run_input(conversation, bot)):
                kind = event.get("type")
                if kind == "TEXT_MESSAGE_START":
                    current = str(event.get("messageId") or current)
                elif kind in TEXT and isinstance(event.get("delta"), str):
                    current = str(event.get("messageId") or current)
                    yield current, event["delta"]
                elif kind == "RUN_ERROR":
                    error.append(
                        AgUiError(str(event.get("message", "")), event.get("code"))
                    )
                    return
                elif kind not in {"TEXT_MESSAGE_END"}:
                    self.handle(event, conversation)

        sent = []
        for _message, chunks in itertools.groupby(texts(), key=lambda item: item[0]):
            message = services.stream_text(
                conversation, bot, (delta for _id, delta in chunks)
            )
            if message is not None:
                sent.append(message)
        if error:
            raise error[0]
        return sent

"""An AG-UI agent answering in a conversation (agui.py)."""

import io
import json

import pytest

from django_chat_ui import content, services
from django_chat_ui.agui import AgUiAgent, AgUiError, sse
from django_chat_ui.matrix import STREAM
from django_chat_ui.models import StreamEntry, get_participant_model

pytestmark = pytest.mark.django_db


def stream(*events):
    """An SSE body of these events (dicts, or raw text)."""
    text = "".join(
        e if isinstance(e, str) else f"data: {json.dumps(e)}\n\n" for e in events
    )
    return io.BytesIO(text.encode())


class Opener:
    def __init__(self, body):
        self.body = body
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append((request, timeout))
        return self.body


@pytest.fixture
def bot(db):
    return get_participant_model().objects.create(kind="bot", name="Agent")


def test_sse():
    body = stream(
        ": a comment\n\n",
        'event: x\ndata: {"type": "A",\ndata: "n": 1}\n\n',
        "data: not json\n\n",
        "data: [1]\n\n",
        'data: {"type": "B"}',  # The last, without its blank line.
    )
    assert list(sse(body)) == [{"type": "A", "n": 1}, {"type": "B"}]
    assert list(sse(io.BytesIO(b"data: nope"))) == []
    assert list(sse(io.BytesIO(b"data: [2]"))) == []


def test_the_agent_answers_as_it_writes(conversation, customer, bot, agent):
    services.add_participant(conversation, bot)
    asked = services.send(conversation, customer, content.text("Where is it?"))
    services.edit(asked, content.text("Where is my order?"))
    services.send(conversation, bot, content.text("Hi!"))
    services.system(conversation, "Rodolfo joined")
    services.send(conversation, agent, {"msgtype": "m.text", "body": ""})
    gone = services.send(conversation, customer, content.text("x"))
    services.redact(gone)

    seen = []
    opener = Opener(
        stream(
            {"type": "RUN_STARTED", "threadId": "t", "runId": "r"},
            {"type": "TEXT_MESSAGE_START", "messageId": "m1", "role": "assistant"},
            {"type": "TEXT_MESSAGE_CONTENT", "messageId": "m1", "delta": "It ships "},
            {"type": "TEXT_MESSAGE_CONTENT", "messageId": "m1", "delta": "today."},
            {"type": "TEXT_MESSAGE_END", "messageId": "m1"},
            {"type": "TOOL_CALL_START", "toolCallId": "c"},
            {
                "type": "TEXT_MESSAGE_CHUNK",
                "messageId": "m2",
                "delta": "Anything else?",
            },
            {"type": "TEXT_MESSAGE_CHUNK", "delta": 3},
            {"type": "RUN_FINISHED"},
        )
    )

    class Agent(AgUiAgent):
        def handle(self, event, conversation):
            seen.append(event["type"])

    agent_ = Agent(
        "https://agents.test/shop", headers={"Authorization": "x"}, opener=opener
    )
    sent = agent_.answer(conversation, bot)

    assert [m.body for m in sent] == ["It ships today.", "Anything else?"]
    assert all(m.sender == bot for m in sent)
    # A chunk without text is the agent's own business, as any other event.
    assert seen == [
        "RUN_STARTED",
        "TOOL_CALL_START",
        "TEXT_MESSAGE_CHUNK",
        "RUN_FINISHED",
    ]
    assert StreamEntry.objects.filter(type=STREAM, data__done=True).count() == 0

    [(request, timeout)] = opener.requests
    assert request.full_url == "https://agents.test/shop"
    assert request.get_header("Authorization") == "x"
    assert request.get_header("Accept") == "text/event-stream"
    assert timeout == 120
    payload = json.loads(request.data)
    assert payload["threadId"] == f"!{conversation.pk}:localhost"
    assert payload["messages"] == [
        {"id": asked.event_id, "role": "user", "content": "Where is my order?"},
        {"id": payload["messages"][1]["id"], "role": "assistant", "content": "Hi!"},
    ]
    assert payload["tools"] == [] and payload["state"] == {}


def test_a_run_that_fails(conversation, bot):
    opener = Opener(
        stream(
            {"type": "TEXT_MESSAGE_CONTENT", "messageId": "m1", "delta": "Half"},
            {"type": "RUN_ERROR", "message": "Overloaded", "code": "busy"},
            {"type": "TEXT_MESSAGE_CONTENT", "messageId": "m1", "delta": "never"},
        )
    )
    with pytest.raises(AgUiError) as error:
        AgUiAgent("https://agents.test", opener=opener).answer(conversation, bot)
    assert (str(error.value), error.value.code) == ("Overloaded", "busy")
    assert conversation.messages.get().body == "Half"


def test_a_run_without_text(conversation, bot):
    opener = Opener(
        stream(
            {"type": "RUN_STARTED"},
            {"type": "TEXT_MESSAGE_CONTENT", "messageId": "m1", "delta": ""},
            {"type": "RUN_FINISHED"},
        )
    )
    assert (
        AgUiAgent("https://agents.test", opener=opener).answer(conversation, bot) == []
    )
    assert StreamEntry.objects.filter(type=STREAM).get().data["done"] is True


def test_the_real_opener():
    import urllib.request

    assert AgUiAgent("https://x").opener is urllib.request.urlopen

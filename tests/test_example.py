"""The example's backend: the assistant, and the staff taking over."""

import pytest

from django_chat_ui import content, services
from django_chat_ui.matrix import room_id
from django_chat_ui.models import get_conversation_model, get_participant_model

#: This package's model, or the example's (tests.settings_swapped).
Conversation = get_conversation_model()
Participant = get_participant_model()

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def demo(settings, monkeypatch):
    settings.CHAT_UI = {**settings.CHAT_UI, "BACKEND": "shop.chat.DemoBackend"}
    monkeypatch.setattr("shop.chat.time.sleep", lambda seconds: None)
    # Its hooks in the request here (in a thread, they wait for a commit
    # that a test's transaction never makes).
    monkeypatch.setattr("shop.chat.DemoBackend.hooks", "inline")


def texts(conversation):
    return [m.body for m in conversation.messages.filter(redacted_by=None)]


def start(client):
    """A visitor opens the widget: the room it starts."""
    from tests.conftest import Api

    api = Api(client)
    api.ok("GET", "/account/whoami")
    room = api.ok("POST", "/createRoom", {})["room_id"]
    return api, room, Conversation.objects.get(pk=room[1:].split(":")[0])


def test_a_visitor_is_greeted_and_answered(client, agent):
    from django_chat_ui.matrix import ACTION, BUTTONS

    api, room, conversation = start(client)
    assert conversation.capabilities["buttons"] is True
    assert {p.kind for p in conversation.participants.all()} == {
        "contact",
        "agent",
        "bot",
    }
    greeting = conversation.messages.get()
    assert greeting.content[BUTTONS]["buttons"][0] == {
        "id": "order",
        "label": "My order",
    }

    api.sent(
        room,
        {
            "msgtype": "m.text",
            "body": "x",
            ACTION: {"event_id": greeting.event_id, "button": "order"},
        },
    )
    assert texts(conversation)[1:] == [
        "My order",
        "Your order A-1029 ships today with UPS.",
    ]

    api.sent(room, {"msgtype": "m.text", "body": "And in size M?"})
    assert texts(conversation)[-1] == "Thanks. Someone will answer you shortly."


def test_the_staff_takes_over(agent_api, agent, customer):
    conversation = services.create_conversation([agent, customer], state="pending")
    room = room_id(conversation)
    agent_api.sent(room, {"msgtype": "m.text", "body": "Hi"})
    conversation.refresh_from_db()
    assert conversation.state == "open"
    assert texts(conversation) == ["Rodolfo joined", "Hi"]
    # Once open, nobody joins again, and the assistant stays quiet.
    agent_api.sent(room, {"msgtype": "m.text", "body": "Anything else?"})
    assert len(texts(conversation)) == 3


def test_system_messages_need_no_answer(rf, agent):
    from shop.chat import DemoBackend

    conversation = services.create_conversation([agent], state="pending")
    DemoBackend().on_message(rf.get("/"), services.system(conversation, "Hi"))
    assert conversation.messages.count() == 1


def test_demo_chat_fills_the_example(capsys):
    from django.core.management import call_command

    call_command("demo_chat")
    assert Conversation.objects.count() == 2
    assert Participant.objects.filter(kind="contact", name="Anna Smith").exists()
    call_command("demo_chat")  # Again: the users are there already.
    assert "admin / demo" in capsys.readouterr().out


def test_the_pages(client, agent_user):
    assert client.get("/").status_code == 200
    assert b"<chat-widget" in client.get("/").content
    assert client.get("/inbox/").status_code == 302
    client.force_login(agent_user)
    assert b"<chat-inbox>" in client.get("/inbox/").content


class FakeStream:
    """What anthropic's client.messages.stream() gives, without the network."""

    def __init__(self, chunks, error=None):
        self.chunks = chunks
        self.error = error

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @property
    def text_stream(self):
        yield from self.chunks
        if self.error:
            raise self.error


@pytest.fixture
def claude(monkeypatch):
    """A fake anthropic SDK, recording what it's asked."""
    import sys
    import types

    calls = []
    module = types.ModuleType("anthropic")

    class APIError(Exception):
        pass

    class Messages:
        def stream(self, **kwargs):
            calls.append(kwargs)
            return module.next_stream

    class Anthropic:
        messages = Messages()

    module.APIError = APIError
    module.Anthropic = Anthropic
    module.next_stream = FakeStream(["We ship ", "to **Hawaii**, ", "yes."])
    monkeypatch.setitem(sys.modules, "anthropic", module)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    module.calls = calls
    return module


def visitor_writes(client, text):
    api, room, conversation = start(client)
    api.sent(room, {"msgtype": "m.text", "body": text})
    return api, conversation


def test_the_assistant_answers_with_claude(client, agent, claude):
    _, conversation = visitor_writes(client, "Do you ship to Hawaii?")

    assert texts(conversation)[-1] == "We ship to Hawaii, yes."
    assert (
        "<strong>Hawaii</strong>"
        in conversation.messages.last().content["formatted_body"]
    )
    [call] = claude.calls
    assert call["model"] == "claude-opus-5-5"
    assert "T-shirts" in call["system"]
    # From the customer's first words (the greeting is left out).
    assert call["messages"] == [{"role": "user", "content": "Do you ship to Hawaii?"}]


def test_the_history_the_model_gets(agent, customer):
    from shop.chat import assistant, history

    conversation = services.create_conversation([agent, customer])
    bot = assistant()
    services.send(conversation, bot, content.text("Hi!"))
    services.send(conversation, customer, content.text("Hello"))
    services.send(
        conversation, customer, content.image("mxc://localhost/x", body="a photo")
    )
    services.system(conversation, "Rodolfo joined")
    services.send(conversation, bot, {"msgtype": "m.text", "body": " "})
    gone = services.send(conversation, customer, content.text("Oops"))
    services.redact(gone)
    services.send(conversation, agent, content.text("I'm here"))
    assert history(conversation) == [
        {"role": "user", "content": "Hello\na photo\nI'm here"},
    ]


def test_the_assistant_says_sorry_when_claude_fails(client, agent, claude):
    claude.next_stream = FakeStream(["We "], error=claude.APIError("overloaded"))
    _, conversation = visitor_writes(client, "Hi?")
    assert texts(conversation)[-2:] == [
        "We",  # what came before it failed, sent
        "Sorry, I can't answer now: someone will shortly.",
    ]


def test_without_a_key_or_the_sdk(client, agent, monkeypatch, claude):
    import sys

    monkeypatch.delenv("ANTHROPIC_API_KEY")
    _, conversation = visitor_writes(client, "Hi?")
    assert texts(conversation)[-1] == "Thanks. Someone will answer you shortly."

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setitem(sys.modules, "anthropic", None)  # not installed
    from shop.chat import ai_answer

    assert ai_answer(conversation) is False
    assert claude.calls == []


def test_after_asking_for_someone_no_ai(client, agent, claude):
    from django_chat_ui.matrix import ACTION

    api, room, conversation = start(client)
    menu = conversation.messages.get()
    api.sent(
        room,
        {
            "msgtype": "m.text",
            "body": "x",
            ACTION: {"event_id": menu.event_id, "button": "human"},
        },
    )
    conversation.refresh_from_db()
    assert conversation.meta == {"human": True}
    api.sent(room, {"msgtype": "m.text", "body": "Hi?"})
    assert texts(conversation)[-1] == "Thanks. Someone will answer you shortly."
    assert claude.calls == []

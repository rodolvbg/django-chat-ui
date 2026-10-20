"""The example's backend: the assistant, and the staff taking over."""

import pytest

from django_chat_ui import services
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
    return [
        " / ".join(p.get("text", p.get("fallback", "")) for p in m.parts)
        for m in conversation.messages.all()
    ]


def test_a_visitor_is_greeted_and_answered(client, agent):
    from tests.conftest import Chat

    chat = Chat(client)
    me = chat.hello()["me"]
    assert me["kind"] == "contact"

    frames = chat.ok("conversation.open", {"with": [], "channel": "web"})
    conversation = Conversation.objects.get(pk=frames[-1]["data"]["conversation"])
    assert conversation.capabilities["streaming"] is True
    assert {p.kind for p in conversation.participants.all()} == {
        "contact",
        "agent",
        "bot",
    }
    greeting = conversation.messages.get()
    assert greeting.parts[1]["buttons"][0] == {"id": "order", "label": "My order"}

    chat.ok(
        "action",
        {
            "conversation": str(conversation.pk),
            "message": str(greeting.pk),
            "button": "order",
        },
    )
    assert texts(conversation)[1:] == [
        "My order",
        "Your order **A-1029** ships today with UPS.",
    ]

    chat.ok(
        "message.send",
        {
            "conversation": str(conversation.pk),
            "clientId": "c1",
            "parts": [{"type": "text", "text": "And in size M?"}],
        },
    )
    assert texts(conversation)[-1] == "Thanks. Someone will answer you shortly."


def test_the_staff_takes_over(agent_chat, agent, customer):
    conversation = services.create_conversation(
        [agent, customer], state="pending", capabilities={"composer": {"mode": "free"}}
    )
    agent_chat.ok(
        "message.send",
        {
            "conversation": str(conversation.pk),
            "clientId": "c1",
            "parts": [{"type": "text", "text": "Hi"}],
        },
    )
    conversation.refresh_from_db()
    assert conversation.state == "open"
    assert texts(conversation) == ["Rodolfo joined", "Hi"]
    # Once open, nobody joins again, and the assistant stays quiet.
    agent_chat.ok(
        "message.send",
        {
            "conversation": str(conversation.pk),
            "clientId": "c2",
            "parts": [{"type": "text", "text": "Anything else?"}],
        },
    )
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

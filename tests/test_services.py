"""The services: the change, and the events every interface gets."""

import pytest

from django_chat_ui import protocol, services
from django_chat_ui.models import Event, Membership, Participant

pytestmark = pytest.mark.django_db


def text(value):
    return [{"type": "text", "text": value}]


def events(after):
    return list(Event.objects.filter(id__gt=after).order_by("id"))


def test_create_conversation_tells_each_participant(agent, customer, seq):
    conversation = services.create_conversation(
        [agent, customer, agent], channel="whatsapp", title="Ana", state="pending"
    )
    created = events(seq)
    assert [(e.type, e.recipient) for e in created] == [
        ("conversation.created", agent),
        ("conversation.created", customer),
    ]
    assert created[0].data["unread"] == 0
    assert created[0].data["title"] == "Ana"
    assert conversation.memberships.count() == 2


def test_post_updates_the_lists(agent, customer, conversation, seq):
    message = services.post(conversation, agent, text("Hola"), client_id="c_1")

    created, *updates = events(seq)
    assert created.type == "message.created"
    assert created.recipient is None
    assert created.data["clientId"] == "c_1"
    assert created.data["status"] == "sent"
    by = {e.recipient: e.data for e in updates}
    assert "unread" not in by[agent]
    assert by[customer]["unread"] == 1
    assert by[customer]["lastMessage"]["id"] == str(message.pk)
    conversation.refresh_from_db()
    assert conversation.last_message == message
    assert conversation.updated == message.created


def test_system_messages_have_no_author(conversation, seq):
    message = services.system(conversation, "Ana joined", code="joined")
    assert message.author is None
    assert message.parts == [{"type": "system", "text": "Ana joined", "code": "joined"}]
    assert "author" not in events(seq)[0].data
    assert services.system(conversation, "Closed").parts == [
        {"type": "system", "text": "Closed"}
    ]


def test_add_and_remove_participants(agent, customer, conversation, seq):
    bot = Participant.objects.create(kind="bot", name="Bot")
    services.add_participant(conversation, bot)
    services.add_participant(conversation, bot)  # Already there: nothing.

    kinds = [(e.type, e.recipient) for e in events(seq)]
    assert ("conversation.created", bot) in kinds
    assert kinds.count(("conversation.created", bot)) == 1
    assert ("conversation.updated", agent) in kinds

    seq = events(0)[-1].pk
    services.remove_participant(conversation, bot)
    services.remove_participant(conversation, bot)
    assert [(e.type, e.recipient) for e in events(seq)] == [
        ("conversation.removed", bot),
        ("conversation.updated", agent),
        ("conversation.updated", customer),
    ]


def test_update_conversation_merges_capabilities(conversation, seq):
    services.update_conversation(
        conversation, capabilities={"typing": False}, state="closed"
    )
    conversation.refresh_from_db()
    assert conversation.capabilities["typing"] is False
    assert conversation.capabilities["receipts"] is True
    assert conversation.state == "closed"
    [event] = events(seq)
    assert event.data["capabilities"] == {"typing": False}
    assert event.data["state"] == "closed"

    with pytest.raises(TypeError):
        services.update_conversation(conversation, channel="sms")


def test_update_message(agent, conversation, seq):
    message = services.post(conversation, agent, text("Hola"))
    seq = events(seq)[-1].pk
    services.update_message(message, status="delivered", meta={"wa": "wamid.1"})

    [event] = events(seq)
    assert event.data == {
        "id": str(message.pk),
        "conversation": str(conversation.pk),
        "status": "delivered",
        "meta": {"wa": "wamid.1"},
    }
    services.update_message(message, parts=text("Hola!"))
    assert "editedAt" in events(event.pk)[0].data
    with pytest.raises(TypeError):
        services.update_message(message, author=None)


def test_streaming(agent, conversation, seq):
    message = services.start_stream(conversation, agent)
    services.delta(message, "Tu pedido ")
    services.delta(message, "sale hoy.")
    services.delta(message, "Más", part=1)
    assert message.parts == [
        {"type": "text", "text": "Tu pedido sale hoy."},
        {"type": "text", "text": "Más"},
    ]

    services.finish(message, text("Final"))
    message.refresh_from_db()
    assert message.streaming is False
    assert message.edited is None
    assert message.parts == text("Final")

    kinds = [e.type for e in events(seq) if e.recipient is None]
    assert kinds == [
        "message.created",
        "message.delta",
        "message.delta",
        "message.delta",
        "message.updated",
        "conversation.updated",
    ]
    assert events(seq)[0].data["streaming"] is True

    # Lists learn its final text (it was created empty).
    [listed] = [
        e
        for e in events(seq)
        if e.type == "conversation.updated" and e.recipient is None
    ]
    assert listed.data["lastMessage"]["parts"] == text("Final")

    other = services.start_stream(conversation, agent, text("Hi"))
    services.finish(other)
    other.refresh_from_db()
    assert other.parts == text("Hi")


def test_read_without_receipts_leaves_statuses(agent, customer, conversation):
    services.update_conversation(conversation, capabilities={"receipts": False})
    message = services.post(conversation, agent, text("Hola"))
    services.read(conversation, customer, message)
    message.refresh_from_db()
    assert message.status == "sent"
    assert (
        Membership.objects.get(conversation=conversation, participant=customer).unread
        == 0
    )


def test_emit_an_extension_event(conversation, seq):
    services.emit("acme.order.updated", {"id": "A-1"}, conversation=conversation)
    assert events(seq)[0].frame() == {
        "type": "acme.order.updated",
        "seq": seq + 1,
        "data": {"id": "A-1"},
    }


def test_protocol_shapes(agent, conversation):
    agent.avatar = "https://example.com/a.png"
    agent.ext = {"acme": {"level": 2}}
    message = services.post(conversation, agent, text("Hi"))
    services.update_message(
        message, reactions=[{"emoji": "👍", "by": ["1"]}], deleted=True
    )
    message.refresh_from_db()
    assert protocol.participant(agent)["ext"] == {"acme": {"level": 2}}
    data = protocol.message(message)
    assert data["deleted"] is True
    assert data["reactions"] == [{"emoji": "👍", "by": ["1"]}]
    assert data["createdAt"].endswith("Z")
    assert len(data["createdAt"]) == len("2026-10-20T10:00:00.000Z")
    assert protocol.timestamp(None) is None
    assert "participants" not in protocol.conversation(conversation, participants=False)
    assert "unread" not in protocol.conversation(conversation)


@pytest.mark.parametrize(
    "name, expected",
    [
        ("acme.order", True),
        ("message.created", False),
        ("text", False),
        ("Acme.x", False),
        (5, False),
    ],
)
def test_namespaces(name, expected):
    assert protocol.is_namespaced(name) is expected


def test_strings(agent, conversation):
    message = services.post(conversation, agent, text("Hola"))
    assert str(message) == "Hola"
    assert str(
        services.post(conversation, agent, [{"type": "image", "url": "/x"}])
    ).startswith("message ")
    assert str(conversation) == f"web {conversation.pk}"
    assert str(agent) == "Rodolfo"
    assert str(Participant(kind="bot", pk=3)) == "bot 3"
    assert str(conversation.memberships.first()) == f"Rodolfo · web {conversation.pk}"
    assert str(Event.objects.first()).endswith("conversation.created")


def test_errors_without_a_message():
    error = protocol.ProtocolError("internal", retry=True)
    assert error.data() == {"code": "internal", "retry": True}
    assert str(error) == "internal"

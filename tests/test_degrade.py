"""What the server sends a client that can't render everything (6.2)."""

import pytest

from django_chat_ui import services
from django_chat_ui.protocol import degrade, degrade_parts, plain

pytestmark = pytest.mark.django_db

BASIC = {"parts": ["text"], "streaming": False, "formats": ["plain"]}


@pytest.mark.parametrize(
    "part, expected",
    [
        (
            {
                "type": "text",
                "format": "markdown",
                "text": "**Hola** [mira](https://x)",
            },
            [{"type": "text", "text": "Hola mira"}],
        ),
        (
            {
                "type": "card",
                "title": "Pedido",
                "text": "Sale hoy",
                "url": "https://x/1",
            },
            [{"type": "text", "text": "Pedido\nSale hoy\nhttps://x/1"}],
        ),
        (
            {
                "type": "buttons",
                "buttons": [{"id": "a", "label": "Sí"}, {"id": "b", "label": "No"}],
            },
            [{"type": "text", "text": "Sí / No"}],
        ),
        (
            {"type": "link", "url": "https://x", "title": "X"},
            [{"type": "text", "text": "X\nhttps://x"}],
        ),
        (
            {"type": "location", "lat": 40.4, "lng": -3.7},
            [{"type": "text", "text": "40.4, -3.7"}],
        ),
        (
            {
                "type": "location",
                "lat": 1,
                "lng": 2,
                "name": "Tienda",
                "address": "Gran Vía 1",
            },
            [{"type": "text", "text": "Tienda\nGran Vía 1"}],
        ),
        (
            {"type": "contact", "name": "Ana", "phones": ["+34 600"]},
            [{"type": "text", "text": "Ana\n+34 600"}],
        ),
        (
            {"type": "file", "url": "/f/1", "name": "a.pdf"},
            [{"type": "text", "text": "a.pdf\n/f/1"}],
        ),
        (
            {"type": "system", "text": "Ana joined"},
            [{"type": "text", "text": "Ana joined"}],
        ),
        (
            {"type": "acme.order", "fallback": "Pedido A-1"},
            [{"type": "text", "text": "Pedido A-1"}],
        ),
        ({"type": "acme.nothing"}, [{"type": "acme.nothing"}]),  # never dropped
    ],
)
def test_parts_a_basic_client_can_show(part, expected):
    assert degrade_parts([part], BASIC) == expected


def test_what_a_client_renders_is_left_alone():
    rich = {"parts": ["text", "card", "buttons"], "formats": ["plain", "markdown"]}
    parts = [
        {"type": "text", "format": "markdown", "text": "**x**"},
        {"type": "card", "title": "T"},
    ]
    assert degrade_parts(parts, rich) == parts
    # A card for a client with buttons but no cards: its text, its buttons.
    card = {"type": "card", "title": "T", "buttons": [{"id": "a", "label": "A"}]}
    assert degrade_parts([card], {"parts": ["buttons"]}) == [
        {"type": "text", "text": "T"},
        {"type": "buttons", "buttons": [{"id": "a", "label": "A"}]},
    ]


def test_frames():
    card = {"type": "card", "title": "T"}
    text = [{"type": "text", "text": "T"}]
    assert degrade({"type": "message.delta", "data": {}}, BASIC) is None
    assert degrade(
        {"type": "message.delta", "data": {}}, {**BASIC, "streaming": True}
    ) == {"type": "message.delta", "data": {}}
    assert (
        degrade({"type": "message.created", "data": {"parts": [card]}}, BASIC)["data"][
            "parts"
        ]
        == text
    )
    assert degrade({"type": "message.updated", "data": {"status": "read"}}, BASIC)[
        "data"
    ] == {"status": "read"}
    assert (
        degrade(
            {
                "type": "conversation.updated",
                "data": {"lastMessage": {"parts": [card]}},
            },
            BASIC,
        )["data"]["lastMessage"]["parts"]
        == text
    )
    assert degrade({"type": "conversation.updated", "data": {"unread": 1}}, BASIC)[
        "data"
    ] == {"unread": 1}
    assert (
        degrade({"type": "history", "data": {"messages": [{"parts": [card]}]}}, BASIC)[
            "data"
        ]["messages"][0]["parts"]
        == text
    )
    ready = degrade(
        {
            "type": "ready",
            "data": {"conversations": [{"lastMessage": {"parts": [card]}}]},
        },
        BASIC,
    )
    assert ready["data"]["conversations"][0]["lastMessage"]["parts"] == text
    typing = {"type": "typing", "data": {}}
    assert degrade(typing, BASIC) is typing
    assert degrade(typing, None) is typing
    assert plain("# Title\n- one") == "Title\none"


def test_a_client_gets_what_it_said_it_renders(customer_chat, agent, conversation, seq):
    customer_chat.hello(capabilities=BASIC)
    message = services.start_stream(conversation, agent)
    services.delta(message, "Tu pedido ")
    services.finish(message, [{"type": "card", "title": "A-1029", "text": "Sale hoy"}])

    frames = customer_chat.events(seq)["frames"]
    assert "message.delta" not in [f["type"] for f in frames]
    [final] = [f for f in frames if f["type"] == "message.updated"]
    assert final["data"]["parts"] == [{"type": "text", "text": "A-1029\nSale hoy"}]

    [history, _] = customer_chat.ok(
        "history.fetch", {"conversation": str(conversation.pk)}
    )
    assert history["data"]["messages"][-1]["parts"] == [
        {"type": "text", "text": "A-1029\nSale hoy"}
    ]


def test_finished_streams_carry_their_parts(agent, conversation, seq):
    from django_chat_ui.models import Event

    message = services.start_stream(conversation, agent)
    services.delta(message, "Hola")
    services.finish(message)
    final = Event.objects.filter(type="message.updated").last()
    assert final.data["parts"] == [{"type": "text", "text": "Hola"}]

"""The stream of events: who gets what, resuming, SSE and polling."""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from django.test import RequestFactory
from django.utils import timezone

from django_chat_ui import services, stream
from django_chat_ui.backend import get_backend
from django_chat_ui.models import Event

pytestmark = pytest.mark.django_db


def text(value):
    return [{"type": "text", "text": value}]


def parse(body):
    """The SSE messages of a body: ``(id, frame or None)``."""
    messages = []
    for block in body.strip().split("\n\n"):
        fields = dict(
            line.split(": ", 1)
            for line in block.splitlines()
            if not line.startswith(":")
        )
        frame = json.loads(fields["data"]) if "data" in fields else None
        messages.append((fields.get("id"), frame, fields.get("retry")))
    return messages


def test_a_participant_gets_the_events_of_their_conversations(
    customer_chat, agent, customer, conversation, seq
):
    elsewhere = services.create_conversation([agent])
    services.post(elsewhere, agent, text("Not for Ana"))
    services.post(conversation, agent, text("For Ana"))

    answer = customer_chat.events(seq)

    frames = answer["frames"]
    assert [f["type"] for f in frames] == ["message.created", "conversation.updated"]
    assert frames[0]["data"]["parts"] == text("For Ana")
    # Her unread count, not the agent's.
    assert frames[1]["data"]["unread"] == 1
    assert all(f["seq"] > seq for f in frames)
    # Past every event, hers or not.
    assert answer["seq"] == Event.objects.order_by("id").last().pk


def test_polling_without_after_starts_now(customer_chat, conversation):
    answer = customer_chat.client.get("/chat/events").json()
    assert answer == {"frames": [], "seq": Event.objects.order_by("id").last().pk}


def test_last_event_id_works_as_after(customer_chat, agent, conversation, seq):
    services.post(conversation, agent, text("Hi"))
    response = customer_chat.client.get(
        "/chat/events", headers={"Last-Event-ID": str(seq)}
    )
    assert len(response.json()["frames"]) == 2


def test_events_need_a_participant(client):
    assert client.get("/chat/events").status_code == 403
    assert client.post("/chat/events").status_code == 405


def test_an_event_for_one_participant(
    customer_chat, agent_chat, customer, conversation, seq
):
    services.remove_participant(conversation, customer)
    # She no longer sees the conversation, but learns that she doesn't.
    [removed] = customer_chat.events(seq)["frames"]
    assert removed["type"] == "conversation.removed"
    assert removed["data"] == {"id": str(conversation.pk)}
    [updated] = agent_chat.events(seq)["frames"]
    assert [p["name"] for p in updated["data"]["participants"]] == ["Rodolfo"]


def test_a_missing_event_is_waited_for_while_recent(agent, conversation, seq):
    reader = stream.Reader(get_backend(), agent, seq)
    services.post(conversation, agent, text("1"))
    # The message (seq + 1) is still committing (or was rolled back); the
    # agent's update of the list (seq + 2) is there.
    Event.objects.filter(pk=seq + 1).delete()

    assert reader.read() == []
    assert reader.after == seq

    old = timezone.now() - timedelta(seconds=5)
    Event.objects.filter(pk__gt=seq).update(created=old)
    assert [f["seq"] for f in reader.read()] == [seq + 2]


def test_reader_reads_on(agent, conversation, seq):
    reader = stream.Reader(get_backend(), agent, None)
    assert reader.after == seq
    assert reader.read() == []
    services.typing(conversation, agent, True)
    assert [f["type"] for f in reader.read()] == ["typing"]
    assert reader.read() == []


def sse_request(user):
    request = RequestFactory().get("/chat/events", HTTP_ACCEPT="text/event-stream")
    request.user = user
    request.session = {}
    return request


def test_server_sent_events(customer_user, agent, conversation, seq, settings):
    from django_chat_ui.views import events

    services.post(conversation, agent, text("Hi"))
    request = sse_request(customer_user)
    request.GET = request.GET.copy()
    request.GET["after"] = str(seq)

    response = events(request)

    assert response["Content-Type"] == "text/event-stream"
    assert response["X-Accel-Buffering"] == "no"
    assert "no-cache" in response["Cache-Control"]
    body = b"".join(response.streaming_content).decode()
    messages = parse(body)
    assert messages[0] == (str(seq), None, "1000")
    ids = [int(i) for i, frame, _ in messages[1:]]
    # The message, and her list's update (seq + 2 is the agent's).
    assert ids == [seq + 1, seq + 3]
    assert messages[1][1]["type"] == "message.created"
    assert messages[1][1]["seq"] == seq + 1


def test_the_stream_moves_its_id_past_events_of_others(
    agent, customer, conversation, seq
):
    reader = stream.Reader(get_backend(), customer, seq)
    elsewhere = services.create_conversation([agent])
    services.typing(elsewhere, agent, True)

    assert stream.chunk(reader, reader.read(), seq) == f"id: {reader.after}\n\n"
    services.typing(conversation, agent, True)
    services.typing(elsewhere, agent, False)
    before = reader.after
    text_ = stream.chunk(reader, reader.read(), before)
    assert text_.endswith(f"id: {reader.after}\n\n")
    assert text_.count("data:") == 1


def test_the_stream_ends_after_its_timeout(agent, settings):
    settings.CHAT_UI = {**settings.CHAT_UI, "STREAM_TIMEOUT": 0, "RETRY": 500}
    reader = stream.Reader(get_backend(), agent, None)
    assert list(stream.events(reader)) == [f"retry: 500\nid: {reader.after}\n\n"]


@pytest.mark.django_db(transaction=True)
def test_the_stream_for_asgi(agent, customer, conversation, settings):
    settings.CHAT_UI = {
        **settings.CHAT_UI,
        "STREAM_TIMEOUT": 0.2,
        "POLL_INTERVAL": 0.05,
    }
    reader = stream.Reader(get_backend(), customer, None)
    services.post(conversation, agent, text("Hi"))

    async def collect():
        return [chunk async for chunk in stream.aevents(reader)]

    # In a thread of its own: Playwright's tests leave a loop running here.
    with ThreadPoolExecutor(1) as pool:
        body = "".join(pool.submit(asyncio.run, collect()).result())
    assert [frame["type"] for _, frame, _ in parse(body)[1:]] == [
        "message.created",
        "conversation.updated",
    ]


def test_asgi_requests_get_the_async_stream(customer_user, customer, monkeypatch):
    from django.core.handlers.asgi import ASGIRequest

    from django_chat_ui import views

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/chat/events",
        "headers": [(b"accept", b"text/event-stream")],
        "query_string": b"",
    }
    request = ASGIRequest(scope, None)
    request.user = customer_user
    request.session = {}
    response = views.events(request)
    assert response.is_async is True


def test_a_quiet_stream_says_it_is_alive(agent, settings, monkeypatch):
    settings.CHAT_UI = {**settings.CHAT_UI, "STREAM_TIMEOUT": 0.25, "KEEPALIVE": 0.1}
    reader = stream.Reader(get_backend(), agent, None)
    assert ":\n\n" in list(stream.events(reader))
    quiet = stream.Quiet()
    assert quiet("") == ""
    assert quiet("data") == "data"

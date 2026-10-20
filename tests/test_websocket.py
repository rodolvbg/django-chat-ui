"""The WebSocket transport, with Channels."""

import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.backends.db import SessionStore

pytest.importorskip("channels")

from channels.testing.websocket import WebsocketCommunicator  # noqa: E402

from django_chat_ui import services  # noqa: E402
from django_chat_ui.consumers import (  # noqa: E402
    UNAUTHORIZED,
    ChatConsumer,
    ScopeRequest,
)

pytestmark = pytest.mark.django_db(transaction=True)


def run(coroutine):
    # A loop of its own, in a thread: Playwright's tests leave one here.
    with ThreadPoolExecutor(1) as pool:
        return pool.submit(asyncio.run, coroutine).result()


def communicator(user, session=None):
    socket = WebsocketCommunicator(ChatConsumer.as_asgi(), "/chat/ws")
    socket.scope["user"] = user
    socket.scope["session"] = session if session is not None else SessionStore()
    return socket


HELLO = {"type": "hello", "id": "h1", "data": {"protocol": ["1.0"]}}


def test_hello_then_the_stream(customer_user, customer, agent, conversation, settings):
    settings.CHAT_UI = {**settings.CHAT_UI, "POLL_INTERVAL": 0.02}

    async def chat():
        socket = communicator(customer_user)
        connected, _ = await socket.connect()
        assert connected
        await socket.send_json_to(HELLO)
        ready = await socket.receive_json_from()
        await asyncio.sleep(0.05)
        await asyncio.to_thread(
            services.post, conversation, agent, [{"type": "text", "text": "Hola"}]
        )
        created = await socket.receive_json_from(timeout=2)
        updated = await socket.receive_json_from(timeout=2)
        await socket.send_json_to(
            [
                {
                    "type": "message.send",
                    "id": "s1",
                    "data": {
                        "conversation": str(conversation.pk),
                        "clientId": "c1",
                        "parts": [{"type": "text", "text": "¡Hola!"}],
                    },
                },
                {"type": "acme.nope", "id": "s2", "data": {}},
            ]
        )
        answers = [await socket.receive_json_from(timeout=2) for _ in range(2)]
        await socket.disconnect()
        return ready, created, updated, answers

    ready, created, updated, answers = run(chat())
    assert ready["type"] == "ready"
    assert ready["ref"] == "h1"
    assert ready["data"]["me"]["id"] == str(customer.pk)
    assert created["type"] == "message.created"
    assert created["data"]["parts"] == [{"type": "text", "text": "Hola"}]
    assert updated["data"]["unread"] == 1
    assert [(a["type"], a["ref"]) for a in answers] == [("ack", "s1"), ("error", "s2")]


def test_hello_again_resumes(customer_user, agent, conversation, seq, settings):
    settings.CHAT_UI = {**settings.CHAT_UI, "POLL_INTERVAL": 0.02}
    services.typing(conversation, agent, True)

    async def chat():
        socket = communicator(customer_user)
        await socket.connect()
        await socket.send_json_to(
            {**HELLO, "data": {"protocol": ["1.0"], "resume": {"seq": seq}}}
        )
        ready = await socket.receive_json_from()
        missed = await socket.receive_json_from(timeout=2)
        await socket.send_json_to({**HELLO, "id": "h2"})  # A new stream, from now.
        again = await socket.receive_json_from()
        await socket.disconnect()
        return ready, missed, again

    ready, missed, again = run(chat())
    assert ready["data"]["resumed"] is True
    assert missed["type"] == "typing"
    assert again["data"]["resumed"] is False


def test_the_client_gets_what_it_renders(customer_user, agent, conversation, settings):
    settings.CHAT_UI = {**settings.CHAT_UI, "POLL_INTERVAL": 0.02}
    session = SessionStore()

    async def chat():
        socket = communicator(customer_user, session)
        await socket.connect()
        await socket.send_json_to(
            {
                **HELLO,
                "data": {
                    "protocol": ["1.0"],
                    "capabilities": {"parts": ["text"], "streaming": False},
                },
            }
        )
        await socket.receive_json_from()
        await asyncio.sleep(0.05)
        message = await asyncio.to_thread(services.start_stream, conversation, agent)
        await asyncio.to_thread(services.delta, message, "Hola")
        await asyncio.to_thread(
            services.finish, message, [{"type": "card", "title": "Pedido"}]
        )
        frames = []
        while len(frames) < 4:  # created, her list, updated, the list again
            frames.append(await socket.receive_json_from(timeout=2))
        await socket.disconnect()
        return frames

    frames = run(chat())
    assert "message.delta" not in [f["type"] for f in frames]
    [final] = [f for f in frames if f["type"] == "message.updated"]
    assert final["data"]["parts"] == [{"type": "text", "text": "Pedido"}]
    # Kept in the session, as over HTTP.
    assert SessionStore(session.session_key)["django_chat_ui_client"]["parts"] == [
        "text"
    ]


def test_nobody_is_closed_out():
    async def chat():
        socket = communicator(AnonymousUser())
        connected, code = await socket.connect()
        return connected, code

    assert run(chat()) == (False, UNAUTHORIZED)


def test_a_failing_stream_closes(customer_user, conversation, monkeypatch, caplog):
    from django_chat_ui import stream

    def broken(self):
        raise RuntimeError("database gone")

    monkeypatch.setattr(stream.Reader, "read", broken)

    async def chat():
        socket = communicator(customer_user)
        await socket.connect()
        await socket.send_json_to(HELLO)
        await socket.receive_json_from()
        output = await socket.receive_output(timeout=2)
        await socket.wait()
        return output

    assert run(chat()) == {"type": "websocket.close", "code": 1011}
    assert "the WebSocket's stream failed" in caplog.text


def test_scope_request():
    request = ScopeRequest({"path": "/chat/ws", "headers": [(b"origin", b"https://x")]})
    assert request.user.is_anonymous
    assert request.session is None
    assert request.headers == {"origin": "https://x"}
    assert request.path == "/chat/ws"


def test_the_route():
    from django_chat_ui.routing import websocket_urlpatterns

    [route] = websocket_urlpatterns
    assert route.pattern.match("chat/ws")
    assert route.callback.consumer_class is ChatConsumer


def test_leaving_before_hello(customer_user):
    async def chat():
        socket = communicator(customer_user)
        connected, _ = await socket.connect()
        await socket.disconnect()
        return connected

    assert run(chat()) is True

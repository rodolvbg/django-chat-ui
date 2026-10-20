"""The same chat over a WebSocket: an ASGI server (uvicorn) with Channels,
in real Chromium windows."""

import socket
import threading
import time

import pytest
from django.contrib.auth.models import User
from playwright.sync_api import expect

pytest.importorskip("channels")
uvicorn = pytest.importorskip("uvicorn")

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def asgi_url(settings):
    from channels.auth import AuthMiddlewareStack
    from channels.routing import ProtocolTypeRouter, URLRouter
    from django.contrib.staticfiles.handlers import ASGIStaticFilesHandler
    from django.core.asgi import get_asgi_application

    from django_chat_ui.routing import websocket_urlpatterns

    settings.CHAT_UI = {"BACKEND": "shop.chat.DemoBackend", "POLL_INTERVAL": 0.1}
    application = ProtocolTypeRouter(
        {
            "http": ASGIStaticFilesHandler(get_asgi_application()),
            "websocket": AuthMiddlewareStack(URLRouter(websocket_urlpatterns)),
        }
    )
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            application,
            host="127.0.0.1",
            port=port,
            lifespan="off",
            log_level="warning",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(5)


def test_chatting_over_a_websocket(asgi_url, new_page):
    User.objects.create_user(
        "agent", password="pw", first_name="Rodolfo", is_staff=True
    )
    errors = []
    sockets = []

    visitor = new_page(locale="en-US")
    visitor.on("pageerror", lambda error: errors.append(str(error)))
    visitor.on("websocket", lambda ws: sockets.append(ws.url))
    visitor.goto(f"{asgi_url}/?transport=websocket")
    visitor.locator(".chat-widget-launcher").click()
    widget = visitor.locator("chat-widget chat-thread")
    expect(widget.locator(".chat-message")).to_contain_text(
        ["Hi! I'm the shop's assistant"]
    )
    widget.locator(".chat-input").fill("Do you ship to Hawaii?")
    widget.locator(".chat-input").press("Enter")
    expect(widget.locator(".chat-message").last).to_contain_text("answer you shortly")

    agent = new_page(locale="en-US")
    agent.on("pageerror", lambda error: errors.append(str(error)))
    agent.goto(f"{asgi_url}/admin/login/?next=/inbox/%3Ftransport%3Dwebsocket")
    agent.fill("#id_username", "agent")
    agent.fill("#id_password", "pw")
    agent.click("input[type=submit]")
    agent.locator(".chat-conversation").first.click()
    thread = agent.locator("chat-inbox chat-thread")
    expect(thread.locator(".chat-message")).to_contain_text(["Do you ship to Hawaii?"])
    thread.locator(".chat-input").fill("Yes, in 3-5 days.")
    thread.locator(".chat-input").press("Enter")

    expect(
        widget.locator(".chat-message", has_text="Yes, in 3-5 days.")
    ).to_be_visible()
    expect(widget.locator(".chat-message", has_text="Rodolfo joined")).to_be_visible()
    assert sockets == [f"{asgi_url.replace('http', 'ws')}/chat/ws"]
    assert errors == []

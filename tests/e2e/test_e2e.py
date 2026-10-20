"""A visitor and an agent chatting, in real Chromium windows, against a
real Django server: the widget, the inbox, the stream, in Spanish."""

import re

import pytest
from django.contrib.auth.models import User
from playwright.sync_api import Browser, Page, expect

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def demo(settings):
    settings.CHAT_UI = {
        "BACKEND": "shop.chat.DemoBackend",
        # Short streams: none outlives its test (and its database).
        "STREAM_TIMEOUT": 2,
        "KEEPALIVE": 0.5,
        "POLL_INTERVAL": 0.1,
        "RETRY": 200,
    }


@pytest.fixture
def agent_page(live_server, browser: Browser) -> Page:
    User.objects.create_user(
        "agent", password="pw", first_name="Rodolfo", is_staff=True
    )
    page = browser.new_context(locale="es-ES").new_page()
    page.goto(f"{live_server.url}/admin/login/?next=/inbox/")
    page.fill("#id_username", "agent")
    page.fill("#id_password", "pw")
    page.click("input[type=submit]")
    expect(page.locator("chat-inbox")).to_be_visible()
    return page


@pytest.fixture
def visitor_page(live_server, browser: Browser) -> Page:
    page = browser.new_context(locale="es-ES").new_page()
    page.goto(f"{live_server.url}/")
    return page


def test_a_visitor_and_an_agent(agent_page: Page, visitor_page: Page):
    agent, visitor = agent_page, visitor_page
    errors = []
    for page in (agent, visitor):
        page.on("pageerror", lambda error: errors.append(str(error)))

    # The visitor opens the widget: the assistant greets them.
    launcher = visitor.locator(".chat-widget-launcher")
    expect(launcher).to_have_attribute("aria-label", "Escríbenos")
    launcher.click()
    widget = visitor.locator("chat-widget chat-thread")
    expect(widget.locator(".chat-message")).to_contain_text(["¡Hola! Soy el asistente"])

    # A quick reply: their answer, and the assistant's, streamed.
    widget.get_by_role("button", name="Mi pedido").click()
    expect(widget.locator(".chat-message").last).to_contain_text(
        "Tu pedido A-1029 sale hoy con MRW."
    )

    widget.locator(".chat-input").fill("¿Tenéis la talla M en azul?")
    widget.locator(".chat-input").press("Enter")
    expect(widget.locator(".chat-message").last).to_contain_text(
        "Una persona del equipo te contesta"
    )

    # The agent's inbox got it, unread.
    item = agent.locator(".chat-conversation").first
    expect(item.locator(".chat-conversation-preview")).to_contain_text(
        "Una persona del equipo"
    )
    expect(item.locator(".chat-unread")).to_be_visible()
    item.click()
    thread = agent.locator("chat-inbox chat-thread")
    expect(thread.locator(".chat-message")).to_contain_text(
        ["¿Tenéis la talla M en azul?"]
    )
    expect(item.locator(".chat-unread")).to_have_count(0)

    # They answer: the visitor sees it, and who joined.
    thread.locator(".chat-input").fill("¡Sí! Te la reservo.")
    thread.get_by_role("button", name="Enviar").click()
    expect(
        widget.locator(".chat-message", has_text="¡Sí! Te la reservo.")
    ).to_be_visible()
    expect(
        widget.locator(".chat-message", has_text="Rodolfo se ha unido")
    ).to_be_visible()

    # The visitor's message shows as read by then.
    asked = widget.locator(".chat-message", has_text="¿Tenéis la talla M en azul?")
    expect(asked.locator(".chat-status--read")).to_be_visible()

    # The agent sees the visitor typing.
    widget.locator(".chat-input").press_sequentially("Gra")
    expect(thread.locator(".chat-typing")).to_have_text(re.compile("está escribiendo"))
    assert errors == []


def test_a_photo(agent_page: Page, visitor_page: Page, tmp_path):
    visitor = visitor_page
    visitor.locator(".chat-widget-launcher").click()
    widget = visitor.locator("chat-widget chat-thread")
    expect(widget.locator(".chat-message")).to_have_count(1)

    photo = tmp_path / "talla.png"
    photo.write_bytes(
        bytes.fromhex(
            "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
            "1f15c4890000000d49444154789c6360f8cf000000030101005c2d6e"
            "a20000000049454e44ae426082"
        )
    )
    widget.locator(".chat-file-input").set_input_files(str(photo))
    image = widget.locator(".chat-image")
    expect(image).to_have_attribute("alt", "talla.png")
    expect(image).to_have_js_property("naturalWidth", 1)

    agent_page.locator(".chat-conversation").first.click()
    expect(agent_page.locator("chat-inbox .chat-image")).to_have_js_property(
        "naturalWidth", 1
    )

import json
import re

import pytest
from django.template import Context, Template
from django.test import RequestFactory
from django.utils import translation

pytestmark = pytest.mark.django_db


def render(source, request=None):
    return Template("{% load chat_ui %}" + source).render(Context({"request": request}))


def config(html):
    match = re.search(
        r'<script id="chat-ui-config" type="application/json">(.*?)</script>', html
    )
    return json.loads(match.group(1))


def test_chat_ui_writes_what_a_page_needs():
    html = render("{% chat_ui %}", RequestFactory().get("/"))

    assert '<link rel="stylesheet" href="/static/django_chat_ui/chat.css">' in html
    assert (
        '<script type="module" src="/static/django_chat_ui/boot.js"></script>' in html
    )
    data = config(html)
    assert data["events"] == "/chat/events"
    assert data["commands"] == "/chat/commands"
    assert data["uploads"] == "/chat/uploads"
    assert data["transport"] == "sse"
    assert len(data["csrfToken"]) == 64
    assert data["texts"]["thread"]["send"] == "Send"
    # Nothing inline runs (strict CSP): only a data block, and a module.
    assert "<script>" not in html
    assert "style=" not in html


def test_chat_ui_polling_and_without_a_request():
    data = config(render('{% chat_ui transport="polling" poll=5000 %}'))
    assert data["transport"] == "polling"
    assert data["poll"] == 5000
    assert data["csrfToken"] == ""
    assert config(render('{% chat_ui transport="x" %}'))["transport"] == "sse"


def test_chat_ui_texts_are_translated():
    with translation.override("es"):
        data = config(render("{% chat_ui %}"))
    assert data["texts"]["thread"]["send"] == "Enviar"
    assert data["texts"]["inbox"]["unread"] == "%(count)s sin leer"
    assert data["texts"]["widget"]["open"] == "Escríbenos"

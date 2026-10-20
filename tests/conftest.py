import itertools
import json
import os

import pytest
from django.contrib.auth.models import User

from django_chat_ui import services
from django_chat_ui.backend import get_backend

# pytest-playwright's sync API runs on a greenlet bridge to an asyncio loop,
# which makes Django's async-safety check think the database is used from
# async code. Nothing here is concurrent: the documented escape hatch.
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "1")

ids = itertools.count(1)


class Chat:
    """Speaks the protocol through Django's test client, as one participant."""

    def __init__(self, client):
        self.client = client

    def post(self, frames):
        return self.client.post(
            "/chat/commands", json.dumps(frames), content_type="application/json"
        )

    def __call__(self, type, data=None, **extra):
        frame = {"type": type, "id": f"cmd_{next(ids)}", "data": data or {}, **extra}
        response = self.post(frame)
        assert response.status_code == 200, response.content
        return response.json()

    def ok(self, type, data=None):
        """The answers of a command that must succeed (ending in its ack)."""
        frames = self(type, data)
        assert frames[-1]["type"] in {"ack", "ready"}, frames
        return frames

    def error(self, type, data=None):
        """The error of a command that must fail."""
        [frame] = self(type, data)
        assert frame["type"] == "error", frame
        return frame["data"]

    def hello(self, **data):
        [ready] = self.ok("hello", {"protocol": ["1.0"], **data})
        return ready["data"]

    def events(self, after):
        response = self.client.get("/chat/events", {"after": after})
        assert response.status_code == 200
        return response.json()


@pytest.fixture
def agent_user(db):
    return User.objects.create_user(
        "agent", password="pw", first_name="Rodolfo", is_staff=True
    )


@pytest.fixture
def customer_user(db):
    return User.objects.create_user("ana", password="pw", first_name="Ana")


@pytest.fixture
def agent(agent_user):
    return get_backend().participant_for_user(agent_user)


@pytest.fixture
def customer(customer_user):
    return get_backend().participant_for_user(customer_user)


@pytest.fixture
def agent_chat(client, agent_user, agent):
    client.force_login(agent_user)
    return Chat(client)


@pytest.fixture
def customer_chat(customer_user, customer):
    from django.test import Client

    client = Client()
    client.force_login(customer_user)
    return Chat(client)


CAPABILITIES = {
    "typing": True,
    "receipts": True,
    "history": True,
    "replies": True,
    "buttons": True,
    "edit": True,
    "delete": True,
    "reactions": True,
    "attachments": {"types": ["image", "file"], "maxSize": 1000},
    "composer": {"mode": "free", "maxLength": 50},
}


@pytest.fixture
def conversation(agent, customer):
    return services.create_conversation(
        [agent, customer], channel="web", capabilities=dict(CAPABILITIES)
    )


@pytest.fixture
def seq(db):
    """The last seq now: what comes after it is what a test caused."""
    from django_chat_ui.models import Event

    last = Event.objects.order_by("-id").values_list("id", flat=True).first()
    return last or 0

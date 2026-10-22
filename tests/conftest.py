import itertools
import json
import os

import pytest
from django.contrib.auth.models import User

from django_chat_ui import services
from django_chat_ui.backend import get_backend
from django_chat_ui.matrix import room_id, user_id

# pytest-playwright's sync API runs on a greenlet bridge to an asyncio loop,
# which makes Django's async-safety check think the database is used from
# async code. Nothing here is concurrent: the documented escape hatch.
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "1")

BASE = "/chat/_matrix/client/v3"
txns = itertools.count(1)


class Api:
    """Speaks the Matrix Client-Server API through Django's test client, as
    one participant."""

    def __init__(self, client, participant=None):
        self.client = client
        self.participant = participant

    @property
    def me(self):
        return user_id(self.participant)

    def call(self, method, path, body=None, **params):
        url = path if path.startswith("/chat/") else BASE + path
        if method == "GET":
            return self.client.get(url, params)
        if params:
            from urllib.parse import urlencode

            url = f"{url}?{urlencode(params)}"
        return getattr(self.client, method.lower())(
            url,
            json.dumps(body if body is not None else {}),
            content_type="application/json",
        )

    def ok(self, method, path, body=None, **params):
        response = self.call(method, path, body, **params)
        assert response.status_code == 200, response.content
        return response.json()

    def error(self, method, path, body=None, status=None, **params):
        response = self.call(method, path, body, **params)
        assert response.status_code >= 400, response.content
        if status is not None:
            assert response.status_code == status, response.content
        return response.json()["errcode"]

    def send(self, room, content, type="m.room.message", txn=None):
        txn = txn or f"t{next(txns)}"
        return self.call("PUT", f"/rooms/{room}/send/{type}/{txn}", content)

    def sent(self, room, content, type="m.room.message", txn=None):
        """The event ID of what must be sent."""
        response = self.send(room, content, type, txn)
        assert response.status_code == 200, response.content
        return response.json()["event_id"]

    def refused(self, room, content, type="m.room.message"):
        """The errcode of what must not be sent."""
        response = self.send(room, content, type)
        assert response.status_code >= 400, response.content
        return response.json()["errcode"]

    def sync(self, since=None, **params):
        if since is not None:
            params["since"] = since
        return self.ok("GET", "/sync", **params)


def text(body):
    return {"msgtype": "m.text", "body": body}


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
def agent_api(client, agent_user, agent):
    client.force_login(agent_user)
    return Api(client, agent)


@pytest.fixture
def customer_api(customer_user, customer):
    from django.test import Client

    client = Client()
    client.force_login(customer_user)
    return Api(client, customer)


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
def room(conversation):
    return room_id(conversation)

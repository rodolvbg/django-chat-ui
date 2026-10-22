"""The default backend: who chats, what they see, and its hooks."""

import threading

import pytest
from django.contrib.auth.models import AnonymousUser, User
from django.test import Client, RequestFactory

from django_chat_ui import services
from django_chat_ui.backend import SESSION_KEY, ChatBackend, get_backend
from django_chat_ui.matrix import room_id
from django_chat_ui.models import RoomEvent
from tests.conftest import Api, text

pytestmark = pytest.mark.django_db


def request(user=None, session=None):
    req = RequestFactory().get("/")
    req.user = user or AnonymousUser()
    req.session = session if session is not None else {}
    return req


def test_users_get_a_participant(agent_user, customer_user):
    backend = ChatBackend()
    agent = backend.get_participant(request(agent_user))
    assert (agent.kind, agent.name) == ("agent", "Rodolfo")
    assert backend.get_participant(request(agent_user)) == agent
    assert backend.get_participant(request(customer_user)).kind == "user"


def test_visitors_only_if_allowed():
    assert ChatBackend().get_participant(request()) is None

    class Open(ChatBackend):
        allow_anonymous = True

    session = {}
    visitor = Open().get_participant(request(session=session))
    assert (visitor.kind, visitor.name) == ("contact", "Visitor")
    assert session[SESSION_KEY] == visitor.pk
    assert Open().get_participant(request(session=session)) == visitor
    # A participant of a user can't be taken over through the session.
    user = User.objects.create_user("u")
    session[SESSION_KEY] = ChatBackend().participant_for_user(user).pk
    assert Open().get_participant(request(session=session)).user is None


def test_the_support_team_is_the_active_staff(agent, customer_user):
    User.objects.create_user("gone", is_staff=True, is_active=False)
    assert ChatBackend().support_team("web") == [agent]


def test_get_backend_reads_the_settings(settings):
    assert type(get_backend()) is ChatBackend
    settings.CHAT_UI = {"BACKEND": "shop.chat.DemoBackend"}
    assert type(get_backend()).__name__ == "DemoBackend"


class ThreadBackend(ChatBackend):
    hooks = "thread"
    seen: list = []

    def on_message(self, request, message):
        # Its own connection: it sees what the request committed.
        self.seen.append(RoomEvent.objects.get(pk=message.pk).body)


@pytest.mark.django_db(transaction=True)
def test_hooks_in_a_thread_after_the_commit(settings, monkeypatch):
    settings.CHAT_UI = {
        **settings.CHAT_UI,
        "BACKEND": "tests.test_backend.ThreadBackend",
    }
    started = []
    real = threading.Thread

    def thread(*args, **kwargs):
        started.append(real(*args, **kwargs))
        return started[-1]

    monkeypatch.setattr("django_chat_ui.backend.threading.Thread", thread)
    user = User.objects.create_user("t")
    client = Client()
    client.force_login(user)
    me = ChatBackend().participant_for_user(user)
    conversation = services.create_conversation([me])

    Api(client, me).sent(room_id(conversation), text("Hi"))
    [hook] = started
    hook.join(5)
    assert ThreadBackend.seen == ["Hi"]
    assert hook.daemon is True


def test_a_failing_hook_is_logged(caplog):
    def broken():
        raise ValueError("boom")

    ChatBackend().run_hook_now(broken)
    assert "django-chat-ui: broken failed" in caplog.text


def test_the_default_hooks_do_nothing(rf, agent, conversation):
    message = services.send(conversation, agent, {"msgtype": "m.text", "body": "x"})
    backend = ChatBackend()
    assert backend.on_start(rf.get("/"), conversation, agent) is None
    assert backend.on_message(rf.get("/"), message) is None
    assert backend.on_action(rf.get("/"), agent, message, {"id": "a"}) is None
    assert backend.on_event(rf.get("/"), message) is None
    assert backend.validate_content(conversation, agent, "m.room.message", {}) is None

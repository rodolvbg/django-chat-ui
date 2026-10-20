"""The default backend: who chats, and what they see."""

import pytest
from django.contrib.auth.models import AnonymousUser, User
from django.test import Client, RequestFactory

from django_chat_ui.backend import SESSION_KEY, ChatBackend, get_backend
from django_chat_ui.models import get_participant_model

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
    plain = User.objects.create_user("plain")
    assert backend.get_participant(request(plain)).name == "plain"
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


def test_a_visitor_chats_through_the_session(settings, agent):
    settings.CHAT_UI = {**settings.CHAT_UI, "BACKEND": "tests.test_backend.OpenBackend"}
    client = Client()
    response = client.post(
        "/chat/commands",
        '{"type": "hello", "id": "1", "data": {"protocol": ["1.0"]}}',
        content_type="application/json",
    )
    me = response.json()[0]["data"]["me"]
    assert me["kind"] == "contact"
    assert get_participant_model().objects.get(pk=me["id"]).user is None


class OpenBackend(ChatBackend):
    allow_anonymous = True


class ThreadBackend(ChatBackend):
    hooks = "thread"
    seen: list = []

    def on_message(self, request, message):
        from django_chat_ui.models import Message

        # Its own connection: it sees what the command committed.
        self.seen.append(Message.objects.get(pk=message.pk).parts)


@pytest.mark.django_db(transaction=True)
def test_hooks_in_a_thread_after_the_commit(settings, monkeypatch):
    import threading

    from django_chat_ui import services
    from tests.conftest import Chat

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
    conversation = services.create_conversation(
        [me], capabilities={"composer": {"mode": "free"}}
    )

    Chat(client).ok(
        "message.send",
        {
            "conversation": str(conversation.pk),
            "clientId": "c",
            "parts": [{"type": "text", "text": "Hi"}],
        },
    )
    [hook] = started
    hook.join(5)
    assert ThreadBackend.seen == [[{"type": "text", "text": "Hi"}]]
    assert hook.daemon is True


def test_a_failing_hook_is_logged(caplog):
    def broken():
        raise ValueError("boom")

    ChatBackend().run_hook_now(broken)
    assert "django-chat-ui: broken failed" in caplog.text


def test_before_send_can_refuse(customer_chat, conversation, settings):
    settings.CHAT_UI = {
        **settings.CHAT_UI,
        "BACKEND": "tests.test_backend.QuietBackend",
    }
    [error] = customer_chat(
        "message.send",
        {
            "conversation": str(conversation.pk),
            "clientId": "c",
            "parts": [{"type": "text", "text": "shout"}],
        },
    )
    assert error["data"]["code"] == "forbidden"
    assert conversation.messages.count() == 0


class QuietBackend(ChatBackend):
    def before_send(self, request, conversation, participant, parts):
        from django_chat_ui.protocol import ProtocolError

        raise ProtocolError("forbidden", "Not now.")

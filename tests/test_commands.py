"""The commands of the protocol, through ``POST /chat/commands``."""

import json

import pytest

from django_chat_ui import services
from django_chat_ui.backend import ChatBackend
from django_chat_ui.models import Conversation, Message, Participant

pytestmark = pytest.mark.django_db


def text(value):
    return [{"type": "text", "text": value}]


def types(frames):
    return [frame["type"] for frame in frames]


# hello ---------------------------------------------------------------------


def test_hello_says_who_and_lists_the_conversations(agent_chat, agent, conversation):
    services.post(conversation, None, [{"type": "system", "text": "Started"}])

    ready = agent_chat.hello()

    assert ready["protocol"] == "1.0"
    assert ready["me"] == {"id": str(agent.pk), "kind": "agent", "name": "Rodolfo"}
    assert ready["capabilities"] == {}
    assert ready["resumed"] is False
    [listed] = ready["conversations"]
    assert listed["id"] == str(conversation.pk)
    assert listed["channel"] == "web"
    assert listed["unread"] == 1
    assert listed["lastMessage"]["parts"] == [{"type": "system", "text": "Started"}]
    assert {p["name"] for p in listed["participants"]} == {"Rodolfo", "Ana"}


def test_hello_answers_with_its_ref(agent_chat):
    [ready] = agent_chat("hello", {"protocol": ["1.0"]}, id="cmd_hello")
    assert ready["ref"] == "cmd_hello"


def test_hello_resumes_while_the_events_are_kept(agent_chat, conversation, seq):
    assert agent_chat.hello(resume={"seq": seq})["resumed"] is True
    assert agent_chat.hello(resume={"seq": "x"})["resumed"] is False


def test_hello_without_a_version_in_common_is_fatal(agent_chat):
    error = agent_chat.error("hello", {"protocol": ["2.0"]})
    assert error["code"] == "unsupported"
    assert error["fatal"] is True
    assert agent_chat.error("hello", {"protocol": "1.0"})["code"] == "unsupported"


# Frames ----------------------------------------------------------------------


def test_bad_frames_are_answered_with_errors(agent_chat):
    response = agent_chat.post(["nope", {"type": "typing"}, {"type": "x", "id": True}])
    errors = response.json()
    assert types(errors) == ["error", "error", "error"]
    assert [e["data"]["code"] for e in errors] == ["bad_request"] * 3
    assert all("ref" not in e for e in errors)

    assert (
        agent_chat.error("typing", ["x"])["code"] == "bad_request"
    )  # data not an object
    [error] = agent_chat.post({"type": "typing", "id": "no-data"}).json()
    assert error["data"]["code"] == "not_found"


def test_a_list_of_commands_is_answered_in_order(agent_chat, conversation):
    response = agent_chat.post(
        [
            {
                "type": "conversation.close",
                "id": "a",
                "data": {"conversation": str(conversation.pk)},
            },
            {"type": "acme.unknown", "id": "b", "data": {}},
        ]
    )
    answers = response.json()
    assert [(a["type"], a["ref"]) for a in answers] == [("ack", "a"), ("error", "b")]
    assert answers[1]["data"]["code"] == "unknown_command"


def test_the_body_must_be_json_and_not_too_long(agent_chat):
    response = agent_chat.client.post(
        "/chat/commands", "{", content_type="application/json"
    )
    assert response.status_code == 400
    assert response.json()[0]["data"]["code"] == "bad_request"

    response = agent_chat.post([{"type": "x", "id": n} for n in range(21)])
    assert response.status_code == 400
    assert response.json()[0]["data"]["code"] == "too_large"


def test_commands_need_a_participant(client):
    response = client.post("/chat/commands", "{}", content_type="application/json")
    assert response.status_code == 403
    assert response.json()[0]["data"] == {
        "code": "unauthorized",
        "retry": False,
        "message": "Log in to chat.",
        "fatal": True,
    }
    assert client.get("/chat/commands").status_code == 405


def test_commands_check_the_csrf_token(customer_user):
    from django.test import Client

    client = Client(enforce_csrf_checks=True)
    client.force_login(customer_user)
    response = client.post("/chat/commands", "{}", content_type="application/json")
    assert response.status_code == 403


# conversation.open -----------------------------------------------------------


def test_open_sends_the_conversation_and_its_latest_messages(
    customer_chat, conversation, agent
):
    for n in range(3):
        services.post(conversation, agent, text(f"m{n}"))

    frames = customer_chat.ok(
        "conversation.open", {"conversation": str(conversation.pk), "limit": 2}
    )

    assert types(frames) == ["conversation.created", "history", "ack"]
    created, history, ack = frames
    assert created["data"]["unread"] == 3
    assert [m["parts"][0]["text"] for m in history["data"]["messages"]] == ["m1", "m2"]
    assert history["data"]["more"] is True
    assert history["data"]["before"] == history["data"]["messages"][0]["id"]
    assert ack["data"] == {"conversation": str(conversation.pk)}


def test_open_only_what_one_sees(customer_chat, agent):
    other = services.create_conversation([agent])
    for pk in [str(other.pk), "nope", 5, None]:
        assert (
            customer_chat.error("conversation.open", {"conversation": pk})["code"]
            == "not_found"
        )


def test_the_widget_starts_a_conversation_with_the_support_team(
    customer_chat, customer, agent
):
    frames = customer_chat.ok("conversation.open", {"with": [], "channel": "web"})

    conversation = Conversation.objects.get()
    assert frames[-1]["data"] == {"conversation": str(conversation.pk)}
    assert conversation.state == "pending"
    assert conversation.title == "Ana"
    assert set(conversation.participants.all()) == {customer, agent}
    assert conversation.capabilities["composer"] == {"mode": "free", "maxLength": 4096}
    assert frames[0]["data"]["state"] == "pending"
    assert frames[1]["data"]["messages"] == []


def test_agents_start_conversations_with_anyone(agent_chat, customer):
    frames = agent_chat.ok(
        "conversation.open", {"with": [str(customer.pk)], "channel": "internal"}
    )
    conversation = Conversation.objects.get(pk=frames[-1]["data"]["conversation"])
    assert conversation.state == "open"
    assert conversation.title == ""
    assert conversation.channel == "internal"


def test_others_only_with_the_support_team(customer_chat, agent):
    error = customer_chat.error("conversation.open", {"with": [str(agent.pk)]})
    assert error["code"] == "forbidden"


@pytest.mark.parametrize(
    "data, code",
    [
        ({"with": "p_1"}, "bad_request"),
        ({"with": [1]}, "bad_request"),
        ({"with": ["999"]}, "not_found"),
        ({"with": ["x"]}, "not_found"),
        ({"with": [], "channel": 5}, "bad_request"),
    ],
)
def test_starting_checks_what_it_gets(agent_chat, data, code):
    assert agent_chat.error("conversation.open", data)["code"] == code


def test_starting_with_oneself_is_starting_alone(customer_chat, customer):
    customer_chat.ok("conversation.open", {"with": [str(customer.pk)]})
    assert Conversation.objects.get().state == "pending"


def test_close(customer_chat, conversation):
    assert types(
        customer_chat.ok("conversation.close", {"conversation": str(conversation.pk)})
    ) == ["ack"]


# message.send ----------------------------------------------------------------


def send(chat, conversation, parts, client_id="c_1", **data):
    return chat(
        "message.send",
        {
            "conversation": str(conversation.pk),
            "clientId": client_id,
            "parts": parts,
            **data,
        },
    )


def test_send_posts_the_message_as_the_sender(customer_chat, customer, conversation):
    [ack] = send(
        customer_chat,
        conversation,
        [{"type": "text", "text": "Hola", "format": "markdown", "x": 1}],
        author="p_999",
    )

    assert ack["type"] == "ack"
    message = Message.objects.get()
    assert message.author == customer  # never the one a client claims (11)
    assert message.client_id == "c_1"
    assert message.parts == [{"type": "text", "text": "Hola", "format": "markdown"}]


def test_send_is_idempotent_by_client_id(customer_chat, conversation):
    send(customer_chat, conversation, text("Hola"))
    [ack] = send(customer_chat, conversation, text("Hola"))
    assert ack["type"] == "ack"
    assert Message.objects.count() == 1


def test_send_at_the_same_time_is_still_once(customer_chat, conversation, monkeypatch):
    from django.db import IntegrityError

    def clash(*args, **kwargs):
        raise IntegrityError

    monkeypatch.setattr(services, "post", clash)
    [ack] = send(customer_chat, conversation, text("Hola"))
    assert ack["type"] == "ack"


@pytest.mark.parametrize(
    "parts, code",
    [
        ([], "bad_request"),
        ("hi", "bad_request"),
        ([{"text": "no type"}], "bad_request"),
        ([{"type": "text", "text": "  "}], "bad_request"),
        ([{"type": "text"}], "bad_request"),
        ([{"type": "text", "text": "x" * 51}], "too_large"),
        ([{"type": "buttons", "buttons": []}], "unsupported"),
        ([{"type": "acme.order"}], "bad_request"),
        ([{"type": "image", "url": "https://evil.example/pixel.png"}], "bad_request"),
        ([{"type": "video", "url": "/x"}], "unsupported"),
        ([{"type": "template", "template": "nope"}], "bad_request"),
    ],
)
def test_send_checks_the_parts(customer_chat, conversation, parts, code):
    [error] = send(customer_chat, conversation, parts)
    assert error["data"]["code"] == code


def test_send_needs_a_client_id(customer_chat, conversation):
    [error] = send(customer_chat, conversation, text("Hi"), client_id="")
    assert error["data"]["code"] == "bad_request"


def test_extension_parts_go_with_their_fallback(customer_chat, conversation):
    part = {
        "type": "acme.order",
        "fallback": "Order A-1",
        "ext": {"acme": {"id": "A-1"}},
    }
    send(customer_chat, conversation, [part])
    assert Message.objects.get().parts == [part]


def test_the_backend_can_refuse_parts(customer_chat, conversation, settings):
    settings.CHAT_UI = {
        **settings.CHAT_UI,
        "BACKEND": "tests.test_commands.StrictBackend",
    }
    [error] = send(
        customer_chat, conversation, [{"type": "acme.order", "fallback": "x"}]
    )
    assert error["data"] == {
        "code": "forbidden",
        "retry": False,
        "message": "No orders.",
    }


class StrictBackend(ChatBackend):
    def validate_parts(self, conversation, participant, parts):
        from django_chat_ui.protocol import ProtocolError

        if any(p["type"] == "acme.order" for p in parts):
            raise ProtocolError("forbidden", "No orders.")


def test_send_follows_the_composer(customer_chat, conversation):
    templates = [
        {
            "id": "followup",
            "name": "Seguimiento",
            "preview": "Hola {{1}}, ¿algo más? {{2}}{{3}}",
            "params": ["name", "extra"],
        }
    ]
    services.update_conversation(
        conversation,
        capabilities={
            "composer": {"mode": "templates", "reason": "24 h", "templates": templates}
        },
    )
    [error] = send(customer_chat, conversation, text("Hi"))
    assert error["data"] == {"code": "window_closed", "retry": False, "message": "24 h"}

    template = {
        "type": "template",
        "template": "followup",
        "params": {"name": "Ana", "evil": "x"},
        "fallback": "<b>forged</b>",
    }
    [ack] = send(customer_chat, conversation, [template])
    assert ack["type"] == "ack"
    assert Message.objects.get().parts == [
        {
            "type": "template",
            "template": "followup",
            "params": {"name": "Ana", "extra": ""},
            "fallback": "Hola Ana, ¿algo más? ",
        }
    ]
    send(customer_chat, conversation, [{**template, "params": "Ana"}], client_id="c_2")
    assert Message.objects.last().parts[0]["params"] == {"name": "", "extra": ""}

    for mode, code in [
        ("actions", "unsupported"),
        ("closed", "unsupported"),
        ("acme.x", "unsupported"),
    ]:
        services.update_conversation(
            conversation, capabilities={"composer": {"mode": mode}}
        )
        [error] = send(customer_chat, conversation, text("Hi"), client_id=mode)
        assert error["data"]["code"] == code
        assert error["data"]["message"] == "Nothing can be written here now."

    services.update_conversation(
        conversation, capabilities={"composer": {"mode": "templates"}}
    )
    [error] = send(customer_chat, conversation, text("Hi"), client_id="t")
    assert error["data"]["message"] == "Only templates can be sent now."


def test_nothing_is_sent_to_a_closed_conversation(customer_chat, conversation):
    services.update_conversation(conversation, state="closed")
    [error] = send(customer_chat, conversation, text("Hi"))
    assert error["data"] == {
        "code": "forbidden",
        "retry": False,
        "message": "This conversation is closed.",
    }


def test_replies_need_their_capability(customer_chat, conversation, agent):
    first = services.post(conversation, agent, text("Question"))
    send(customer_chat, conversation, text("Answer"), replyTo=str(first.pk))
    assert Message.objects.get(client_id="c_1").reply_to == first

    [error] = send(
        customer_chat, conversation, text("Answer"), client_id="c_2", replyTo="999"
    )
    assert error["data"]["code"] == "not_found"

    services.update_conversation(conversation, capabilities={"replies": False})
    [error] = send(
        customer_chat,
        conversation,
        text("Answer"),
        client_id="c_3",
        replyTo=str(first.pk),
    )
    assert error["data"]["code"] == "unsupported"


def test_on_message_runs_after_sending(customer_chat, conversation, settings):
    settings.CHAT_UI = {
        **settings.CHAT_UI,
        "BACKEND": "tests.test_commands.EchoBackend",
    }
    send(customer_chat, conversation, text("Hola"))
    assert [m.parts[0]["text"] for m in conversation.messages.all()] == [
        "Hola",
        "Echo: Hola",
    ]


class EchoBackend(ChatBackend):
    def on_message(self, request, message):
        bot = Participant.objects.create(kind="bot", name="Echo")
        services.post(
            message.conversation, bot, text(f"Echo: {message.parts[0]['text']}")
        )


# edit, delete, react ---------------------------------------------------------


def test_edit_own_messages(customer_chat, customer, agent, conversation):
    mine = services.post(conversation, customer, text("Hola"))
    customer_chat.ok("message.edit", {"id": str(mine.pk), "parts": text("Hola!")})
    mine.refresh_from_db()
    assert mine.parts == text("Hola!")
    assert mine.edited is not None

    theirs = services.post(conversation, agent, text("Hi"))
    assert (
        customer_chat.error("message.edit", {"id": str(theirs.pk), "parts": text("x")})[
            "code"
        ]
        == "forbidden"
    )
    assert (
        customer_chat.error("message.edit", {"id": "999", "parts": text("x")})["code"]
        == "not_found"
    )
    assert (
        customer_chat.error("message.edit", {"id": 1, "parts": text("x")})["code"]
        == "not_found"
    )

    services.update_message(mine, deleted=True)
    assert (
        customer_chat.error("message.edit", {"id": str(mine.pk), "parts": text("x")})[
            "code"
        ]
        == "forbidden"
    )


def test_delete_own_messages(customer_chat, customer, conversation):
    mine = services.post(conversation, customer, text("Oops"))
    customer_chat.ok("message.delete", {"id": str(mine.pk)})
    mine.refresh_from_db()
    assert mine.deleted is True
    assert mine.parts == text("")
    assert mine.edited is None


def test_edit_and_delete_need_their_capabilities(customer_chat, customer, conversation):
    services.update_conversation(
        conversation, capabilities={"edit": False, "delete": False}
    )
    mine = services.post(conversation, customer, text("Hola"))
    assert (
        customer_chat.error("message.edit", {"id": str(mine.pk), "parts": text("x")})[
            "code"
        ]
        == "unsupported"
    )
    assert (
        customer_chat.error("message.delete", {"id": str(mine.pk)})["code"]
        == "unsupported"
    )


def test_react_to_any_message(customer_chat, agent_chat, customer, agent, conversation):
    message = services.post(conversation, agent, text("Done"))
    customer_chat.ok(
        "message.react", {"id": str(message.pk), "emoji": "👍", "active": True}
    )
    agent_chat.ok("message.react", {"id": str(message.pk), "emoji": "👍"})
    message.refresh_from_db()
    assert message.reactions == [
        {"emoji": "👍", "by": [str(customer.pk), str(agent.pk)]}
    ]

    customer_chat.ok(
        "message.react", {"id": str(message.pk), "emoji": "👍", "active": False}
    )
    agent_chat.ok(
        "message.react", {"id": str(message.pk), "emoji": "👍", "active": False}
    )
    message.refresh_from_db()
    assert message.reactions == []

    assert (
        customer_chat.error("message.react", {"id": str(message.pk), "emoji": ""})[
            "code"
        ]
        == "bad_request"
    )


# read, typing, action, history ------------------------------------------------


def test_read(customer_chat, customer, agent, conversation, seq):
    first = services.post(conversation, agent, text("1"))
    services.post(conversation, agent, text("2"))
    customer_chat.ok(
        "message.read", {"conversation": str(conversation.pk), "until": str(first.pk)}
    )

    membership = conversation.memberships.get(participant=customer)
    assert membership.unread == 1
    assert membership.last_read == first
    first.refresh_from_db()
    assert first.status == "read"

    assert (
        customer_chat.error(
            "message.read", {"conversation": str(conversation.pk), "until": "999"}
        )["code"]
        == "not_found"
    )


def test_typing(customer_chat, conversation, customer, seq):
    customer_chat.ok("typing", {"conversation": str(conversation.pk), "active": True})
    frames = customer_chat.events(seq)["frames"]
    assert frames[-1]["data"] == {
        "conversation": str(conversation.pk),
        "participant": str(customer.pk),
        "active": True,
    }
    services.update_conversation(conversation, capabilities={"typing": False})
    assert (
        customer_chat.error(
            "typing", {"conversation": str(conversation.pk), "active": True}
        )["code"]
        == "unsupported"
    )


def test_action_writes_the_button_as_the_answer(
    customer_chat, customer, agent, conversation
):
    menu = services.post(
        conversation,
        agent,
        [
            {"type": "text", "text": "Choose"},
            {"type": "buttons", "buttons": [{"id": "yes", "label": "Yes"}]},
            {
                "type": "card",
                "title": "More",
                "buttons": [{"id": "more", "label": "More"}],
            },
        ],
    )
    customer_chat.ok(
        "action",
        {
            "conversation": str(conversation.pk),
            "message": str(menu.pk),
            "button": "more",
        },
    )
    answer = conversation.messages.last()
    assert answer.author == customer
    assert answer.parts == text("More")

    error = customer_chat.error(
        "action",
        {"conversation": str(conversation.pk), "message": str(menu.pk), "button": "no"},
    )
    assert error["code"] == "not_found"
    error = customer_chat.error(
        "action",
        {"conversation": str(conversation.pk), "message": menu.pk, "button": "yes"},
    )
    assert error["code"] == "not_found"

    services.update_conversation(conversation, capabilities={"buttons": False})
    error = customer_chat.error(
        "action",
        {
            "conversation": str(conversation.pk),
            "message": str(menu.pk),
            "button": "yes",
        },
    )
    assert error["code"] == "unsupported"


def test_history_pages_back(customer_chat, agent, conversation):
    messages = [services.post(conversation, agent, text(str(n))) for n in range(5)]
    pk = str(conversation.pk)

    history, ack = customer_chat.ok(
        "history.fetch", {"conversation": pk, "before": str(messages[3].pk), "limit": 2}
    )
    assert history["type"] == "history"
    assert [m["parts"][0]["text"] for m in history["data"]["messages"]] == ["1", "2"]
    assert history["data"]["before"] == str(messages[1].pk)
    assert history["data"]["more"] is True

    history, _ = customer_chat.ok(
        "history.fetch",
        {"conversation": pk, "before": str(messages[1].pk), "limit": "x"},
    )
    assert [m["parts"][0]["text"] for m in history["data"]["messages"]] == ["0"]
    assert history["data"]["more"] is False
    assert history["data"]["before"] is None

    history, _ = customer_chat.ok("history.fetch", {"conversation": pk, "limit": 500})
    assert len(history["data"]["messages"]) == 5

    services.update_conversation(conversation, capabilities={"history": False})
    assert (
        customer_chat.error("history.fetch", {"conversation": pk})["code"]
        == "unsupported"
    )


# Extensions --------------------------------------------------------------------


class OrderBackend(ChatBackend):
    commands = {
        "acme.order.lookup": lambda backend, request, participant, data: {
            "status": f"{data['id']} shipped"
        },
        "message.pin": lambda *args: {},
    }


def test_extension_commands(customer_chat, settings):
    settings.CHAT_UI = {
        **settings.CHAT_UI,
        "BACKEND": "tests.test_commands.OrderBackend",
    }
    [ack] = customer_chat.ok("acme.order.lookup", {"id": "A-1"})
    assert ack["data"] == {"status": "A-1 shipped"}
    # Only namespaced ones: the protocol's names aren't anyone's to take.
    assert customer_chat.error("message.pin")["code"] == "unknown_command"


def test_frames_are_json(customer_chat, conversation):
    response = customer_chat.post(
        {
            "type": "conversation.close",
            "id": "x",
            "data": {"conversation": str(conversation.pk)},
        }
    )
    assert response["Content-Type"] == "application/json"
    assert json.loads(response.content) == [{"type": "ack", "data": {}, "ref": "x"}]

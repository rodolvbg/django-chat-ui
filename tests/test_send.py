"""What clients may send to a room (rules.py), through PUT …/send."""

from unittest import mock

import pytest
from django.db import IntegrityError

from django_chat_ui import content, services
from django_chat_ui.backend import ChatBackend
from django_chat_ui.matrix import ACTION, CARD, HTML, STATUS, SYSTEM, TEMPLATE
from django_chat_ui.models import Media, RoomEvent
from tests.conftest import text

pytestmark = pytest.mark.django_db

UNSUPPORTED = "IO.GITHUB.RODOLVBG.CHAT.UNSUPPORTED"


def event(event_id):
    return RoomEvent.objects.get(pk=event_id[1:])


def test_a_text(customer_api, room):
    sent = event(customer_api.sent(room, text("Hi")))
    assert sent.content == {"msgtype": "m.text", "body": "Hi"}
    assert sent.sender == customer_api.participant
    # What a client adds that isn't Matrix's is left out; its HTML kept.
    rich = {
        "msgtype": "m.text",
        "body": "**a**",
        "format": HTML,
        "formatted_body": "<b>a</b>",
        "m.mentions": {},
        SYSTEM: {"code": "fake"},
    }
    sent = event(customer_api.sent(room, rich))
    assert sent.content == {
        "msgtype": "m.text",
        "body": "**a**",
        "format": HTML,
        "formatted_body": "<b>a</b>",
        "m.mentions": {},
    }
    assert event(customer_api.sent(room, {"msgtype": "m.emote", "body": "waves"}))


def test_the_same_transaction_once(customer_api, room):
    first = customer_api.sent(room, text("Hi"), txn="same")
    assert customer_api.sent(room, text("Hi"), txn="same") == first
    assert RoomEvent.objects.filter(txn_id="same").count() == 1


def test_the_same_transaction_at_the_same_time(customer_api, room, conversation):
    real = services.send

    def racing(*args, **kwargs):
        # Another request with it commits first.
        real(*args, **kwargs)
        raise IntegrityError

    with mock.patch("django_chat_ui.services.send", side_effect=racing):
        response = customer_api.send(room, text("Hi"), txn="race")
    first = conversation.events.get(txn_id="race")
    assert response.json() == {"event_id": first.event_id}


def test_content_must_be_an_object(conversation, customer):
    from django_chat_ui.matrix import MatrixError
    from django_chat_ui.rules import Rules

    with pytest.raises(MatrixError):
        Rules(ChatBackend(), customer, conversation).check("m.room.message", "x")


@pytest.mark.parametrize(
    "message, errcode",
    [
        ("nope", "M_BAD_JSON"),
        ({"body": "x"}, "M_BAD_JSON"),
        ({"msgtype": "m.text", "body": "  "}, "M_BAD_JSON"),
        ({"msgtype": "m.text", "body": "x" * 51}, "M_TOO_LARGE"),
        ({"msgtype": "m.notice", "body": "x"}, UNSUPPORTED),
        ({"msgtype": "m.location", "body": "x", "geo_uri": "geo:1,2"}, UNSUPPORTED),
        ({"msgtype": "m.text", "body": "x", "m.relates_to": "x"}, "M_BAD_JSON"),
        (
            {
                "msgtype": "m.text",
                "body": "x",
                "m.relates_to": {"rel_type": "m.thread"},
            },
            UNSUPPORTED,
        ),
        ({"msgtype": "com.acme.order"}, UNSUPPORTED),
        ({"msgtype": f"{CARD}", "body": "fake"}, UNSUPPORTED),
    ],
)
def test_what_isnt_a_message_to_send(customer_api, room, message, errcode):
    assert customer_api.refused(room, message) == errcode


def test_messages_of_extensions(customer_api, room, settings):
    order = {
        "msgtype": "com.acme.order",
        "body": "Order A-1",
        "com.acme.order": {"id": 1},
    }
    assert event(customer_api.sent(room, order)).content == order

    settings.CHAT_UI = {**settings.CHAT_UI, "BACKEND": "tests.test_send.Strict"}
    assert customer_api.refused(room, order) == "M_FORBIDDEN"


class Strict(ChatBackend):
    event_types = {"com.acme.ping", "m.call.invite"}

    def validate_content(self, conversation, participant, event_type, content):
        from django_chat_ui.matrix import MatrixError

        if event_type == "m.room.message":
            raise MatrixError("M_FORBIDDEN", "No orders.")

    seen: list = []

    def on_event(self, request, event):
        self.seen.append(event.type)


def test_events_of_extensions(customer_api, room, settings):
    assert customer_api.refused(room, {"x": 1}, type="com.acme.ping") == "M_FORBIDDEN"
    settings.CHAT_UI = {**settings.CHAT_UI, "BACKEND": "tests.test_send.Strict"}
    customer_api.sent(room, {"x": 1}, type="com.acme.ping")
    assert Strict.seen == ["com.acme.ping"]
    # Matrix's own types aren't an extension's to allow.
    assert customer_api.refused(room, {}, type="m.call.invite") == "M_FORBIDDEN"


def test_the_composer_decides(customer_api, room, conversation):
    templates = [
        {
            "id": "hi",
            "name": "Hi",
            "preview": "Hi {{1}}, {{2}}{{3}}{{name}}!",
            "params": ["name", "x"],
        }
    ]
    services.update_conversation(
        conversation,
        capabilities={
            "composer": {"mode": "templates", "reason": "24 h.", "templates": templates}
        },
    )
    assert (
        customer_api.refused(room, text("Hi"))
        == "IO.GITHUB.RODOLVBG.CHAT.WINDOW_CLOSED"
    )
    sent = customer_api.sent(
        room,
        {
            "msgtype": TEMPLATE,
            "body": "forged",
            TEMPLATE: {"id": "hi", "params": {"name": "Ana", "y": "z"}},
        },
    )
    assert event(sent).content == {
        "msgtype": TEMPLATE,
        "body": "Hi Ana, Ana!",
        TEMPLATE: {"id": "hi", "params": {"name": "Ana", "x": ""}},
    }
    sent = customer_api.sent(
        room, {"msgtype": TEMPLATE, "body": "", TEMPLATE: {"id": "hi", "params": "x"}}
    )
    assert event(sent).content["body"] == "Hi , !"
    assert (
        customer_api.refused(
            room, {"msgtype": TEMPLATE, "body": "x", TEMPLATE: {"id": "no"}}
        )
        == "M_BAD_JSON"
    )
    assert (
        customer_api.refused(room, {"msgtype": TEMPLATE, "body": "x"}) == "M_BAD_JSON"
    )

    services.update_conversation(
        conversation, capabilities={"composer": {"mode": "actions"}}
    )
    assert customer_api.refused(room, text("Hi")) == UNSUPPORTED
    services.update_conversation(
        conversation, capabilities={"composer": {"mode": "closed", "reason": "Bye."}}
    )
    response = customer_api.send(room, text("Hi"))
    assert response.json() == {"errcode": UNSUPPORTED, "error": "Bye."}

    services.update_conversation(
        conversation, state="closed", capabilities={"composer": {"mode": "free"}}
    )
    assert customer_api.refused(room, text("Hi")) == "M_FORBIDDEN"


def test_buttons(customer_api, room, conversation, agent, settings):
    settings.CHAT_UI = {**settings.CHAT_UI, "BACKEND": "tests.test_send.Recorder"}
    menu = services.send(
        conversation,
        agent,
        content.text("Pick", buttons=[{"id": "a", "label": "Yes"}, {"id": "b"}]),
    )
    answer = customer_api.sent(
        room,
        {
            "msgtype": "m.text",
            "body": "forged",
            ACTION: {"event_id": menu.event_id, "button": "a"},
        },
    )
    assert event(answer).content == {
        "msgtype": "m.text",
        "body": "Yes",
        ACTION: {"event_id": menu.event_id, "button": "a"},
        "m.relates_to": {"m.in_reply_to": {"event_id": menu.event_id}},
    }
    assert Recorder.seen == [("action", menu.pk, "a")]  # Not on_message.
    answer = customer_api.sent(
        room,
        {
            "msgtype": "m.text",
            "body": "",
            ACTION: {"event_id": menu.event_id, "button": "b"},
        },
    )
    assert event(answer).content["body"] == "b"

    no = {
        "msgtype": "m.text",
        "body": "x",
        ACTION: {"event_id": menu.event_id, "button": "z"},
    }
    assert customer_api.refused(room, no) == "M_NOT_FOUND"
    gone = {
        "msgtype": "m.text",
        "body": "x",
        ACTION: {"event_id": "$999", "button": "a"},
    }
    assert customer_api.refused(room, gone) == "M_NOT_FOUND"
    # In a bot's menu (actions), buttons only.
    services.update_conversation(
        conversation, capabilities={"composer": {"mode": "actions"}}
    )
    customer_api.sent(
        room,
        {
            "msgtype": "m.text",
            "body": "x",
            ACTION: {"event_id": menu.event_id, "button": "a"},
        },
    )
    services.update_conversation(
        conversation, capabilities={"composer": {"mode": "closed"}}
    )
    assert customer_api.refused(room, no) == UNSUPPORTED
    services.update_conversation(conversation, capabilities={"buttons": False})
    assert customer_api.refused(room, no) == UNSUPPORTED


class Recorder(ChatBackend):
    seen: list = []

    def on_action(self, request, participant, message, button):
        self.seen.append(("action", message.pk, button["id"]))

    def on_message(self, request, message):
        self.seen.append(("message", message.body))


def test_replies(customer_api, room, conversation, agent):
    first = services.send(conversation, agent, content.text("Hi"))
    reply = {
        "msgtype": "m.text",
        "body": "Hello",
        "m.relates_to": {"m.in_reply_to": {"event_id": first.event_id}},
    }
    sent = event(customer_api.sent(room, reply))
    assert (sent.relates_to, sent.rel_type) == (first, "m.in_reply_to")
    reply["m.relates_to"]["m.in_reply_to"]["event_id"] = "$999"
    assert customer_api.refused(room, reply) == "M_NOT_FOUND"
    services.update_conversation(conversation, capabilities={"replies": False})
    assert customer_api.refused(room, reply) == UNSUPPORTED


def test_edits(customer_api, room, conversation, agent, settings):
    settings.CHAT_UI = {**settings.CHAT_UI, "BACKEND": "tests.test_send.Recorder"}
    Recorder.seen = []
    original = customer_api.sent(room, text("Hi"))

    def edit(of, new):
        return {
            "msgtype": "m.text",
            "body": "* x",
            "m.new_content": new,
            "m.relates_to": {"rel_type": "m.replace", "event_id": of},
        }

    sent = event(customer_api.sent(room, edit(original, text("Hello"))))
    assert sent.content["m.new_content"] == text("Hello")
    assert sent.content["body"] == "* Hello"
    assert Recorder.seen == [("message", "Hi")]  # The edit isn't a new message.

    theirs = services.send(conversation, agent, content.text("Hi"))
    assert customer_api.refused(room, edit(theirs.event_id, text("x"))) == "M_FORBIDDEN"
    assert customer_api.refused(room, edit(original, "x")) == "M_BAD_JSON"
    assert (
        customer_api.refused(room, edit(original, {**text("x"), "m.relates_to": {}}))
        == "M_BAD_JSON"
    )
    services.redact(event(original))
    assert customer_api.refused(room, edit(original, text("x"))) == "M_FORBIDDEN"
    services.update_conversation(conversation, capabilities={"edit": False})
    assert customer_api.refused(room, edit(original, text("x"))) == UNSUPPORTED


def reaction(of, key="👍"):
    return {"m.relates_to": {"rel_type": "m.annotation", "event_id": of, "key": key}}


def test_reactions(customer_api, room, conversation, agent):
    message = services.send(conversation, agent, content.text("Hi"))
    sent = customer_api.sent(room, reaction(message.event_id), type="m.reaction")
    assert services.reactions(message) == {"👍": [customer_api.participant]}
    assert customer_api.refused(room, reaction(message.event_id), "m.reaction") == (
        "M_DUPLICATE_ANNOTATION"
    )
    assert customer_api.refused(room, reaction(sent), "m.reaction") == "M_FORBIDDEN"
    assert (
        customer_api.refused(room, reaction(message.event_id, "x" * 17), "m.reaction")
        == "M_BAD_JSON"
    )
    assert (
        customer_api.refused(room, {"m.relates_to": {}}, "m.reaction") == "M_BAD_JSON"
    )

    services.update_conversation(
        conversation, capabilities={"reactions": {"emojis": ["✅"]}}
    )
    assert (
        customer_api.refused(room, reaction(message.event_id, "🎉"), "m.reaction")
        == UNSUPPORTED
    )
    customer_api.sent(room, reaction(message.event_id, "✅"), type="m.reaction")
    services.update_conversation(conversation, capabilities={"reactions": False})
    assert (
        customer_api.refused(room, reaction(message.event_id, "✅"), "m.reaction")
        == UNSUPPORTED
    )


def upload(api, name="a.png", data=b"x"):
    response = api.client.post(
        f"/chat/_matrix/media/v3/upload?filename={name}", data, content_type="image/png"
    )
    assert response.status_code == 200, response.content
    return response.json()["content_uri"]


def test_files(customer_api, room, conversation, agent_api):
    uri = upload(customer_api)
    sent = event(
        customer_api.sent(
            room,
            {
                "msgtype": "m.image",
                "body": "",
                "url": uri,
                "info": {"w": 2, "h": True, "size": 999},
            },
        )
    )
    assert sent.content == {
        "msgtype": "m.image",
        "body": "a.png",
        "url": uri,
        "info": {"mimetype": "image/png", "size": 1, "w": 2},
    }
    assert Media.objects.get().conversation == conversation

    document = upload(customer_api, "a.pdf")
    sent = event(
        customer_api.sent(
            room, {"msgtype": "m.file", "body": "Invoice", "url": document}
        )
    )
    assert sent.content["filename"] == "a.pdf"
    assert sent.content["body"] == "Invoice"

    # A photo as a file is fine; a file as a photo, or a type it doesn't take, isn't.
    photo = upload(customer_api, "b.png")
    customer_api.sent(room, {"msgtype": "m.file", "body": "b", "url": photo})
    assert (
        customer_api.refused(
            room,
            {"msgtype": "m.image", "body": "x", "url": upload(customer_api, "c.pdf")},
        )
        == UNSUPPORTED
    )
    assert (
        customer_api.refused(
            room,
            {"msgtype": "m.audio", "body": "x", "url": upload(customer_api, "d.ogg")},
        )
        == UNSUPPORTED
    )
    # Only what they uploaded, once, here.
    assert (
        customer_api.refused(
            room, {"msgtype": "m.image", "body": "x", "url": upload(agent_api)}
        )
        == "M_BAD_JSON"
    )
    assert (
        customer_api.refused(
            room, {"msgtype": "m.image", "body": "x", "url": "https://x/y.png"}
        )
        == "M_BAD_JSON"
    )
    other = services.create_conversation(
        [customer_api.participant], capabilities={"attachments": {"types": ["image"]}}
    )
    from django_chat_ui.matrix import room_id

    assert (
        customer_api.refused(
            room_id(other), {"msgtype": "m.image", "body": "x", "url": uri}
        )
        == "M_BAD_JSON"
    )


def test_files_too_big_and_voice(customer_api, room, conversation, settings):
    services.update_conversation(
        conversation, capabilities={"attachments": {"types": ["audio"], "maxSize": 2}}
    )
    voice = upload(customer_api, "v.ogg", b"ab")
    sent = event(
        customer_api.sent(
            room,
            {
                "msgtype": "m.audio",
                "body": "v",
                "url": voice,
                "org.matrix.msc3245.voice": {},
                "info": "x",
            },
        )
    )
    assert sent.content["org.matrix.msc3245.voice"] == {}
    big = upload(customer_api, "w.ogg", b"abc")
    assert (
        customer_api.refused(room, {"msgtype": "m.audio", "body": "w", "url": big})
        == "M_TOO_LARGE"
    )
    services.update_conversation(conversation, capabilities={"attachments": True})
    assert (
        customer_api.refused(room, {"msgtype": "m.audio", "body": "w", "url": big})
        == UNSUPPORTED
    )


def test_before_send_can_refuse(customer_api, room, settings):
    settings.CHAT_UI = {**settings.CHAT_UI, "BACKEND": "tests.test_send.Quiet"}
    assert customer_api.refused(room, text("shout")) == "M_FORBIDDEN"
    assert not RoomEvent.objects.filter(type="m.room.message").exists()


class Quiet(ChatBackend):
    def before_send(self, request, conversation, participant, event_type, content):
        from django_chat_ui.matrix import MatrixError

        raise MatrixError("M_FORBIDDEN", "Not now.")


def test_redactions(customer_api, room, conversation, agent):
    mine = customer_api.sent(room, text("Hi"))
    path = f"/rooms/{room}/redact/{mine}/r1"
    redaction = customer_api.ok("PUT", path, {"reason": "typo"})["event_id"]
    assert event(redaction).content == {"redacts": mine, "reason": "typo"}
    assert customer_api.ok("PUT", path)["event_id"] == redaction  # Same txn.
    again = customer_api.ok("PUT", f"/rooms/{room}/redact/{mine}/r2", {"reason": 1})
    assert again["event_id"] == redaction  # Redacted already.

    message = services.send(conversation, agent, content.text("Hi"))
    my_reaction = customer_api.sent(room, reaction(message.event_id), type="m.reaction")
    customer_api.ok("PUT", f"/rooms/{room}/redact/{my_reaction}/r3")
    assert services.reactions(message) == {}

    assert (
        customer_api.error("PUT", f"/rooms/{room}/redact/{message.event_id}/r4")
        == "M_FORBIDDEN"
    )
    state = conversation.events.filter(
        type="m.room.member", sender=customer_api.participant
    ).get()
    assert (
        customer_api.error("PUT", f"/rooms/{room}/redact/{state.event_id}/r5")
        == "M_FORBIDDEN"
    )
    assert (
        customer_api.error("PUT", f"/rooms/{room}/redact/$999/r6", status=404)
        == "M_NOT_FOUND"
    )
    services.update_conversation(conversation, capabilities={"delete": False})
    other = customer_api.sent(room, text("Bye"))
    assert customer_api.error("PUT", f"/rooms/{room}/redact/{other}/r7") == UNSUPPORTED


def test_redacting_events_of_extensions(customer_api, room, conversation, settings):
    services.update_conversation(conversation, capabilities={"delete": False})
    ping = services.send(
        conversation, customer_api.participant, {"x": 1}, type="com.acme.ping"
    )
    other = services.send(
        conversation, customer_api.participant, {"x": 1}, type="com.acme.other"
    )
    settings.CHAT_UI = {**settings.CHAT_UI, "BACKEND": "tests.test_send.Strict"}
    customer_api.ok("PUT", f"/rooms/{room}/redact/{ping.event_id}/r1")
    assert (
        customer_api.error("PUT", f"/rooms/{room}/redact/{other.event_id}/r2")
        == "M_FORBIDDEN"
    )


def test_a_status_comes_with_the_message(customer_api, room, conversation, agent):
    message = services.send(conversation, agent, content.text("Hi"))
    services.status(message, "failed", {"errcode": "X"})
    page = customer_api.ok("GET", f"/rooms/{room}/messages", limit="1")
    assert page["chunk"][0]["unsigned"][STATUS]["status"] == "failed"

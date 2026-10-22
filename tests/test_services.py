"""The API of integrations: each change, its room events and its entries."""

import pytest

from django_chat_ui import content, services
from django_chat_ui.matrix import (
    CAPABILITIES,
    CONVERSATION,
    DELIVERED,
    PARTICIPANT,
    STATUS,
    STREAM,
)
from django_chat_ui.models import (
    Media,
    Membership,
    Receipt,
    RoomEvent,
    RoomState,
    StreamEntry,
    Typing,
    get_participant_model,
)

pytestmark = pytest.mark.django_db


def state(conversation, type, key=""):
    return RoomState.objects.get(
        conversation=conversation, type=type, state_key=key
    ).event


def test_a_new_room_and_its_state(agent, customer):
    conversation = services.create_conversation(
        [agent, customer, agent],
        channel="whatsapp",
        title="Ana",
        ext={"com.acme": {"id": 1}},
        meta={"crm": 9},
        capabilities={"typing": True},
    )
    types = list(conversation.events.values_list("type", flat=True))
    assert types == [
        "m.room.create",
        "m.room.member",
        "m.room.member",
        "m.room.power_levels",
        "m.room.join_rules",
        "m.room.history_visibility",
        "m.room.name",
        CONVERSATION,
        CAPABILITIES,
    ]
    assert state(conversation, "m.room.name").content == {"name": "Ana"}
    assert state(conversation, CONVERSATION).content == {
        "channel": "whatsapp",
        "state": "open",
        "ext": {"com.acme": {"id": 1}},
    }
    member = state(conversation, "m.room.member", f"@p{customer.pk}:localhost")
    assert member.content == {
        "membership": "join",
        "displayname": "Ana",
        PARTICIPANT: {"kind": "user"},
    }
    assert member.sender == customer
    assert list(conversation.participants) == [agent, customer]
    joins = StreamEntry.objects.filter(kind="join")
    assert {e.recipient for e in joins} == {agent, customer}


def test_a_participant_without_a_name(conversation):
    nameless = get_participant_model().objects.create()
    services.add_participant(conversation, nameless)
    member = state(conversation, "m.room.member", f"@p{nameless.pk}:localhost")
    assert member.content == {"membership": "join", PARTICIPANT: {"kind": "user"}}
    assert str(nameless) == f"user {nameless.pk}"


def test_participants_join_and_leave(conversation, agent, customer):
    bot = get_participant_model().objects.create(kind="bot", name="Bot", handle="b")
    services.add_participant(conversation, bot)
    services.add_participant(conversation, bot)  # Already in: nothing.
    assert conversation.participants.count() == 3
    assert StreamEntry.objects.filter(kind="join", recipient=bot).count() == 1
    joined = state(conversation, "m.room.member", f"@p{bot.pk}:localhost")
    assert joined.content[PARTICIPANT] == {"kind": "bot", "handle": "b"}

    services.typing(conversation, bot, True)
    services.remove_participant(conversation, bot)
    services.remove_participant(conversation, bot)  # Gone already.
    left = state(conversation, "m.room.member", f"@p{bot.pk}:localhost")
    assert left.content["membership"] == "leave"
    entry = StreamEntry.objects.get(kind="leave")
    assert (entry.recipient, entry.event) == (bot, left)
    assert not Typing.objects.filter(participant=bot).exists()


def test_update_conversation(conversation):
    services.update_conversation(conversation, title="New", state="closed")
    services.update_conversation(conversation, capabilities={"typing": False})
    services.update_conversation(conversation, meta={"secret": 1})
    assert state(conversation, "m.room.name").content == {"name": "New"}
    assert state(conversation, CONVERSATION).content["state"] == "closed"
    caps = state(conversation, CAPABILITIES).content
    assert caps["typing"] is False and caps["reactions"] is True
    # meta: the server's only.
    assert conversation.meta == {"secret": 1}
    assert "secret" not in str(conversation.events.values_list("content", flat=True))
    with pytest.raises(TypeError):
        services.update_conversation(conversation, channel="sms")


def test_send_counts_unread_and_stops_typing(conversation, agent, customer):
    services.typing(conversation, agent, True)
    message = services.send(conversation, agent, content.text("Hi"))
    assert message.body == "Hi"
    assert str(message) == "Hi"
    assert message.event_id == f"${message.pk}"
    unread = dict(Membership.objects.values_list("participant", "unread"))
    assert unread == {agent.pk: 0, customer.pk: 1}
    assert StreamEntry.objects.filter(kind="unread", recipient=customer).exists()
    assert not Typing.objects.exists()
    typing = StreamEntry.objects.filter(type="m.typing").last()
    assert typing.data == {"user_ids": []}
    # A system notice: the server's.
    notice = services.system(conversation, "Ana joined", code="joined")
    assert notice.sender is None
    assert list(conversation.messages) == [message, notice]


def test_the_files_a_message_shows_become_the_conversations(conversation, agent):
    media = Media.objects.create(uploader=agent, name="a.png", mime="image/png", size=1)
    thumb = Media.objects.create(uploader=agent, name="t.png", mime="image/png", size=1)
    services.send(
        conversation,
        agent,
        {
            "msgtype": "m.image",
            "body": "a",
            "url": f"mxc://localhost/{media.media_id}",
            "info": {"thumbnail_url": f"mxc://localhost/{thumb.media_id}"},
        },
    )
    assert set(Media.objects.values_list("conversation", flat=True)) == {
        conversation.pk
    }
    assert str(media) == "a.png"


def test_relations(conversation, agent, customer):
    message = services.send(conversation, agent, content.text("Hi"))
    reply = services.send(
        conversation,
        customer,
        {
            **content.text("Hello"),
            "m.relates_to": {"m.in_reply_to": {"event_id": message.event_id}},
        },
    )
    assert (reply.relates_to, reply.rel_type) == (message, "m.in_reply_to")
    unknown = services.send(
        conversation,
        customer,
        {**content.text("?"), "m.relates_to": {"event_id": "$999"}},
    )
    assert (unknown.relates_to, unknown.rel_type) == (None, "")
    nothing = services.send(
        conversation,
        customer,
        {**content.text("?"), "m.relates_to": {"m.in_reply_to": {}}},
    )
    assert (nothing.relates_to, nothing.rel_type) == (None, "")

    edit = services.edit(message, content.text("Hi!"))
    assert edit.sender == agent
    assert edit.content["m.new_content"] == content.text("Hi!")
    assert edit.content["body"] == "* Hi!"
    assert edit.rel_type == "m.replace"
    # An edit isn't a new message to read.
    assert Membership.objects.get(participant=customer).unread == 1


def test_reactions(conversation, agent, customer):
    message = services.send(conversation, agent, content.text("Hi"))
    services.react(message, customer, "👍")
    services.react(message, agent, "👍")
    services.react(message, agent, "🎉")
    assert services.reactions(message) == {"👍": [customer, agent], "🎉": [agent]}
    services.unreact(message, agent, "👍")
    assert services.reactions(message) == {"👍": [customer], "🎉": [agent]}
    assert str(RoomEvent.objects.filter(type="m.reaction").first()) == (
        f"m.reaction {RoomEvent.objects.filter(type='m.reaction').first().pk}"
    )


def test_redact(conversation, agent):
    message = services.send(conversation, agent, content.text("Hi"))
    redaction = services.redact(message)
    message.refresh_from_db()
    assert message.content == {}
    assert message.redacted_by == redaction
    assert redaction.sender == agent
    assert redaction.content == {"redacts": message.event_id}


def test_receipts_and_unread(conversation, agent, customer):
    first = services.send(conversation, agent, content.text("1"))
    services.send(conversation, agent, content.text("2"))
    services.read(conversation, customer, first)
    membership = Membership.objects.get(participant=customer)
    assert (membership.unread, membership.last_read) == (1, first)
    receipt = StreamEntry.objects.filter(type="m.receipt").last()
    assert list(receipt.data) == [first.event_id]
    assert f"@p{customer.pk}:localhost" in receipt.data[first.event_id]["m.read"]

    # Private: their count, nothing for the others.
    entries = StreamEntry.objects.count()
    services.read(conversation, customer, conversation.messages.last(), public=False)
    assert Membership.objects.get(participant=customer).unread == 0
    assert StreamEntry.objects.count() == entries + 1  # Only their unread.
    assert Receipt.objects.get(participant=customer).event == first

    services.delivered(first, customer)
    assert Receipt.objects.filter(type=DELIVERED).get().event == first


def test_status(conversation, agent):
    message = services.send(conversation, agent, content.text("Hi"))
    services.status(message, "failed", {"errcode": "X", "error": "Blocked"})
    message.refresh_from_db()
    assert message.unsigned[STATUS] == {
        "status": "failed",
        "error": {"errcode": "X", "error": "Blocked"},
    }
    entry = StreamEntry.objects.filter(type=STATUS).get()
    assert entry.data["event_id"] == message.event_id
    services.status(message, "sent")
    assert StreamEntry.objects.filter(type=STATUS).last().data == {
        "event_id": message.event_id,
        "status": "sent",
    }


def test_typing_expires(conversation, agent):
    services.typing(conversation, agent, True, timeout=0)
    assert StreamEntry.objects.filter(type="m.typing").last().data == {"user_ids": []}
    services.typing(conversation, agent, True)
    assert StreamEntry.objects.filter(type="m.typing").last().data == {
        "user_ids": [f"@p{agent.pk}:localhost"]
    }
    services.typing(conversation, agent, False)
    assert not Typing.objects.exists()


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def streamed(conversation):
    return list(StreamEntry.objects.filter(type=STREAM).values_list("data", flat=True))


def test_stream_text(conversation, agent):
    clock = Clock()

    def chunks():
        yield "Your "
        clock.now = 1
        yield "order "
        clock.now = 2
        yield ""  # Time passed, nothing new to show.
        yield "ships."

    message = services.stream_text(
        conversation, agent, chunks(), clock=clock, buttons=[{"id": "a", "label": "OK"}]
    )
    [shown] = streamed(conversation)
    assert shown["body"] == "Your order "
    assert shown["markdown"] is True
    assert shown["sender"] == f"@p{agent.pk}:localhost"
    assert message.content[STREAM] == {"id": shown["id"]}
    assert message.content["formatted_body"].startswith("<p>Your order ships.</p>")
    assert message.content["io.github.rodolvbg.chat.buttons"]["buttons"]
    # The author was typing meanwhile; their message stopped it.
    typing = StreamEntry.objects.filter(type="m.typing")
    assert [e.data["user_ids"] for e in typing] == [[f"@p{agent.pk}:localhost"], []]


def test_stream_text_by_size_and_plain(conversation, agent):
    message = services.stream_text(
        conversation, agent, iter(["ab", "cd", "e"]), markdown=False, size=4, every=99
    )
    assert [d["body"] for d in streamed(conversation)] == ["abcd"]
    assert "markdown" not in streamed(conversation)[0]
    assert message.content == {
        "msgtype": "m.text",
        "body": "abcde",
        STREAM: message.content[STREAM],
    }


def test_stream_text_that_fails_sends_what_came(conversation, agent):
    def chunks():
        yield "Half"
        raise RuntimeError("cut")

    with pytest.raises(RuntimeError):
        services.stream_text(conversation, agent, chunks(), every=99)
    assert conversation.messages.get().content["body"] == "Half"


def test_stream_text_with_nothing(conversation, agent):
    assert services.stream_text(conversation, agent, iter([])) is None
    [done] = streamed(conversation)
    assert done["done"] is True
    assert not conversation.messages.exists()
    assert not Typing.objects.exists()

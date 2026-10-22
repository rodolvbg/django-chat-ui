"""GET /sync and GET /rooms/{roomId}/messages."""

import asyncio
import json
from datetime import timedelta

import pytest
from django.utils import timezone

from django_chat_ui import content, services, sync
from django_chat_ui.backend import get_backend
from django_chat_ui.matrix import CAPABILITIES, STATUS, STREAM, room_id
from django_chat_ui.models import RoomEvent, StreamEntry, SyncFilter
from tests.conftest import text

pytestmark = pytest.mark.django_db


def timeline(response, room):
    return response["rooms"]["join"][room]["timeline"]["events"]


def ephemeral(response, room):
    return response["rooms"]["join"][room]["ephemeral"]["events"]


def test_a_first_sync_has_every_room(customer_api, conversation, room, agent):
    services.send(conversation, agent, content.text("Hi"))
    response = customer_api.sync()
    assert response["next_batch"] == f"s{StreamEntry.objects.last().pk}"
    data = response["rooms"]["join"][room]
    types = [e["type"] for e in data["timeline"]["events"]]
    assert types[0] == "m.room.create" and types[-1] == "m.room.message"
    assert data["timeline"]["limited"] is False
    assert data["state"]["events"] == []  # All in the timeline.
    assert data["unread_notifications"] == {
        "notification_count": 1,
        "highlight_count": 0,
    }
    assert data["summary"]["m.joined_member_count"] == 2
    assert data["summary"]["m.heroes"] == [f"@p{agent.pk}:localhost"]
    assert [e["type"] for e in data["ephemeral"]["events"]] == ["m.receipt", "m.typing"]
    for key in ("account_data", "presence", "to_device", "device_lists"):
        assert key in response


def test_a_first_sync_has_the_receipts(
    customer_api, conversation, room, agent, customer
):
    message = services.send(conversation, agent, content.text("Hi"))
    services.read(conversation, customer, message)
    services.delivered(message, customer)
    [receipts, _] = customer_api.sync()["rooms"]["join"][room]["ephemeral"]["events"]
    users = receipts["content"][message.event_id]
    assert set(users) == {"m.read", "io.github.rodolvbg.chat.delivered"}
    assert list(users["m.read"]) == [f"@p{customer.pk}:localhost"]


def test_rooms_that_arent_theirs_any_more(customer_api, conversation, agent, customer):
    since = customer_api.sync()["next_batch"]
    other = services.create_conversation([agent])
    services.entry("unread", conversation=other, recipient=customer)
    assert customer_api.sync(since)["rooms"]["join"] == {}
    # Joined and left at once: only the leaving.
    since = customer_api.sync()["next_batch"]
    services.add_participant(other, customer)
    services.remove_participant(other, customer)
    response = customer_api.sync(since)
    assert response["rooms"]["join"] == {}
    assert list(response["rooms"]["leave"]) == [room_id(other)]


def test_a_first_sync_starts_where_things_settled(
    customer_api, conversation, room, agent
):
    StreamEntry.objects.update(created=timezone.now() - timedelta(seconds=5))
    services.send(conversation, agent, content.text("Just now"))
    response = customer_api.sync()
    assert response["next_batch"] == f"s{StreamEntry.objects.last().pk}"
    assert timeline(response, room)[-1]["content"]["body"] == "Just now"
    assert sync.settled() == StreamEntry.objects.last().pk
    StreamEntry.objects.all().delete()
    assert sync.settled() == 0


def test_its_timeline_limited(customer_api, conversation, room, agent):
    for n in range(5):
        services.send(conversation, agent, content.text(str(n)))
    response = customer_api.sync(
        filter=json.dumps({"room": {"timeline": {"limit": 2}}})
    )
    data = response["rooms"]["join"][room]
    assert [e["content"]["body"] for e in data["timeline"]["events"]] == ["3", "4"]
    assert data["timeline"]["limited"] is True
    first = data["timeline"]["events"][0]["event_id"]
    assert data["timeline"]["prev_batch"] == f"t{first[1:]}"
    # The state before them.
    assert CAPABILITIES in [e["type"] for e in data["state"]["events"]]


def test_filters(agent, customer_api):
    assert sync.filter_limit(agent, None) == sync.DEFAULT_LIMIT
    assert sync.filter_limit(agent, '{"room": {"timeline": {"limit": 5}}}') == 5
    assert sync.filter_limit(agent, '{"room": {"timeline": {"limit": 500}}}') == 100
    assert sync.filter_limit(agent, '{"room": {"timeline": {"limit": true}}}') == 20
    assert sync.filter_limit(agent, "{nope") == sync.DEFAULT_LIMIT
    assert sync.filter_limit(agent, '{"room": 1}') == sync.DEFAULT_LIMIT
    mine = SyncFilter.objects.create(
        participant=agent, definition={"room": {"timeline": {"limit": 3}}}
    )
    assert sync.filter_limit(agent, str(mine.pk)) == 3
    assert sync.filter_limit(customer_api.participant, str(mine.pk)) == 20
    assert sync.filter_limit(agent, "x") == 20
    assert sync.position("s12") == 12
    assert sync.position("12") is None
    assert sync.position(None) is None


def test_then_what_changed(
    customer_api, agent_api, conversation, room, agent, customer
):
    since = customer_api.sync()["next_batch"]
    assert customer_api.sync(since)["rooms"]["join"] == {}  # Nothing yet.

    event = agent_api.sent(room, text("Hi"))
    services.typing(conversation, agent, True)
    services.typing(conversation, agent, False)
    services.read(conversation, agent, RoomEvent.objects.get(pk=event[1:]))
    services.read(conversation, customer, RoomEvent.objects.get(pk=event[1:]))
    services.ephemeral(conversation, "com.acme.progress", {"done": 50})
    services.status(RoomEvent.objects.get(pk=event[1:]), "failed")

    response = customer_api.sync(since)
    [message] = timeline(response, room)
    assert message["content"] == {"msgtype": "m.text", "body": "Hi"}
    assert "transaction_id" not in message.get("unsigned", {})  # Not theirs.
    events = ephemeral(response, room)
    assert [e["type"] for e in events] == [
        "com.acme.progress",
        STATUS,
        "m.receipt",
        "m.typing",
    ]
    receipts = events[2]["content"][event]["m.read"]
    assert set(receipts) == {f"@p{agent.pk}:localhost", f"@p{customer.pk}:localhost"}
    assert events[3]["content"] == {"user_ids": []}  # The latest only.
    data = response["rooms"]["join"][room]
    assert data["unread_notifications"]["notification_count"] == 0


def test_the_latest_of_a_message_being_written(customer_api, conversation, room, agent):
    since = customer_api.sync()["next_batch"]
    services.ephemeral(conversation, STREAM, {"id": "a", "body": "Hel"})
    services.ephemeral(conversation, STREAM, {"id": "a", "body": "Hello"})
    services.ephemeral(conversation, STREAM, {"id": "b", "body": "x"})
    events = ephemeral(customer_api.sync(since), room)
    assert [e["content"]["body"] for e in events] == ["Hello", "x"]


def test_a_new_room_comes_whole(customer_api, agent, customer):
    since = customer_api.sync()["next_batch"]
    conversation = services.create_conversation([agent, customer], title="New")
    services.send(conversation, agent, content.text("Hi"))
    data = customer_api.sync(since)["rooms"]["join"][room_id(conversation)]
    assert "summary" in data  # As a first sync has it.
    types = [e["type"] for e in data["timeline"]["events"]]
    assert types.count("m.room.message") == 1  # Not twice.


def test_leaving(customer_api, conversation, room, customer, agent):
    since = customer_api.sync()["next_batch"]
    services.remove_participant(conversation, customer)
    services.send(conversation, agent, content.text("Not for them"))
    response = customer_api.sync(since)
    assert response["rooms"]["join"] == {}
    [left] = response["rooms"]["leave"][room]["timeline"]["events"]
    assert left["content"]["membership"] == "leave"


def test_account_data(customer_api, conversation, room):
    since = customer_api.sync()["next_batch"]
    me = customer_api.me
    customer_api.ok("PUT", f"/user/{me}/account_data/com.acme.theme", {"dark": True})
    customer_api.ok(
        "PUT", f"/user/{me}/rooms/{room}/account_data/com.acme.pin", {"on": 1}
    )
    response = customer_api.sync(since)
    assert response["account_data"]["events"] == [
        {"type": "com.acme.theme", "content": {"dark": True}}
    ]
    assert response["rooms"]["join"][room]["account_data"]["events"] == [
        {"type": "com.acme.pin", "content": {"on": 1}}
    ]
    # And in a first sync.
    first = customer_api.sync()
    assert first["account_data"]["events"][0]["type"] == "com.acme.theme"
    assert first["rooms"]["join"][room]["account_data"]["events"][0]["type"] == (
        "com.acme.pin"
    )


def test_what_others_get_only_is_left_out(customer_api, conversation, agent):
    since = customer_api.sync()["next_batch"]
    services.entry("unread", conversation=conversation, recipient=agent)
    assert customer_api.sync(since)["rooms"]["join"] == {}


def test_an_entry_still_committing_is_waited_for(customer_api, conversation, agent):
    since = customer_api.sync()["next_batch"]
    services.send(conversation, agent, content.text("1"))
    # The entry before it, still to commit (its id taken, not there yet).
    gap = StreamEntry.objects.filter(kind="event").last()
    StreamEntry.objects.filter(pk=gap.pk).update(id=gap.pk + 5)
    response = customer_api.sync(since)
    assert response["next_batch"] == f"s{gap.pk - 1}"
    # Once what follows it is older than SETTLE, it was rolled back: passed.
    StreamEntry.objects.update(created=timezone.now() - timedelta(seconds=5))
    response = customer_api.sync(response["next_batch"])
    assert response["next_batch"] == f"s{gap.pk + 5}"


def test_too_far_behind_gets_everything_again(customer_api, conversation, room, agent):
    since = customer_api.sync()["next_batch"]
    services.send(conversation, agent, content.text("Hi"))
    StreamEntry.objects.filter(pk__lte=int(since[1:]) + 1).delete()
    response = customer_api.sync(since)
    data = response["rooms"]["join"][room]
    assert data["timeline"]["limited"] is True
    assert "summary" in data


def test_full_state(customer_api, room):
    since = customer_api.sync()["next_batch"]
    assert room in customer_api.sync(since, full_state="true")["rooms"]["join"]


def test_long_polling(customer_api, conversation, agent):
    since = customer_api.sync()["next_batch"]
    response = customer_api.sync(since, timeout="100")
    assert response["next_batch"] == since
    assert customer_api.sync(since, timeout="nope")["next_batch"] == since

    reader = sync.Sync(get_backend(), customer_api.participant, int(since[1:]))
    calls = []

    def read():
        calls.append(1)
        if len(calls) == 2:
            return {"next_batch": "s99"}
        return None

    reader.read = read
    assert asyncio.run(sync.wait(reader, 5)) == {"next_batch": "s99"}
    assert len(calls) == 2


def test_messages(customer_api, conversation, room, agent):
    events = [
        services.send(conversation, agent, content.text(str(n))) for n in range(5)
    ]
    page = customer_api.ok("GET", f"/rooms/{room}/messages", dir="b", limit="2")
    assert [e["content"]["body"] for e in page["chunk"]] == ["4", "3"]
    assert page["end"] == f"t{events[3].pk}"
    assert page["chunk"][0]["room_id"] == room
    older = customer_api.ok(
        "GET", f"/rooms/{room}/messages", dir="b", limit="2", **{"from": page["end"]}
    )
    assert [e["content"]["body"] for e in older["chunk"]] == ["2", "1"]
    assert older["start"] == page["end"]

    forward = customer_api.ok(
        "GET",
        f"/rooms/{room}/messages",
        dir="f",
        limit="2",
        **{"from": f"t{events[1].pk}"},
    )
    assert [e["content"]["body"] for e in forward["chunk"]] == ["1", "2"]
    assert forward["end"] == f"t{events[2].pk + 1}"
    everything = customer_api.ok("GET", f"/rooms/{room}/messages", dir="f", limit="100")
    assert "end" not in everything
    bad = customer_api.ok("GET", f"/rooms/{room}/messages", limit="x")
    assert len(bad["chunk"]) == 10


def test_messages_where_there_are_none(agent):
    from django_chat_ui.models import get_conversation_model

    conversation = services.create_conversation([agent])
    newest = conversation.events.last()
    assert (
        sync.messages(conversation, agent, None, "b", 1)["start"] == f"t{newest.pk + 1}"
    )
    page = sync.messages(conversation, agent, "t1", "b", 10)
    assert page == {"chunk": [], "start": "t1", "state": []}
    empty = get_conversation_model().objects.create()
    assert sync.messages(empty, agent, None, "b", 10)["start"] == "t0"

"""``GET /sync`` (https://spec.matrix.org/v1.11/client-server-api/#get_matrixclientv3sync)
and ``GET /rooms/{roomId}/messages``, read from the log of ``StreamEntry``.

A ``next_batch`` is ``s<position>``: the last entry a client got. A
``prev_batch`` (and the tokens of ``/messages``) is ``t<pk>``: before the
event ``pk`` of a room.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from asgiref.sync import sync_to_async
from django.conf import settings
from django.db.models import Max, Min, Q
from django.utils import timezone

from .matrix import STREAM, client_event, event_id, room_id, timestamp, user_id
from .models import (
    AccountData,
    Membership,
    Receipt,
    RoomEvent,
    RoomState,
    StreamEntry,
    SyncFilter,
    Typing,
)

if TYPE_CHECKING:
    from .backend import ChatBackend
    from .models import AbstractConversation, AbstractParticipant

BATCH = 500
DEFAULT_LIMIT = 20
MAX_LIMIT = 100
HEROES = 5


def setting(name: str, default: Any) -> Any:
    return getattr(settings, "CHAT_UI", {}).get(name, default)


def position(token: Any) -> int | None:
    """The position of a ``next_batch`` (``s42``), or None."""
    match = re.fullmatch(r"s(\d+)", token) if isinstance(token, str) else None
    return int(match.group(1)) if match else None


def timeline_limit(definition: Any) -> int:
    """``room.timeline.limit`` of a filter (its JSON, or its object)."""
    try:
        limit = definition["room"]["timeline"]["limit"]
    except (KeyError, TypeError):
        return DEFAULT_LIMIT
    if not isinstance(limit, int) or isinstance(limit, bool):
        return DEFAULT_LIMIT
    return max(1, min(limit, MAX_LIMIT))


def filter_limit(participant: AbstractParticipant, value: str | None) -> int:
    """The timeline's limit of a ``filter`` parameter: inline JSON, or the
    id of one the client uploaded."""
    if not value:
        return DEFAULT_LIMIT
    if value.lstrip().startswith("{"):
        try:
            return timeline_limit(json.loads(value))
        except ValueError:
            return DEFAULT_LIMIT
    found = (
        SyncFilter.objects.filter(pk=value, participant=participant).first()
        if value.isdigit()
        else None
    )
    return timeline_limit(found.definition) if found else DEFAULT_LIMIT


def advance(after: int) -> int:
    """How far the log can be read after ``after``: past every entry there,
    up to a gap in the ids. Ids are given when an entry is created, but
    transactions commit out of that order: a missing id is waited for (it
    may be about to commit), unless what follows it is older than
    ``SETTLE`` seconds (it was rolled back)."""
    settle = timezone.now() - timedelta(seconds=setting("SETTLE", 1.0))
    horizon = after
    rows = StreamEntry.objects.filter(id__gt=after).order_by("id")
    for pk, created in rows.values_list("id", "created")[:BATCH]:
        if pk != horizon + 1 and created > settle:
            break
        horizon = pk
    return horizon


def settled() -> int:
    """Where a client with nothing yet starts: every entry older than
    ``SETTLE`` is there, and what follows them, up to a gap. Without any
    that old, from the first there is."""
    settle = timezone.now() - timedelta(seconds=setting("SETTLE", 1.0))
    older = StreamEntry.objects.filter(created__lte=settle).aggregate(last=Max("id"))
    if older["last"] is not None:
        return advance(older["last"])
    first = StreamEntry.objects.aggregate(first=Min("id"))["first"]
    return advance(first - 1) if first else 0


def empty(next_batch: int) -> dict[str, Any]:
    return {
        "next_batch": f"s{next_batch}",
        "rooms": {"join": {}, "invite": {}, "leave": {}, "knock": {}},
        "account_data": {"events": []},
        "presence": {"events": []},
        "to_device": {"events": []},
        "device_lists": {"changed": [], "left": []},
        "device_one_time_keys_count": {},
    }


def _receipts(conversation: AbstractConversation) -> dict[str, Any]:
    content: dict[str, Any] = {}
    for receipt in Receipt.objects.filter(conversation=conversation):
        users = content.setdefault(event_id(receipt.event_id), {}).setdefault(
            receipt.type, {}
        )
        users[user_id(receipt.participant_id)] = {"ts": timestamp(receipt.created)}
    return content


def _typing(conversation: AbstractConversation) -> dict[str, Any]:
    typers = Typing.objects.filter(conversation=conversation, until__gt=timezone.now())
    ids = [user_id(pk) for pk in typers.values_list("participant_id", flat=True)]
    return {"type": "m.typing", "content": {"user_ids": ids}}


def _account_data(participant: AbstractParticipant, conversation: Any) -> list:
    rows = AccountData.objects.filter(
        participant=participant, conversation=conversation
    )
    return [{"type": row.type, "content": row.content} for row in rows]


class Sync:
    """What one ``/sync`` of ``participant`` answers, after ``since``."""

    def __init__(
        self,
        backend: ChatBackend,
        participant: AbstractParticipant,
        since: int | None,
        limit: int = DEFAULT_LIMIT,
    ):
        self.backend = backend
        self.participant = participant
        self.limit = limit
        oldest = StreamEntry.objects.order_by("id").values_list("id", flat=True).first()
        #: A client away for longer than the log is kept gets everything
        #: again, as a new one (its timelines ``limited``).
        self.full = since is None or (oldest is not None and since < oldest - 1)
        self.since = 0 if since is None else since
        if since is None:
            self.position = settled()
        elif self.full:
            self.position = advance(oldest - 1 if oldest else 0)
        else:
            self.position = since

    def visible(self) -> Any:
        return self.backend.conversations(self.participant).values("pk")

    def read(self) -> dict[str, Any] | None:
        """The answer, or None: nothing new (yet) for this participant.
        Each call moves ``position`` over what it has read."""
        if self.full:
            self.full = False
            return self.everything()
        before = self.position
        self.position = advance(before)
        if self.position == before:
            return None
        return self.changes(before)

    # Everything ------------------------------------------------------------------

    def everything(self) -> dict[str, Any]:
        response = empty(self.position)
        conversations = self.backend.conversations(self.participant).distinct()
        unread = dict(
            Membership.objects.filter(participant=self.participant).values_list(
                "conversation_id", "unread"
            )
        )
        joined = response["rooms"]["join"]
        for conversation in conversations:
            joined[room_id(conversation)] = self.room(
                conversation, unread.get(conversation.pk, 0), limited=self.since > 0
            )
        response["account_data"]["events"] = _account_data(self.participant, None)
        return response

    def room(
        self, conversation: AbstractConversation, unread: int, *, limited: bool = False
    ) -> dict[str, Any]:
        """A room as a client that has nothing of it gets it: its state, its
        latest events, its receipts, who is typing."""
        events = (
            conversation.events.filter(
                stream_entries__kind="event", stream_entries__id__lte=self.position
            )
            .select_related("redacted_by")
            .order_by("-id")
        )
        rows = list(events[: self.limit + 1])
        more = len(rows) > self.limit
        timeline = rows[: self.limit][::-1]
        first = timeline[0].pk if timeline else None
        in_timeline = {event.pk for event in timeline}
        state = [
            client_event(row.event, room=False, viewer=self.participant)
            for row in RoomState.objects.filter(conversation=conversation)
            .select_related("event__redacted_by")
            .order_by("event_id")
            if row.event_id not in in_timeline
        ]
        members = list(
            Membership.objects.filter(conversation=conversation).values_list(
                "participant_id", flat=True
            )
        )
        heroes = [user_id(pk) for pk in members if pk != self.participant.pk]
        room: dict[str, Any] = {
            "state": {"events": state},
            "timeline": {
                "events": [
                    client_event(event, room=False, viewer=self.participant)
                    for event in timeline
                ],
                "limited": more or limited,
            },
            "ephemeral": {
                "events": [
                    {"type": "m.receipt", "content": _receipts(conversation)},
                    _typing(conversation),
                ]
            },
            "account_data": {"events": _account_data(self.participant, conversation)},
            "unread_notifications": {
                "notification_count": unread,
                "highlight_count": 0,
            },
            "summary": {
                "m.heroes": heroes[:HEROES],
                "m.joined_member_count": len(members),
                "m.invited_member_count": 0,
            },
        }
        if first is not None and more:
            room["timeline"]["prev_batch"] = f"t{first}"
        return room

    # What changed ----------------------------------------------------------------

    def changes(self, before: int) -> dict[str, Any] | None:
        me = self.participant
        visible = Q(recipient=me) | Q(recipient=None, conversation__in=self.visible())
        entries = list(
            StreamEntry.objects.filter(visible, id__gt=before, id__lte=self.position)
            .select_related("event__redacted_by")
            .order_by("id")
        )
        if not entries:
            return None
        response = empty(self.position)
        rooms = response["rooms"]
        joined_now = {e.conversation_id for e in entries if e.kind == "join"}
        left_now = {e.conversation_id for e in entries if e.kind == "leave"}
        touched: dict[Any, dict[str, Any]] = {}

        def room(pk: Any) -> dict[str, Any]:
            if pk not in touched:
                touched[pk] = {
                    "timeline": {"events": [], "limited": False},
                    "state": {"events": []},
                    "ephemeral": {"events": []},
                    "account_data": {"events": []},
                }
            return touched[pk]

        receipts: dict[Any, dict[str, Any]] = {}
        typing: dict[Any, dict[str, Any]] = {}
        streams: dict[Any, dict[str, dict[str, Any]]] = {}
        for entry in entries:
            pk = entry.conversation_id
            if entry.kind == "account_data":
                if pk is None:
                    response["account_data"]["events"].append(
                        {"type": entry.type, "content": entry.data}
                    )
                else:
                    room(pk)["account_data"]["events"].append(
                        {"type": entry.type, "content": entry.data}
                    )
                continue
            if pk in joined_now or pk in left_now:
                continue  # Below: the whole room, or its leaving.
            if entry.kind == "event" and entry.event is not None:
                room(pk)["timeline"]["events"].append(
                    client_event(entry.event, room=False, viewer=me)
                )
            elif entry.kind == "ephemeral" and entry.type == "m.receipt":
                merged = receipts.setdefault(pk, {})
                for target, kinds in entry.data.items():
                    for kind, users in kinds.items():
                        merged.setdefault(target, {}).setdefault(kind, {}).update(users)
                room(pk)
            elif entry.kind == "ephemeral" and entry.type == "m.typing":
                typing[pk] = {"type": "m.typing", "content": entry.data}
                room(pk)
            elif entry.kind == "ephemeral" and entry.type == STREAM:
                # Only the latest of each message being written.
                streams.setdefault(pk, {})[entry.data.get("id", "")] = entry.data
                room(pk)
            elif entry.kind == "ephemeral":
                room(pk)["ephemeral"]["events"].append(
                    {"type": entry.type, "content": entry.data}
                )
            else:  # unread
                room(pk)

        for pk, content in receipts.items():
            touched[pk]["ephemeral"]["events"].append(
                {"type": "m.receipt", "content": content}
            )
        for pk, event in typing.items():
            touched[pk]["ephemeral"]["events"].append(event)
        for pk, latest in streams.items():
            for content in latest.values():
                touched[pk]["ephemeral"]["events"].append(
                    {"type": STREAM, "content": content}
                )

        unread = dict(
            Membership.objects.filter(
                participant=me, conversation__in=[*touched, *joined_now]
            ).values_list("conversation_id", "unread")
        )
        conversations = {
            c.pk: c
            for c in self.backend.conversations(me).filter(
                pk__in=[*touched, *joined_now]
            )
        }
        for pk, data in touched.items():
            if pk not in conversations:
                continue
            data["unread_notifications"] = {
                "notification_count": unread.get(pk, 0),
                "highlight_count": 0,
            }
            rooms["join"][room_id(pk)] = data
        for pk in joined_now:
            if pk in conversations:
                rooms["join"][room_id(pk)] = self.room(
                    conversations[pk], unread.get(pk, 0)
                )
        for entry in entries:
            if entry.kind == "leave" and entry.event is not None:
                rooms["leave"][room_id(entry.conversation_id)] = {
                    "state": {"events": []},
                    "timeline": {
                        "events": [client_event(entry.event, room=False, viewer=me)],
                        "limited": False,
                    },
                }
        if not (rooms["join"] or rooms["leave"] or response["account_data"]["events"]):
            return None
        return response


async def wait(sync: Sync, timeout: float) -> dict[str, Any]:
    """Long polling: the first answer with something, or an empty one after
    ``timeout`` seconds. Waiting costs no thread under ASGI."""
    read = sync_to_async(sync.read)
    end = time.monotonic() + timeout
    while True:
        response = await read()
        if response is not None:
            return response
        if time.monotonic() >= end:
            return empty(sync.position)
        await asyncio.sleep(setting("POLL_INTERVAL", 0.5))


# /messages -------------------------------------------------------------------------


def messages(
    conversation: AbstractConversation,
    viewer: AbstractParticipant,
    start: str | None,
    direction: str,
    limit: int,
) -> dict[str, Any]:
    """A page of a room's timeline: back (``b``, newest first) from a
    ``t<pk>`` token (or from now), or forward (``f``)."""
    events = conversation.events.select_related("redacted_by")
    match = re.fullmatch(r"t(\d+)", start) if isinstance(start, str) else None
    if direction == "f":
        if match:
            events = events.filter(id__gte=match.group(1))
        rows = list(events.order_by("id")[: limit + 1])
    else:
        if match:
            events = events.filter(id__lt=match.group(1))
        rows = list(events.order_by("-id")[: limit + 1])
    more = len(rows) > limit
    rows = rows[:limit]
    data: dict[str, Any] = {
        "chunk": [client_event(event, viewer=viewer) for event in rows],
        "start": start or f"t{(rows[0].pk + 1) if rows else 0}",
        "state": [],
    }
    if more and rows:
        data["end"] = f"t{rows[-1].pk}" if direction != "f" else f"t{rows[-1].pk + 1}"
    return data


def current_state(conversation: AbstractConversation) -> list[RoomEvent]:
    return [
        row.event
        for row in RoomState.objects.filter(conversation=conversation)
        .select_related("event__redacted_by")
        .order_by("event_id")
    ]

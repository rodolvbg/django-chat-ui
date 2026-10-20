"""The stream of events of one participant (docs/protocol.md, 10.1 and 10.3),
read from the log of events in the database."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Max, Q
from django.utils import timezone

from . import protocol
from .models import Event

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

    from .backend import ChatBackend
    from .models import AbstractParticipant

BATCH = 500


def setting(name: str, default: Any) -> Any:
    return getattr(settings, "CHAT_UI", {}).get(name, default)


def dumps(data: Any) -> str:
    return json.dumps(
        data, cls=DjangoJSONEncoder, ensure_ascii=False, separators=(",", ":")
    )


class Reader:
    """Reads, poll after poll, the events ``participant`` may see after
    ``after`` (a ``seq``; None: from now on)."""

    def __init__(
        self,
        backend: ChatBackend,
        participant: AbstractParticipant,
        after: int | None,
        capabilities: dict[str, Any] | None = None,
    ):
        self.backend = backend
        self.participant = participant
        #: The client's, from its hello: what it's sent is degraded for it.
        self.capabilities = capabilities
        if after is None:
            after = Event.objects.aggregate(last=Max("id"))["last"] or 0
        self.after = after

    def read(self) -> list[dict[str, Any]]:
        """The next events. It moves ``after`` over every event it has
        passed, the participant's or not.

        Ids are given when an event is created, but transactions can commit
        out of that order: a missing id is waited for (it may be about to
        commit), unless it's older than ``SETTLE`` seconds (it was rolled
        back, or deleted)."""
        settle = timezone.now() - timedelta(seconds=setting("SETTLE", 1.0))
        rows = Event.objects.filter(id__gt=self.after).order_by("id")
        horizon = self.after
        for pk, created in rows.values_list("id", "created")[:BATCH]:
            if pk != horizon + 1 and created > settle:
                break
            horizon = pk
        if horizon == self.after:
            return []
        visible = Q(recipient=self.participant) | Q(
            recipient=None,
            conversation__in=self.backend.conversations(self.participant).values("pk"),
        )
        events = Event.objects.filter(
            visible, id__gt=self.after, id__lte=horizon
        ).order_by("id")
        self.after = horizon
        frames = (protocol.degrade(e.frame(), self.capabilities) for e in events)
        return [frame for frame in frames if frame is not None]


def message(frame: dict[str, Any]) -> str:
    """One frame as one Server-Sent Events message: no event name, so a
    client gets every type in ``onmessage``; its ``seq`` as the id."""
    return f"id: {frame['seq']}\ndata: {dumps(frame)}\n\n"


def opening(reader: Reader) -> str:
    # The id alone sets the client's Last-Event-ID: a reconnection resumes
    # from here, even if no event of theirs came.
    return f"retry: {setting('RETRY', 1000)}\nid: {reader.after}\n\n"


def chunk(reader: Reader, frames: list[dict[str, Any]], before: int) -> str:
    text = "".join(message(frame) for frame in frames)
    if not frames and reader.after != before:
        text = f"id: {reader.after}\n\n"
    elif frames and frames[-1]["seq"] != reader.after:
        text += f"id: {reader.after}\n\n"
    return text


class Quiet:
    """A comment after ``KEEPALIVE`` seconds without anything to send: so
    proxies keep the connection, and a client that left is noticed."""

    def __init__(self) -> None:
        self.last = time.monotonic()

    def __call__(self, text: str) -> str:
        now = time.monotonic()
        if not text and now - self.last >= setting("KEEPALIVE", 15):
            text = ":\n\n"
        if text:
            self.last = now
        return text


def events(reader: Reader) -> Iterator[str]:
    """The stream, for a WSGI server. It ends after ``STREAM_TIMEOUT``
    seconds, not to hold a worker forever; the browser reconnects (with its
    Last-Event-ID) by itself."""
    yield opening(reader)
    end = time.monotonic() + setting("STREAM_TIMEOUT", 25)
    quiet = Quiet()
    while True:
        before = reader.after
        text = quiet(chunk(reader, reader.read(), before))
        if text:
            yield text
        if time.monotonic() >= end:
            return
        time.sleep(setting("POLL_INTERVAL", 0.5))


async def aevents(reader: Reader) -> AsyncIterator[str]:
    """The same, for an ASGI server: waiting costs no thread."""
    yield opening(reader)
    end = time.monotonic() + setting("STREAM_TIMEOUT", 25)
    quiet = Quiet()
    read = sync_to_async(reader.read)
    while True:
        before = reader.after
        text = quiet(chunk(reader, await read(), before))
        if text:
            yield text
        if time.monotonic() >= end:
            return
        await asyncio.sleep(setting("POLL_INTERVAL", 0.5))

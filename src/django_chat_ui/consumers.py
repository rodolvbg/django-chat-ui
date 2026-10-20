"""The protocol over a WebSocket (docs/protocol.md, 10.2), with Django
Channels (``pip install django-chat-ui[channels]``): one frame per message,
both ways; the client's first is ``hello``, and the stream of its events
starts with the ``ready`` (from its ``resume``, if it gave one).

    # asgi.py
    from channels.auth import AuthMiddlewareStack
    from channels.routing import ProtocolTypeRouter, URLRouter
    from django_chat_ui.routing import websocket_urlpatterns

    application = ProtocolTypeRouter({
        "http": get_asgi_application(),
        "websocket": AuthMiddlewareStack(URLRouter(websocket_urlpatterns)),
    })
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, cast

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.contrib.auth.models import AnonymousUser

from . import commands, stream
from .backend import get_backend
from .views import MAX_FRAMES

if TYPE_CHECKING:
    from django.http import HttpRequest

logger = logging.getLogger("django_chat_ui")

#: Closed for want of a participant (like HTTP's 401, in the private range).
UNAUTHORIZED = 4401


class ScopeRequest:
    """What the backend and the commands read of a request, from the
    connection's scope (its user and session, from Channels' middleware)."""

    method = "WEBSOCKET"

    def __init__(self, scope: dict[str, Any]):
        self.scope = scope
        self.user = scope.get("user") or AnonymousUser()
        self.session = scope.get("session")
        self.path = scope.get("path", "")
        self.META: dict[str, Any] = {}
        self.headers: dict[str, str] = {
            key.decode("latin-1"): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }


class ChatConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self) -> None:
        # Enough of a request for the backend and the commands.
        self.request = cast("HttpRequest", ScopeRequest(self.scope))
        self.backend = get_backend()
        self.task: asyncio.Task | None = None
        self.participant = await database_sync_to_async(self.backend.get_participant)(
            self.request
        )
        if self.participant is None:
            await self.close(code=UNAUTHORIZED)
            return
        await self.accept()

    async def disconnect(self, code: int) -> None:
        if self.task is not None:
            self.task.cancel()

    async def receive_json(self, content: Any, **kwargs: Any) -> None:
        frames = content if isinstance(content, list) else [content]
        for raw in frames[:MAX_FRAMES]:
            answers = await database_sync_to_async(self.command)(raw)
            for answer in answers:
                await self.send_json(answer)
            ready = answers[-1] if answers else None
            if ready and ready["type"] == "ready":
                await self.follow(raw, ready)

    def command(self, raw: Any) -> list[dict[str, Any]]:
        answers = commands.handle(self.backend, self.request, self.participant, raw)
        session = self.request.session
        if session is not None and getattr(session, "modified", False):
            session.save()
        return answers

    async def follow(self, hello: dict[str, Any], ready: dict[str, Any]) -> None:
        """Start (again) the stream of events, after this ``hello``."""
        if self.task is not None:
            self.task.cancel()
        after = None
        if ready["data"].get("resumed"):
            after = hello["data"]["resume"]["seq"]
        self.reader = await database_sync_to_async(stream.Reader)(
            self.backend,
            self.participant,
            after,
            commands.client_capabilities(self.request),
        )
        self.task = asyncio.create_task(self.pump())

    async def pump(self) -> None:
        read = database_sync_to_async(self.reader.read)
        try:
            while True:
                for frame in await read():
                    await self.send_json(frame)
                await asyncio.sleep(stream.setting("POLL_INTERVAL", 0.5))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("django-chat-ui: the WebSocket's stream failed")
            await self.close(code=1011)

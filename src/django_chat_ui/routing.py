"""The WebSocket's route, for Channels' ``URLRouter``: at ``chat/ws``, next
to ``chat/events`` and ``chat/commands`` when the app's URLs are included
at ``chat/``. Elsewhere, route ``ChatConsumer.as_asgi()`` at
``<there>/ws``."""

from django.urls import path

from .consumers import ChatConsumer

websocket_urlpatterns = [path("chat/ws", ChatConsumer.as_asgi())]

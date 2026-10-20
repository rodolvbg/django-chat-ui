"""The example under ASGI: HTTP, and the WebSocket transport (with
Channels). Run it with an ASGI server:

    uvicorn --app-dir example example.asgi:application

and open http://localhost:8000/?transport=websocket
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "example.settings")

django_application = get_asgi_application()

from channels.auth import AuthMiddlewareStack  # noqa: E402
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from django.conf import settings  # noqa: E402
from django.contrib.staticfiles.handlers import ASGIStaticFilesHandler  # noqa: E402

from django_chat_ui.routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter(
    {
        # The static files too, as runserver serves them (in DEBUG only).
        "http": ASGIStaticFilesHandler(django_application)
        if settings.DEBUG
        else django_application,
        "websocket": AuthMiddlewareStack(URLRouter(websocket_urlpatterns)),
    }
)

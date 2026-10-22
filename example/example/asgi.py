"""The example under ASGI, where waiting for a /sync holds no thread:

uvicorn --app-dir example example.asgi:application
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "example.settings")

django_application = get_asgi_application()

from django.conf import settings  # noqa: E402
from django.contrib.staticfiles.handlers import ASGIStaticFilesHandler  # noqa: E402

# The static files too, as runserver serves them (in DEBUG only).
application = (
    ASGIStaticFilesHandler(django_application) if settings.DEBUG else django_application
)

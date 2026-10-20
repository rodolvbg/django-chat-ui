"""A site with a "contact us" widget for its visitors, and an inbox for its
staff, chatting through django-chat-ui. Run it:

    python example/manage.py migrate
    python example/manage.py demo_chat
    python example/manage.py runserver
"""

from pathlib import Path

import django

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = "example-only-not-secret"
DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_chat_ui",
    "shop",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "example.urls"

# A chat writes from several requests at once (a message, its read, a bot's
# answer): SQLite takes its write lock when a transaction starts, instead
# of failing ("database is locked") when two upgrade at the same time.
SQLITE_OPTIONS: dict[str, int | str] = {"timeout": 20}
if django.VERSION >= (5, 1):
    SQLITE_OPTIONS["transaction_mode"] = "IMMEDIATE"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "example.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
        "OPTIONS": SQLITE_OPTIONS,
    }
}

LANGUAGE_CODE = "en"
# Spanish too: the browser's language chooses.
LANGUAGES = [("en", "English"), ("es", "Español")]
USE_I18N = True
USE_TZ = True
TIME_ZONE = "UTC"

STATIC_URL = "static/"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

LOGIN_URL = "admin:login"

CHAT_UI = {"BACKEND": "shop.chat.DemoBackend"}

import tempfile

from example.settings import *  # noqa: F403

# A file, not in memory: the end-to-end tests' server answers the stream
# and the commands from several threads, each with its connection.
_DB = f"{tempfile.mkdtemp(prefix='chat-ui-db-')}/test.sqlite3"
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": _DB,
        "TEST": {"NAME": _DB},
        "OPTIONS": SQLITE_OPTIONS,  # noqa: F405
    }
}
ROOT_URLCONF = "example.urls"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
MEDIA_ROOT = tempfile.mkdtemp(prefix="chat-ui-tests-")
LANGUAGE_CODE = "en"

# The library's own backend; tests of the example set theirs.
CHAT_UI = {"STREAM_TIMEOUT": 0.3, "POLL_INTERVAL": 0.05, "SETTLE": 1.0}

# The library's own models: the example's tickets (helpdesk.Ticket, a
# model of its own for the conversations) are tested by settings_swapped.
INSTALLED_APPS = [app for app in INSTALLED_APPS if app != "helpdesk"]  # noqa: F405
del CHAT_UI_CONVERSATION_MODEL, CHAT_UI_PARTICIPANT_MODEL  # noqa: F821

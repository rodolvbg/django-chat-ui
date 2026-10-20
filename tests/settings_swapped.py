"""The tests with a site's own model of conversations: the example's,
helpdesk.Ticket (CHAT_UI_CONVERSATION_MODEL). Run them with

    pytest --ds tests.settings_swapped
"""

from tests.settings import *  # noqa: F403
from tests.settings import INSTALLED_APPS

INSTALLED_APPS = [*INSTALLED_APPS, "helpdesk"]
CHAT_UI_CONVERSATION_MODEL = "helpdesk.Ticket"
CHAT_UI_PARTICIPANT_MODEL = "helpdesk.Contact"

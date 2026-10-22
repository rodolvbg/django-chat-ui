"""A site's own models (CHAT_UI_CONVERSATION_MODEL): the example's tickets.
Most run with tests.settings_swapped; the migrations, with both."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from django.conf import settings

from django_chat_ui import content, services
from django_chat_ui.backend import ChatBackend
from django_chat_ui.matrix import CONVERSATION, PARTICIPANT, room_id
from django_chat_ui.models import Conversation, RoomState, get_conversation_model

ROOT = Path(__file__).parent.parent
SWAPPED = Conversation._meta.swapped is not None

pytestmark = pytest.mark.django_db
swapped_only = pytest.mark.skipif(not SWAPPED, reason="tests.settings_swapped")


@swapped_only
def test_the_conversations_are_the_sites(agent, customer, agent_user):
    from helpdesk.models import Ticket

    assert get_conversation_model() is Ticket
    ticket = services.create_conversation(
        [agent, customer], channel="whatsapp", priority=2, assignee=agent_user
    )
    assert isinstance(ticket, Ticket)
    services.send(ticket, customer, content.text("Hi"))

    assert [m.body for m in ticket.messages] == ["Hi"]
    assert list(ticket.participants) == [agent, customer]
    # The ticket's own table, not the package's.
    assert Ticket._meta.db_table == "helpdesk_ticket"


def own_state(conversation, type=CONVERSATION, key=""):
    return RoomState.objects.get(
        conversation=conversation, type=type, state_key=key
    ).event.content


@swapped_only
def test_the_site_sends_its_fields(settings, agent, customer, agent_user, customer_api):
    settings.CHAT_UI = {**settings.CHAT_UI, "BACKEND": "shop.chat.DemoBackend"}
    ticket = services.create_conversation(
        [agent, customer], priority=2, assignee=agent_user, capabilities={}
    )
    shop = {"com.example.shop": {"priority": "high", "assignee": "agent"}}
    assert own_state(ticket)["ext"] == shop

    state = customer_api.sync()["rooms"]["join"][room_id(ticket)]["timeline"]["events"]
    [listed] = [e for e in state if e["type"] == CONVERSATION]
    assert listed["content"]["ext"] == shop


@swapped_only
def test_an_agent_answering_takes_the_ticket(
    settings, monkeypatch, agent, agent_api, customer, agent_user
):
    from helpdesk.models import Ticket

    settings.CHAT_UI = {**settings.CHAT_UI, "BACKEND": "shop.chat.DemoBackend"}
    monkeypatch.setattr("shop.chat.DemoBackend.hooks", "inline")
    ticket = services.create_conversation([agent, customer], state="pending")
    agent_api.sent(room_id(ticket), {"msgtype": "m.text", "body": "Hi"})
    assert Ticket.objects.get(pk=ticket.pk).assignee == agent_user


def test_a_site_adds_fields_to_what_is_sent(settings, agent, customer):
    settings.CHAT_UI = {**settings.CHAT_UI, "BACKEND": "tests.test_swapped.CrmBackend"}
    conversation = services.create_conversation([agent, customer], ext={"x": 1})
    member = own_state(conversation, "m.room.member", f"@p{agent.pk}:localhost")
    assert member[PARTICIPANT]["ext"] == {"com.crm": {"id": f"P-{agent.pk}"}}
    assert own_state(conversation) == {
        "channel": "web",
        "state": "open",
        "ext": {"x": 1, "com.crm": {"queue": "sales"}},
    }


class CrmBackend(ChatBackend):
    def serialize_participant(self, participant, data):
        return {**data, "ext": {"com.crm": {"id": f"P-{participant.pk}"}}}

    def serialize_conversation(self, conversation, data):
        return {**data, "ext": {**data.get("ext", {}), "com.crm": {"queue": "sales"}}}


@pytest.mark.parametrize("module", ["tests.settings", "tests.settings_swapped"])
def test_migrations(module, tmp_path):
    """The migrations, applied for real (the tests' database skips them):
    with the package's models and with a site's, in an order that works."""
    env = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": module,
        "PYTHONPATH": os.pathsep.join(
            [str(ROOT / "src"), str(ROOT / "example"), str(ROOT)]
        ),
    }
    script = (
        "import django; django.setup();"
        "from django.conf import settings;"
        f"settings.DATABASES['default']['NAME'] = {str(tmp_path / 'db.sqlite3')!r};"
        "from django.core.management import call_command;"
        "call_command('makemigrations', '--check', '--dry-run', verbosity=0);"
        "call_command('migrate', verbosity=0);"
        "from django_chat_ui.models import get_conversation_model as g;"
        "print(g()._meta.db_table)"
    )
    done = subprocess.run(
        [sys.executable, "-c", script], env=env, capture_output=True, text=True
    )
    assert done.returncode == 0, done.stderr
    table = (
        "helpdesk_ticket"
        if module.endswith("swapped")
        else "django_chat_ui_conversation"
    )
    assert done.stdout.strip() == table


def test_the_settings_are_always_there():
    assert settings.CHAT_UI_PARTICIPANT_MODEL == (
        "helpdesk.Contact" if SWAPPED else "django_chat_ui.Participant"
    )
    assert settings.CHAT_UI_CONVERSATION_MODEL == (
        "helpdesk.Ticket" if SWAPPED else "django_chat_ui.Conversation"
    )

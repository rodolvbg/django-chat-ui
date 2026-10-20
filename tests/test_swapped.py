"""A site's own models (CHAT_UI_CONVERSATION_MODEL): the example's tickets.
Most run with tests.settings_swapped; the migrations, with both."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from django.conf import settings

from django_chat_ui import protocol, services
from django_chat_ui.backend import ChatBackend
from django_chat_ui.models import Conversation, get_conversation_model

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
    services.post(ticket, customer, [{"type": "text", "text": "Hi"}])

    assert [m.parts[0]["text"] for m in ticket.messages.all()] == ["Hi"]
    assert list(ticket.participants) == [agent, customer]
    assert ticket.last_message["parts"] == [{"type": "text", "text": "Hi"}]
    # The ticket's own table, not the package's.
    assert Ticket._meta.db_table == "helpdesk_ticket"


@swapped_only
def test_the_site_sends_its_fields(
    settings, agent, customer, agent_user, customer_chat
):
    settings.CHAT_UI = {**settings.CHAT_UI, "BACKEND": "shop.chat.DemoBackend"}
    ticket = services.create_conversation(
        [agent, customer], priority=2, assignee=agent_user, capabilities={}
    )
    data = protocol.conversation(ticket)
    assert data["ext"] == {"shop": {"priority": "high", "assignee": "agent"}}

    [listed] = customer_chat.hello()["conversations"]
    assert listed["ext"]["shop"]["priority"] == "high"


@swapped_only
def test_an_agent_answering_takes_the_ticket(
    settings, monkeypatch, agent, agent_chat, customer, agent_user
):
    from helpdesk.models import Ticket

    settings.CHAT_UI = {**settings.CHAT_UI, "BACKEND": "shop.chat.DemoBackend"}
    monkeypatch.setattr("shop.chat.DemoBackend.hooks", "inline")
    ticket = services.create_conversation(
        [agent, customer], state="pending", capabilities={"composer": {"mode": "free"}}
    )
    agent_chat.ok(
        "message.send",
        {
            "conversation": str(ticket.pk),
            "clientId": "c",
            "parts": [{"type": "text", "text": "Hi"}],
        },
    )
    assert Ticket.objects.get(pk=ticket.pk).assignee == agent_user


def test_a_site_adds_fields_to_what_is_sent(settings, conversation, agent):
    settings.CHAT_UI = {**settings.CHAT_UI, "BACKEND": "tests.test_swapped.CrmBackend"}
    assert protocol.participant(agent)["ext"] == {"crm": {"id": f"P-{agent.pk}"}}
    assert protocol.conversation(conversation)["meta"] == {"queue": "sales"}


class CrmBackend(ChatBackend):
    def serialize_participant(self, participant, data):
        return {**data, "ext": {"crm": {"id": f"P-{participant.pk}"}}}

    def serialize_conversation(self, conversation, data):
        return {**data, "meta": {"queue": "sales"}}


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

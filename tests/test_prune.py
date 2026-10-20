from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from django_chat_ui.models import Event

pytestmark = pytest.mark.django_db


def test_prune_deletes_old_events(conversation, agent_chat, seq):
    Event.objects.filter(pk__lt=seq).update(created=timezone.now() - timedelta(days=8))
    out = StringIO()
    call_command("chat_ui_prune", stdout=out)
    assert out.getvalue() == f"{seq - 1} events deleted.\n"
    assert list(Event.objects.values_list("id", flat=True)) == [seq]
    # A client that missed what was deleted reloads.
    assert agent_chat.hello(resume={"seq": seq - 3})["resumed"] is False
    assert agent_chat.hello(resume={"seq": seq - 1})["resumed"] is True

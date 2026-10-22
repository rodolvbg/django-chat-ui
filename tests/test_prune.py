from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from django_chat_ui import services
from django_chat_ui.models import RoomEvent, StreamEntry, Typing

pytestmark = pytest.mark.django_db


def test_prune_deletes_old_entries(conversation, customer_api, room, agent):
    services.typing(conversation, agent, True, timeout=0)
    last = StreamEntry.objects.last().pk
    StreamEntry.objects.filter(pk__lt=last).update(
        created=timezone.now() - timedelta(days=8)
    )
    out = StringIO()
    call_command("chat_ui_prune", stdout=out)
    assert out.getvalue() == f"{last - 1} entries deleted.\n"
    assert list(StreamEntry.objects.values_list("id", flat=True)) == [last]
    assert not Typing.objects.exists()
    # The rooms' events stay; a client that missed what was deleted gets
    # everything again.
    assert RoomEvent.objects.filter(conversation=conversation).exists()
    data = customer_api.sync(f"s{last - 3}")["rooms"]["join"][room]
    assert data["timeline"]["limited"] is True

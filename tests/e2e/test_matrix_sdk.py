"""The Matrix project's own client, matrix-js-sdk, against this package's
homeserver: what any Matrix client does works (npm install, for it)."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from django.contrib.auth.models import User

from django_chat_ui import content, services
from django_chat_ui.backend import get_backend
from django_chat_ui.models import RoomEvent

pytestmark = pytest.mark.django_db(transaction=True)

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tests" / "sdk" / "matrix-js-sdk.mjs"


@pytest.fixture(autouse=True)
def short(settings):
    settings.CHAT_UI = {"SYNC_TIMEOUT": 0.5, "POLL_INTERVAL": 0.05}


def test_matrix_js_sdk(live_server):
    node = shutil.which("node")
    if node is None or not (ROOT / "node_modules" / "matrix-js-sdk").exists():
        pytest.skip("node and matrix-js-sdk (npm install) are needed")
    agent = User.objects.create_user(
        "agent", password="pw", first_name="Rodolfo", is_staff=True
    )
    ana = User.objects.create_user("ana", password="pw", first_name="Ana")
    backend = get_backend()
    me, her = backend.participant_for_user(agent), backend.participant_for_user(ana)
    conversation = services.create_conversation(
        [me, her],
        title="Order A-1029",
        capabilities={"reactions": True, "typing": True, "receipts": True},
    )
    services.send(conversation, her, content.text("Where is my order?"))
    services.send(
        conversation,
        me,
        content.text(
            "It ships **today**.", markdown=True, buttons=[{"id": "ok", "label": "OK"}]
        ),
    )

    # Node resolves localhost to ::1 first; the server listens on 127.0.0.1.
    base = live_server.url.replace("localhost", "127.0.0.1") + "/chat"
    result = subprocess.run(
        [node, str(SCRIPT), base, "ana", "pw", "Thanks!"],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=ROOT,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    seen = json.loads(result.stdout.strip().splitlines()[-1])

    assert seen["user_id"] == f"@p{her.pk}:localhost"
    assert seen["rooms"] == 1
    assert seen["name"] == "Order A-1029"
    assert seen["members"] == ["Ana", "Rodolfo"]
    assert seen["capabilities"]["reactions"] is True
    # Its fallback: the buttons' labels in the body.
    assert seen["before"] == ["Where is my order?", "It ships today.\n\n• OK"]
    assert seen["sent"] == seen["echo"]

    sent = RoomEvent.objects.get(pk=seen["sent"][1:])
    assert sent.sender == her
    assert sent.content == {"msgtype": "m.text", "body": "Thanks!"}
    reaction = RoomEvent.objects.get(type="m.reaction")
    assert reaction.sender == her
    assert reaction.content["m.relates_to"]["key"] == "👍"

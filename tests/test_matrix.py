"""Matrix's shapes: identifiers, errors, events, HTML."""

import pytest

from django_chat_ui import matrix, services
from django_chat_ui.matrix import (
    MatrixError,
    client_event,
    markdown_html,
    parse_event,
    parse_mxc,
    parse_room,
    parse_user,
    plain,
    redacted,
    server_name,
)


def test_identifiers(settings):
    assert matrix.user_id(7) == "@p7:localhost"
    assert matrix.user_id(None) == "@system:localhost"
    assert matrix.room_id(3) == "!3:localhost"
    assert matrix.event_id(42) == "$42"
    assert matrix.mxc("abc") == "mxc://localhost/abc"
    settings.CHAT_UI = {"SERVER_NAME": "chat.example.com"}
    assert server_name() == "chat.example.com"
    assert matrix.user_id(7) == "@p7:chat.example.com"


@pytest.mark.parametrize(
    "parse, value, expected",
    [
        (parse_user, "@p7:localhost", "7"),
        (parse_user, "@p7:elsewhere", None),
        (parse_user, "@alice:localhost", None),
        (parse_user, "@pseven:localhost", None),
        (parse_user, 7, None),
        (parse_room, "!3:localhost", "3"),
        (parse_room, "!3", None),
        (parse_event, "$42", "42"),
        (parse_event, "$x", None),
        (parse_event, None, None),
        (parse_mxc, "mxc://localhost/a_b-1", "a_b-1"),
        (parse_mxc, "mxc://elsewhere/a", None),
        (parse_mxc, "https://localhost/a", None),
        (parse_mxc, None, None),
    ],
)
def test_parsing(parse, value, expected):
    assert parse(value) == expected


def test_errors():
    error = MatrixError("M_FORBIDDEN", "No.")
    assert error.status == 403
    assert error.data() == {"errcode": "M_FORBIDDEN", "error": "No."}
    assert MatrixError("M_BAD_JSON").status == 400
    assert MatrixError("M_BAD_JSON").data()["error"] == "M_BAD_JSON"
    assert MatrixError("X", status=418).response().status_code == 418


def test_markdown_html():
    html = markdown_html("**Hi** *you* `x` [site](https://a.b/c)\n<b>\n\n- one\n- two")
    assert html == (
        "<p><strong>Hi</strong> <em>you</em> <code>x</code> "
        '<a href="https://a.b/c">site</a><br>&lt;b&gt;</p>'
        "<ul><li>one</li><li>two</li></ul>"
    )
    # Only http(s) links: anything else stays text.
    assert (
        markdown_html("[x](javascript:alert(1))") == "<p>[x](javascript:alert(1))</p>"
    )
    assert plain("**A** [b](https://c)\n- d") == "A b\nd"


def test_redaction_keeps_what_the_room_version_keeps():
    assert redacted("m.room.message", {"body": "x", "msgtype": "m.text"}) == {}
    assert redacted("m.room.member", {"membership": "join", "displayname": "A"}) == {
        "membership": "join"
    }
    assert redacted("m.room.create", {"room_version": "11"}) == {"room_version": "11"}


@pytest.mark.django_db
def test_client_events(conversation, agent, customer):
    event = services.send(
        conversation, agent, {"msgtype": "m.text", "body": "Hi"}, txn_id="t"
    )
    data = client_event(event, viewer=agent)
    assert data["room_id"] == f"!{conversation.pk}:localhost"
    assert data["sender"] == f"@p{agent.pk}:localhost"
    assert data["unsigned"] == {"transaction_id": "t"}
    assert isinstance(data["origin_server_ts"], int)
    # Its transaction only for its sender.
    assert "unsigned" not in client_event(event, room=False, viewer=customer)
    assert "room_id" not in client_event(event, room=False)

    redaction = services.redact(event, agent, "oops")
    event.refresh_from_db()
    data = client_event(event)
    assert data["content"] == {}
    assert data["unsigned"]["redacted_because"]["event_id"] == redaction.event_id
    assert data["unsigned"]["redacted_because"]["content"]["reason"] == "oops"

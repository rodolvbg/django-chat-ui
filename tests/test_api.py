"""The Client-Server API's endpoints: sessions, rooms, their state."""

import json

import pytest
from django.contrib.auth.models import User
from django.test import Client

from django_chat_ui import content, services
from django_chat_ui.backend import ChatBackend
from django_chat_ui.matrix import CONVERSATION, room_id
from django_chat_ui.models import (
    AccessToken,
    AccountData,
    Membership,
    SyncFilter,
    Typing,
    get_participant_model,
)
from tests.conftest import BASE, Api, text

pytestmark = pytest.mark.django_db


def login(user="ana", password="pw", **extra):
    return Client().post(
        BASE + "/login",
        json.dumps(
            {
                "type": "m.login.password",
                "identifier": {"type": "m.id.user", "user": user},
                "password": password,
                **extra,
            }
        ),
        content_type="application/json",
    )


def test_versions_and_cors():
    response = Client().get("/chat/_matrix/client/versions")
    assert "v1.11" in response.json()["versions"]
    assert response.json()["unstable_features"] == {"io.github.rodolvbg.chat": True}
    assert response["Access-Control-Allow-Origin"] == "*"
    assert Client().options(BASE + "/sync").status_code == 200
    assert Client().options(BASE + "/login")["Access-Control-Allow-Origin"] == "*"


def test_unknown_requests():
    response = Client().get("/chat/_matrix/client/v3/nope")
    assert response.status_code == 404
    assert response.json()["errcode"] == "M_UNRECOGNIZED"
    response = Client().delete("/chat/_matrix/client/versions")
    assert response.status_code == 405
    assert Client().post(BASE + "/sync").status_code == 405


def test_logging_in_with_a_password(customer, customer_user):
    flows = Client().get(BASE + "/login").json()["flows"]
    assert flows == [{"type": "m.login.password"}]

    data = login(device_id="PHONE").json()
    assert data["user_id"] == f"@p{customer.pk}:localhost"
    assert data["device_id"] == "PHONE"
    assert data["home_server"] == "localhost"
    token = AccessToken.objects.get()
    assert token.digest != data["access_token"]  # Only its hash.
    assert str(token) == "Ana · PHONE"

    # Their Matrix ID works as their user too; and the legacy "user".
    assert login(f"@p{customer.pk}:localhost").status_code == 200
    legacy = Client().post(
        BASE + "/login",
        json.dumps({"type": "m.login.password", "user": "ana", "password": "pw"}),
        content_type="application/json",
    )
    assert len(legacy.json()["device_id"]) == 10


@pytest.mark.parametrize(
    "body, errcode",
    [
        ({"type": "m.login.token", "token": "x"}, "M_UNKNOWN"),
        ({"type": "m.login.password", "identifier": {"user": 1}}, "M_BAD_JSON"),
        ({"type": "m.login.password", "user": "ana", "password": "no"}, "M_FORBIDDEN"),
        (
            {"type": "m.login.password", "user": "@p999:localhost", "password": "pw"},
            "M_FORBIDDEN",
        ),
    ],
)
def test_logging_in_wrong(customer, body, errcode):
    response = Client().post(
        BASE + "/login", json.dumps(body), content_type="application/json"
    )
    assert response.json()["errcode"] == errcode


def test_inactive_users_dont_log_in(customer, customer_user):
    customer_user.is_active = False
    customer_user.save()
    assert ChatBackend().login(None, "ana", "pw") is None


def test_bad_bodies(customer_api, room):
    response = customer_api.client.put(
        f"{BASE}/rooms/{room}/send/m.room.message/t",
        "{nope",
        content_type="application/json",
    )
    assert response.json()["errcode"] == "M_NOT_JSON"
    response = customer_api.client.put(
        f"{BASE}/rooms/{room}/send/m.room.message/t",
        "[1]",
        content_type="application/json",
    )
    assert response.json()["errcode"] == "M_BAD_JSON"


def test_tokens(customer, conversation):
    token = login().json()["access_token"]
    api = Api(Client(HTTP_AUTHORIZATION=f"Bearer {token}"), customer)
    assert api.ok("GET", "/account/whoami")["device_id"]
    # As a query parameter too (deprecated, still allowed).
    assert (
        Client().get(BASE + "/account/whoami", {"access_token": token}).status_code
        == 200
    )
    # No CSRF with a token: it isn't the site's session.
    csrf = Client(enforce_csrf_checks=True, HTTP_AUTHORIZATION=f"Bearer {token}")
    assert (
        Api(csrf, customer).send(room_id(conversation), text("Hi")).status_code == 200
    )

    api.ok("POST", "/logout")
    assert api.error("GET", "/account/whoami", status=401) == "M_UNKNOWN_TOKEN"

    first, second = login().json()["access_token"], login().json()["access_token"]
    Api(Client(HTTP_AUTHORIZATION=f"Bearer {first}")).ok("POST", "/logout/all")
    assert not AccessToken.objects.filter(participant=customer).exists()
    assert second


def test_the_sites_session(customer_api, customer_user, customer, room):
    who = customer_api.ok("GET", "/account/whoami")
    assert who == {"user_id": f"@p{customer.pk}:localhost", "is_guest": False}
    customer_api.ok("POST", "/logout")  # Nothing to log out of: the site's.
    assert Client().get(BASE + "/account/whoami").json()["errcode"] == "M_MISSING_TOKEN"

    # Unsafe methods need the CSRF token.
    client = Client(enforce_csrf_checks=True)
    client.force_login(customer_user)
    api = Api(client, customer)
    assert api.refused(room, text("Hi")) == "M_FORBIDDEN"
    client.get("/")  # The CSRF cookie.
    token = client.cookies["csrftoken"].value
    response = client.put(
        f"{BASE}/rooms/{room}/send/m.room.message/t1",
        json.dumps(text("Hi")),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=token,
    )
    assert response.status_code == 200, response.content
    assert api.ok("GET", "/joined_rooms")  # Safe methods don't.


def test_capabilities_pushrules_filters(customer_api, agent_api):
    caps = customer_api.ok("GET", "/capabilities")["capabilities"]
    assert caps["m.room_versions"]["default"] == "11"
    assert customer_api.ok("GET", "/pushrules/")["global"]["override"] == []

    me = customer_api.me
    created = customer_api.ok("POST", f"/user/{me}/filter", {"room": {}})
    assert customer_api.ok("GET", f"/user/{me}/filter/{created['filter_id']}") == {
        "room": {}
    }
    assert SyncFilter.objects.count() == 1
    assert (
        customer_api.error("GET", f"/user/{me}/filter/x", status=404) == "M_NOT_FOUND"
    )
    assert customer_api.error("POST", f"/user/{agent_api.me}/filter") == "M_FORBIDDEN"


def test_account_data(customer_api, room):
    me = customer_api.me
    assert (
        customer_api.error("GET", f"/user/{me}/account_data/x", status=404)
        == "M_NOT_FOUND"
    )
    customer_api.ok("PUT", f"/user/{me}/account_data/x", {"a": 1})
    customer_api.ok("PUT", f"/user/{me}/account_data/x", {"a": 2})
    assert customer_api.ok("GET", f"/user/{me}/account_data/x") == {"a": 2}
    customer_api.ok("PUT", f"/user/{me}/rooms/{room}/account_data/y", {"b": 1})
    assert customer_api.ok("GET", f"/user/{me}/rooms/{room}/account_data/y") == {"b": 1}
    assert AccountData.objects.count() == 2


def test_profiles(customer_api, agent, customer):
    assert customer_api.ok("GET", f"/profile/{customer_api.me}") == {
        "displayname": "Ana"
    }
    # Only of whoever shares a room with them.
    assert (
        customer_api.error("GET", f"/profile/@p{agent.pk}:localhost") == "M_NOT_FOUND"
    )
    services.create_conversation([agent, customer])
    assert customer_api.ok("GET", f"/profile/@p{agent.pk}:localhost") == {
        "displayname": "Rodolfo"
    }
    assert customer_api.ok("GET", f"/profile/@p{agent.pk}:localhost/displayname") == {
        "displayname": "Rodolfo"
    }
    assert (
        customer_api.error("GET", f"/profile/@p{agent.pk}:localhost/avatar_url")
        == "M_NOT_FOUND"
    )
    assert customer_api.ok("GET", f"/profile/{customer_api.me}") == {
        "displayname": "Ana"
    }
    stranger = get_participant_model().objects.create(name="X")
    assert (
        customer_api.error("GET", f"/profile/@p{stranger.pk}:localhost")
        == "M_NOT_FOUND"
    )
    assert customer_api.error("GET", "/profile/@alice:localhost") == "M_NOT_FOUND"
    nameless = get_participant_model().objects.create()
    services.create_conversation([nameless, customer])
    assert customer_api.ok("GET", f"/profile/@p{nameless.pk}:localhost") == {}


def test_starting_a_room(customer_api, agent, customer):
    assert customer_api.ok("GET", "/joined_rooms") == {"joined_rooms": []}
    created = customer_api.ok(
        "POST",
        "/createRoom",
        {
            "initial_state": [
                {"type": CONVERSATION, "content": {"channel": "whatsapp"}},
                "x",
            ]
        },
    )
    conversation = Membership.objects.get(participant=customer).conversation
    assert created == {"room_id": room_id(conversation)}
    # With the support team, waiting for them; named after whoever wrote.
    assert list(conversation.participants) == [customer, agent]
    assert (conversation.channel, conversation.state, conversation.title) == (
        "whatsapp",
        "pending",
        "Ana",
    )
    assert customer_api.ok("GET", "/joined_rooms") == {
        "joined_rooms": [created["room_id"]]
    }


@pytest.mark.parametrize(
    "body, errcode",
    [
        ({"invite": "x"}, "M_BAD_JSON"),
        ({"invite": ["@alice:localhost"]}, "M_NOT_FOUND"),
        ({"invite": ["@p999:localhost"]}, "M_NOT_FOUND"),
        (
            {"initial_state": [{"type": CONVERSATION, "content": {"channel": 1}}]},
            "M_BAD_JSON",
        ),
    ],
)
def test_starting_a_room_wrong(customer_api, body, errcode):
    assert customer_api.error("POST", "/createRoom", body) == errcode


def test_who_starts_with_whom(customer_api, agent_api, agent, customer):
    # A customer only with the team; an agent, with anyone.
    invite = {"invite": [agent_api.me]}
    assert customer_api.error("POST", "/createRoom", invite) == "M_FORBIDDEN"
    created = agent_api.ok(
        "POST", "/createRoom", {"invite": [customer_api.me, agent_api.me]}
    )
    conversation = Membership.objects.get(participant=customer).conversation
    assert created["room_id"] == room_id(conversation)
    assert (conversation.state, conversation.title) == ("open", "")
    assert list(conversation.participants) == [agent, customer]


def test_a_room_one_isnt_in(customer_api, agent):
    other = services.create_conversation([agent])
    for path in (f"/rooms/{room_id(other)}/state", "/rooms/!x:localhost/state"):
        assert customer_api.error("GET", path, status=403) == "M_FORBIDDEN"


def test_state(customer_api, room, conversation, customer):
    events = customer_api.ok("GET", f"/rooms/{room}/state")
    assert {e["type"] for e in events} >= {"m.room.create", CONVERSATION}
    assert customer_api.ok("GET", f"/rooms/{room}/state/{CONVERSATION}") == {
        "channel": "web",
        "state": "open",
    }
    assert (
        customer_api.ok("GET", f"/rooms/{room}/state/{CONVERSATION}/")["channel"]
        == "web"
    )
    member = customer_api.ok(
        "GET", f"/rooms/{room}/state/m.room.member/{customer_api.me}"
    )
    assert member["displayname"] == "Ana"
    assert (
        customer_api.error("GET", f"/rooms/{room}/state/m.room.topic") == "M_NOT_FOUND"
    )
    assert (
        customer_api.error("PUT", f"/rooms/{room}/state/m.room.name", {"name": "x"})
        == "M_FORBIDDEN"
    )

    members = customer_api.ok("GET", f"/rooms/{room}/members")["chunk"]
    assert [m["content"]["displayname"] for m in members] == ["Rodolfo", "Ana"]
    joined = customer_api.ok("GET", f"/rooms/{room}/joined_members")["joined"]
    assert joined[customer_api.me] == {"display_name": "Ana"}
    nameless = get_participant_model().objects.create()
    services.add_participant(conversation, nameless)
    joined = customer_api.ok("GET", f"/rooms/{room}/joined_members")["joined"]
    assert joined[f"@p{nameless.pk}:localhost"] == {}


def test_one_event(customer_api, room, conversation, agent):
    message = services.send(conversation, agent, content.text("Hi"))
    data = customer_api.ok("GET", f"/rooms/{room}/event/{message.event_id}")
    assert data["content"]["body"] == "Hi"
    assert customer_api.error("GET", f"/rooms/{room}/event/$999") == "M_NOT_FOUND"


def test_typing(customer_api, agent_api, room, conversation, customer):
    path = f"/rooms/{room}/typing/{customer_api.me}"
    customer_api.ok("PUT", path, {"typing": True, "timeout": 5000})
    assert Typing.objects.get().participant == customer
    customer_api.ok("PUT", path, {"typing": True, "timeout": "x"})
    customer_api.ok("PUT", path, {"typing": False})
    assert not Typing.objects.exists()
    assert (
        customer_api.error("PUT", f"/rooms/{room}/typing/{agent_api.me}")
        == "M_FORBIDDEN"
    )
    # Where it isn't shown: said, and ignored.
    services.update_conversation(conversation, capabilities={"typing": False})
    customer_api.ok("PUT", path, {"typing": True})
    assert not Typing.objects.exists()


def test_receipts_and_read_markers(customer_api, room, conversation, agent, customer):
    first = services.send(conversation, agent, content.text("1"))
    second = services.send(conversation, agent, content.text("2"))
    customer_api.ok("POST", f"/rooms/{room}/receipt/m.read/{first.event_id}")
    assert Membership.objects.get(participant=customer).unread == 1
    customer_api.ok("POST", f"/rooms/{room}/receipt/m.read.private/{second.event_id}")
    assert Membership.objects.get(participant=customer).unread == 0
    customer_api.ok("POST", f"/rooms/{room}/receipt/m.fully_read/{second.event_id}")
    assert AccountData.objects.get(type="m.fully_read").content == {
        "event_id": second.event_id
    }
    assert customer_api.error(
        "POST", f"/rooms/{room}/receipt/m.nope/{second.event_id}"
    ) == ("M_INVALID_PARAM")
    assert (
        customer_api.error("POST", f"/rooms/{room}/receipt/m.read/$999")
        == "M_NOT_FOUND"
    )

    customer_api.ok(
        "POST",
        f"/rooms/{room}/read_markers",
        {"m.fully_read": first.event_id, "m.read": first.event_id},
    )
    assert Membership.objects.get(participant=customer).last_read == first


def test_leaving(customer_api, room, conversation, customer):
    customer_api.ok("POST", f"/rooms/{room}/leave")
    assert customer not in conversation.participants
    assert customer_api.error("POST", f"/rooms/{room}/leave") == "M_FORBIDDEN"


def test_visitors(settings, agent):
    settings.CHAT_UI = {**settings.CHAT_UI, "BACKEND": "tests.test_api.Open"}
    client = Client()
    who = client.get(BASE + "/account/whoami").json()
    visitor = get_participant_model().objects.get(pk=who["user_id"][2:].split(":")[0])
    assert (visitor.kind, visitor.user) == ("contact", None)
    # Theirs, through the session.
    assert client.get(BASE + "/account/whoami").json() == who


class Open(ChatBackend):
    allow_anonymous = True


def test_a_user_not_of_the_staff(db):
    plain = User.objects.create_user("plain")
    assert ChatBackend().participant_for_user(plain).name == "plain"

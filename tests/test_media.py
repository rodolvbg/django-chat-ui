"""Uploading files (POST /upload) and downloading them, only for those who
see them."""

import pytest
from django.test import Client

from django_chat_ui import services
from django_chat_ui.models import Media

pytestmark = pytest.mark.django_db

UPLOAD = "/chat/_matrix/media/v3/upload"


def upload(client, name="a.png", data=b"\x89PNG", type="image/png"):
    return client.post(f"{UPLOAD}?filename={name}", data, content_type=type)


def download(client, media, path="/chat/_matrix/client/v1/media/download/localhost"):
    return client.get(f"{path}/{media.media_id}")


def test_upload_and_download(customer_api, agent_api, conversation, room):
    response = upload(customer_api.client)
    uri = response.json()["content_uri"]
    media = Media.objects.get()
    assert uri == f"mxc://localhost/{media.media_id}"
    assert (media.name, media.mime, media.size, media.uploader) == (
        "a.png",
        "image/png",
        4,
        customer_api.participant,
    )
    # Its uploader only, until it's sent to a conversation.
    assert download(customer_api.client, media).status_code == 200
    assert download(agent_api.client, media).json()["errcode"] == "M_NOT_FOUND"
    customer_api.sent(room, {"msgtype": "m.image", "body": "a", "url": uri})
    served = download(agent_api.client, media)
    assert served["Content-Type"] == "image/png"
    assert served["X-Content-Type-Options"] == "nosniff"
    assert served["Content-Security-Policy"] == "default-src 'none'; sandbox"
    assert b"".join(served.streaming_content) == b"\x89PNG"
    # Its other addresses: with a name, legacy, thumbnails.
    for path in (
        "/chat/_matrix/media/v3/download/localhost",
        "/chat/_matrix/client/v1/media/thumbnail/localhost",
        "/chat/_matrix/media/v3/thumbnail/localhost",
    ):
        assert download(agent_api.client, media, path).status_code == 200
    named = agent_api.client.get(
        f"/chat/_matrix/client/v1/media/download/localhost/{media.media_id}/b.png"
    )
    assert 'filename="b.png"' in named["Content-Disposition"]


def test_what_isnt_shown_is_downloaded(customer_api):
    upload(customer_api.client, "page.html", b"<script>", "text/html")
    media = Media.objects.get()
    assert media.mime == "text/html"
    served = download(customer_api.client, media)
    assert served["Content-Type"] == "application/octet-stream"
    assert served["Content-Disposition"].startswith("attachment")


def test_other_servers_and_strangers(customer_api):
    upload(customer_api.client)
    media = Media.objects.get()
    assert (
        download(
            customer_api.client,
            media,
            "/chat/_matrix/client/v1/media/download/elsewhere",
        ).status_code
        == 404
    )
    assert download(Client(), media).json()["errcode"] == "M_MISSING_TOKEN"


def test_names_and_types(customer_api):
    upload(customer_api.client, "", b"x", "application/x-thing")
    assert Media.objects.get().name == "file"
    assert Media.objects.get().mime == "application/x-thing"
    Media.objects.all().delete()
    customer_api.client.post(f"{UPLOAD}?filename=x", b"x", content_type="")
    assert Media.objects.get().mime == "application/octet-stream"


def test_too_big(customer_api, monkeypatch):
    from django.core.handlers.wsgi import WSGIRequest

    from django_chat_ui.backend import ChatBackend

    limit = ChatBackend.max_upload_size
    response = upload(customer_api.client, data=b"x" * (limit + 1))
    assert response.status_code == 413
    assert response.json()["errcode"] == "M_TOO_LARGE"
    # Without its length (chunked): what's read is counted.
    monkeypatch.setattr(WSGIRequest, "read", lambda self, size: b"x" * size)
    response = customer_api.client.post(
        f"{UPLOAD}?filename=a", b"", content_type="image/png", CONTENT_LENGTH="x"
    )
    assert response.json()["errcode"] == "M_TOO_LARGE"
    assert not Media.objects.exists()


def test_config(customer_api):
    for path in (
        "/chat/_matrix/client/v1/media/config",
        "/chat/_matrix/media/v3/config",
    ):
        assert customer_api.ok("GET", path) == {"m.upload.size": 5 * 1024 * 1024}


def test_a_conversation_shows_files_of_its_own(customer_api, agent, conversation):
    """A file sent elsewhere isn't downloaded through another conversation."""
    upload(customer_api.client)
    media = Media.objects.get()
    other = services.create_conversation([agent])
    Media.objects.filter(pk=media.pk).update(conversation=other)
    assert download(customer_api.client, media).status_code == 200  # Their upload.

"""Attachments: uploaded for a conversation, sent as its parts, served only
to its participants, never run."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from django_chat_ui.models import Attachment, Message

pytestmark = pytest.mark.django_db

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20


def upload(chat, conversation, name="photo.png", content=PNG):
    return chat.client.post(
        "/chat/uploads",
        {
            "conversation": str(conversation.pk),
            "file": SimpleUploadedFile(name, content),
        },
    )


def test_upload_then_send(customer_chat, customer, conversation):
    response = upload(customer_chat, conversation)
    assert response.status_code == 200
    part = response.json()
    attachment = Attachment.objects.get()
    assert part == {
        "type": "image",
        "url": f"/chat/uploads/{attachment.pk}/photo.png",
        "alt": "photo.png",
        "fallback": "photo.png",
    }
    assert attachment.uploader == customer
    assert attachment.file.name.startswith("chat_ui/")
    assert "photo" not in attachment.file.name

    sent = {**part, "url": f"https://site.example{part['url']}", "alt": "<script>"}
    customer_chat.ok(
        "message.send",
        {"conversation": str(conversation.pk), "clientId": "c_1", "parts": [sent]},
    )
    assert Message.objects.get().parts == [part]


def test_files_are_files(customer_chat, conversation):
    part = upload(customer_chat, conversation, "notes.pdf", b"%PDF").json()
    assert part["type"] == "file"
    assert part["name"] == "notes.pdf"
    assert part["size"] == 4
    assert part["mime"] == "application/pdf"
    # An SVG could run scripts: it's a file to download, not an image.
    assert (
        upload(customer_chat, conversation, "x.svg", b"<svg/>").json()["type"] == "file"
    )


def test_media_parts(customer_chat, conversation):
    from django_chat_ui import services

    services.update_conversation(
        conversation, capabilities={"attachments": {"types": ["image", "audio"]}}
    )
    part = upload(customer_chat, conversation, "voice.ogg", b"OggS").json()
    assert part["type"] == "audio"
    assert part["mime"] == "audio/ogg"
    response = upload(customer_chat, conversation, "notes.pdf", b"%PDF")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsupported"


def test_uploads_follow_the_conversation(customer_chat, conversation, agent):
    from django_chat_ui import services

    assert upload(customer_chat, conversation, content=b"x" * 1001).status_code == 413
    response = customer_chat.client.post(
        "/chat/uploads", {"conversation": str(conversation.pk)}
    )
    assert response.status_code == 400
    response = upload(customer_chat, services.create_conversation([agent]))
    assert response.status_code == 400

    services.update_conversation(conversation, capabilities={"attachments": False})
    response = upload(customer_chat, conversation)
    assert response.json()["error"]["code"] == "unsupported"


def test_uploads_need_a_participant(client, conversation):
    response = client.post("/chat/uploads", {})
    assert response.status_code == 403


def test_only_uploads_of_the_conversation_by_the_sender(
    customer_chat, agent_chat, conversation
):
    part = upload(agent_chat, conversation).json()
    [error] = customer_chat(
        "message.send",
        {"conversation": str(conversation.pk), "clientId": "c_1", "parts": [part]},
    )
    assert error["data"]["code"] == "bad_request"
    [error] = customer_chat(
        "message.send",
        {
            "conversation": str(conversation.pk),
            "clientId": "c_2",
            "parts": [{"type": "image", "url": "/chat/events"}],
        },
    )
    assert error["data"]["code"] == "bad_request"


def test_downloads_only_for_those_who_see_it(customer_chat, agent_user, conversation):
    url = upload(customer_chat, conversation).json()["url"]

    response = customer_chat.client.get(url)
    assert response.status_code == 200
    assert response["Content-Type"] == "image/png"
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response["Content-Security-Policy"] == "default-src 'none'; sandbox"
    assert "attachment" not in response.get("Content-Disposition", "")
    assert b"".join(response.streaming_content) == PNG

    stranger = Client()
    assert stranger.get(url).status_code == 404
    from django.contrib.auth.models import User

    other = Client()
    other.force_login(User.objects.create_user("other"))
    assert other.get(url).status_code == 404


def test_other_files_are_downloaded(customer_chat, conversation):
    url = upload(
        customer_chat, conversation, "page.html", b"<script>alert(1)</script>"
    ).json()["url"]
    response = customer_chat.client.get(url)
    assert response["Content-Type"] == "application/octet-stream"
    assert response["Content-Disposition"].startswith("attachment")

import pytest
from django.contrib.auth.models import User

from django_chat_ui import services
from django_chat_ui.models import Attachment

pytestmark = pytest.mark.django_db


def test_the_admin_shows_the_chat(client, agent, customer, conversation):
    message = services.post(conversation, agent, [{"type": "text", "text": "Hi"}])
    Attachment.objects.create(
        conversation=conversation,
        name="a.png",
        mime="image/png",
        size=1,
        file="chat_ui/a.png",
    )
    client.force_login(User.objects.create_superuser("root"))
    for url in [
        "/admin/django_chat_ui/participant/",
        "/admin/django_chat_ui/conversation/",
        f"/admin/django_chat_ui/conversation/{conversation.pk}/change/",
        "/admin/django_chat_ui/message/",
        f"/admin/django_chat_ui/message/{message.pk}/change/",
        "/admin/django_chat_ui/attachment/",
    ]:
        assert client.get(url).status_code == 200, url

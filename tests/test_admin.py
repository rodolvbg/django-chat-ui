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
    # This package's model, or the site's (the example's helpdesk.Ticket).
    model = conversation._meta
    for url in [
        f"/admin/{agent._meta.app_label}/{agent._meta.model_name}/",
        f"/admin/{model.app_label}/{model.model_name}/",
        f"/admin/{model.app_label}/{model.model_name}/{conversation.pk}/change/",
        "/admin/django_chat_ui/message/",
        f"/admin/django_chat_ui/message/{message.pk}/change/",
        "/admin/django_chat_ui/attachment/",
    ]:
        assert client.get(url).status_code == 200, url


def test_swapped_models_are_left_to_the_site():
    """Registered when they're this package's; a site registers its own
    (with ConversationAdmin, as the example's helpdesk does)."""
    from django.contrib import admin

    from django_chat_ui.models import (
        Conversation,
        Participant,
        get_conversation_model,
        get_participant_model,
    )

    assert admin.site.is_registered(get_conversation_model())
    assert admin.site.is_registered(Conversation) is not Conversation._meta.swapped
    assert admin.site.is_registered(get_participant_model())
    assert admin.site.is_registered(Participant) is not Participant._meta.swapped

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


@pytest.mark.parametrize("swapped", [None, "helpdesk.Model"])
def test_only_the_models_in_use_are_registered(monkeypatch, swapped):
    from django.contrib.admin import AdminSite

    from django_chat_ui.admin import register_models
    from django_chat_ui.models import Conversation, Participant

    for model in (Conversation, Participant):
        monkeypatch.setattr(model._meta, "swapped", swapped)
    site = AdminSite()
    register_models(site)
    assert site.is_registered(Conversation) is (swapped is None)
    assert site.is_registered(Participant) is (swapped is None)


def test_the_settings_of_the_models_are_kept(settings):
    """ready() fills in the settings of the models only if they're missing."""
    from django.apps import apps

    settings.CHAT_UI_CONVERSATION_MODEL = "helpdesk.Ticket"
    del settings.CHAT_UI_PARTICIPANT_MODEL
    apps.get_app_config("django_chat_ui").ready()
    assert settings.CHAT_UI_CONVERSATION_MODEL == "helpdesk.Ticket"
    assert settings.CHAT_UI_PARTICIPANT_MODEL == "django_chat_ui.Participant"

import pytest
from django.contrib.auth.models import User

from django_chat_ui import content, services
from django_chat_ui.models import Media

pytestmark = pytest.mark.django_db


def test_the_admin_shows_the_chat(client, agent, customer, conversation):
    message = services.send(conversation, agent, content.text("Hi"))
    Media.objects.create(
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
        "/admin/django_chat_ui/roomevent/",
        f"/admin/django_chat_ui/roomevent/{message.pk}/change/",
        "/admin/django_chat_ui/media/",
        "/admin/django_chat_ui/streamentry/",
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
    from django.db.models.options import Options

    from django_chat_ui.admin import register_models
    from django_chat_ui.models import Conversation, Participant

    real = Options.swapped
    getter = real.fget if isinstance(real, property) else real.func

    def fake(options):
        if options.model in (Conversation, Participant):
            return swapped
        return getter(options)

    # A property (or a cached one): replaced on the class, for these two.
    monkeypatch.setattr(Options, "swapped", property(fake))
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


def test_what_the_models_say_they_are(conversation, agent):
    from django.utils import timezone

    from django_chat_ui.models import (
        AccountData,
        Receipt,
        RoomState,
        SyncFilter,
        Typing,
    )

    message = services.send(conversation, agent, content.text("Hi"))
    services.read(conversation, agent, message)
    services.typing(conversation, agent, True)
    assert str(RoomState.objects.get(type="m.room.create")) == "m.room.create"
    assert str(Receipt.objects.get()) == f"m.read {message.pk}"
    until = Typing.objects.get().until.astimezone(timezone.get_current_timezone())
    assert str(Typing.objects.get()) == f"{agent.pk} until {until:%H:%M:%S}"
    assert str(AccountData(type="m.fully_read")) == "m.fully_read"
    assert str(SyncFilter.objects.create(participant=agent)).startswith("filter ")

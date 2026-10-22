"""Fill the example with conversations: a WhatsApp chat with a customer,
and an internal one of the team. Creates the staff users ``admin`` and
``lucy`` (password: ``demo``) if they don't exist."""

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from django_chat_ui import content, services
from django_chat_ui.backend import get_backend
from django_chat_ui.models import get_conversation_model, get_participant_model


def is_ticket() -> bool:
    return hasattr(get_conversation_model(), "priority")


def company() -> dict[str, str]:
    # The field of the shop's contacts (helpdesk.Contact), if they are.
    has = any(f.name == "company" for f in get_participant_model()._meta.fields)
    return {"company": "Acme Inc."} if has else {}


class Command(BaseCommand):
    help = __doc__

    def handle(self, *args, **options):
        users = {}
        for username, name in [("admin", "Rodolfo"), ("lucy", "Lucy Martin")]:
            user = User.objects.filter(username=username).first()
            if user is None:
                user = User.objects.create_superuser(
                    username, password="demo", first_name=name
                )
            users[username] = user
        backend = get_backend()
        me = backend.participant_for_user(users["admin"])
        lucy = backend.participant_for_user(users["lucy"])
        anna = get_participant_model().objects.create(
            kind="contact", name="Anna Smith", handle="+1 555 0100", **company()
        )

        # With the fields of the shop's tickets (helpdesk.Ticket), if they are.
        ticket = {"priority": 2, "assignee": users["admin"]} if is_ticket() else {}
        whatsapp = services.create_conversation(
            [me, anna],
            channel="whatsapp",
            **ticket,
            capabilities={
                "receipts": True,
                "typing": True,
                "history": True,
                "reactions": True,
                "composer": {"mode": "free"},
            },
        )
        services.send(
            whatsapp, anna, content.text("Hi, do you have the blue one in M?")
        )
        aside = services.send(whatsapp, me, content.text("Yes! I'll put one aside."))
        services.react(aside, anna, "❤️")
        services.send(whatsapp, anna, content.text("Perfect, thanks 🙌"))

        team = services.create_conversation(
            [me, lucy],
            channel="internal",
            title="Support team",
            capabilities={
                "receipts": True,
                "typing": True,
                "history": True,
                # The team reacts with these only.
                "reactions": {"emojis": ["👍", "✅", "👀", "🎉"]},
            },
        )
        services.send(
            team,
            lucy,
            content.text(
                "Can you look at order A-1029? The customer asks about the delivery."
            ),
        )
        self.stdout.write("Conversations created. Log in as admin / demo.")

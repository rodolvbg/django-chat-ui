"""Fill the example with conversations: a WhatsApp chat with a customer,
and an internal one of the team. Creates the staff users ``admin`` and
``lucy`` (password: ``demo``) if they don't exist."""

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from django_chat_ui import services
from django_chat_ui.backend import get_backend
from django_chat_ui.models import Participant


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
        anna = Participant.objects.create(
            kind="contact", name="Anna Smith", handle="+1 555 0100"
        )

        whatsapp = services.create_conversation(
            [me, anna],
            channel="whatsapp",
            capabilities={
                "receipts": True,
                "typing": True,
                "history": True,
                "reactions": True,
                "composer": {"mode": "free"},
            },
        )
        services.post(
            whatsapp,
            anna,
            [{"type": "text", "text": "Hi, do you have the blue one in M?"}],
        )
        aside = services.post(
            whatsapp, me, [{"type": "text", "text": "Yes! I'll put one aside."}]
        )
        services.update_message(aside, reactions=[{"emoji": "❤️", "by": [str(anna.pk)]}])
        services.post(whatsapp, anna, [{"type": "text", "text": "Perfect, thanks 🙌"}])

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
        services.post(
            team,
            lucy,
            [
                {
                    "type": "text",
                    "text": "Can you look at order A-1029? "
                    "The customer asks about the delivery.",
                }
            ],
        )
        self.stdout.write("Conversations created. Log in as admin / demo.")

"""Fill the example with conversations: a WhatsApp chat with a customer,
and an internal one of the team. Creates the staff users ``admin`` and
``lucia`` (password: ``demo``) if they don't exist."""

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from django_chat_ui import services
from django_chat_ui.backend import get_backend
from django_chat_ui.models import Participant


class Command(BaseCommand):
    help = __doc__

    def handle(self, *args, **options):
        users = {}
        for username, name in [("admin", "Rodolfo"), ("lucia", "Lucía Martín")]:
            user = User.objects.filter(username=username).first()
            if user is None:
                user = User.objects.create_superuser(
                    username, password="demo", first_name=name
                )
            users[username] = user
        backend = get_backend()
        me = backend.participant_for_user(users["admin"])
        lucia = backend.participant_for_user(users["lucia"])
        ana = Participant.objects.create(
            kind="contact", name="Ana García", handle="+34 600 000 000"
        )

        whatsapp = services.create_conversation(
            [me, ana],
            channel="whatsapp",
            capabilities={
                "receipts": True,
                "typing": True,
                "history": True,
                "composer": {"mode": "free"},
            },
        )
        services.post(
            whatsapp,
            ana,
            [{"type": "text", "text": "Hola, ¿tenéis la talla M en azul?"}],
        )
        services.post(whatsapp, me, [{"type": "text", "text": "¡Sí! Te la reservo."}])
        services.post(whatsapp, ana, [{"type": "text", "text": "Perfecto, gracias 🙌"}])

        team = services.create_conversation(
            [me, lucia],
            channel="internal",
            title="Equipo de soporte",
            capabilities={"receipts": True, "typing": True, "history": True},
        )
        services.post(
            team,
            lucia,
            [
                {
                    "type": "text",
                    "text": "¿Puedes mirar el pedido A-1029? "
                    "El cliente pregunta por el envío.",
                }
            ],
        )
        self.stdout.write("Conversations created. Log in as admin / demo.")

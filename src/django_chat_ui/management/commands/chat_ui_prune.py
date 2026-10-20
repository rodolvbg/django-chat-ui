from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from django_chat_ui.models import Event


class Command(BaseCommand):
    help = (
        "Delete the events of the stream older than --days (default 7). A "
        "client away for longer reloads instead of resuming."
    )

    def add_arguments(self, parser):
        parser.add_argument("--days", type=float, default=7)

    def handle(self, *args, days: float, **options):
        cutoff = timezone.now() - timedelta(days=days)
        deleted, _ = Event.objects.filter(created__lt=cutoff).delete()
        self.stdout.write(f"{deleted} events deleted.")

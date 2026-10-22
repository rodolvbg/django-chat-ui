from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from django_chat_ui.models import StreamEntry, Typing


class Command(BaseCommand):
    help = (
        "Delete what /sync read older than --days (default 7): a client away "
        "for longer syncs again from nothing. The rooms' events stay."
    )

    def add_arguments(self, parser):
        parser.add_argument("--days", type=float, default=7)

    def handle(self, *args, days: float, **options):
        cutoff = timezone.now() - timedelta(days=days)
        deleted, _ = StreamEntry.objects.filter(created__lt=cutoff).delete()
        Typing.objects.filter(until__lt=timezone.now()).delete()
        self.stdout.write(f"{deleted} entries deleted.")

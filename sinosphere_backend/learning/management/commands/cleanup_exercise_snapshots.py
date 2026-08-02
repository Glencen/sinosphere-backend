from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from learning.models import ExerciseAttempt, PracticeSession


class Command(BaseCommand):
    help = 'Clear heavy exercise payload snapshots after their retention TTL without deleting FSRS audit data.'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=30)
        parser.add_argument('--batch-size', type=int, default=500)
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=options['days'])
        batch_size = options['batch_size']
        dry_run = options['dry_run']
        queryset = ExerciseAttempt.objects.filter(
            session__status__in=[PracticeSession.STATUS_COMPLETED, PracticeSession.STATUS_EXPIRED, PracticeSession.STATUS_ABANDONED],
            submitted_at__lt=cutoff,
        ).exclude(public_payload={}).order_by('id')

        total = 0
        while True:
            ids = list(queryset.values_list('id', flat=True)[:batch_size])
            if not ids:
                break
            total += len(ids)
            if not dry_run:
                with transaction.atomic():
                    ExerciseAttempt.objects.filter(id__in=ids).update(
                        public_payload={},
                        private_state={},
                        grading_payload={},
                    )
            if len(ids) < batch_size:
                break

        mode = 'would clean' if dry_run else 'cleaned'
        self.stdout.write(self.style.SUCCESS(f'{mode} {total} exercise attempt snapshots'))
import django.utils.timezone
from django.db import migrations, models


def backfill_session_and_attempt_fields(apps, schema_editor):
    PracticeSession = apps.get_model('learning', 'PracticeSession')
    ExerciseAttempt = apps.get_model('learning', 'ExerciseAttempt')

    for session in PracticeSession.objects.all():
        attempts_count = ExerciseAttempt.objects.filter(session_id=session.id).count()
        session.requested_cards_count = session.requested_count or attempts_count or 1
        session.generated_exercises_count = attempts_count
        session.generation_config = session.settings or {}
        if session.status == 'active':
            session.status = 'in_progress'
        session.save(update_fields=[
            'requested_cards_count', 'generated_exercises_count',
            'generation_config', 'status'
        ])

    for attempt in ExerciseAttempt.objects.all():
        attempt.position = attempt.order
        if not attempt.learning_items and attempt.word_id:
            attempt.learning_items = [{'item_type': 'word', 'item_id': attempt.word_id, 'payload': {}}]
        attempt.save(update_fields=['position', 'learning_items'])


class Migration(migrations.Migration):

    dependencies = [
        ('learning', '0004_exercise_attempt_handler_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='practicesession',
            name='requested_cards_count',
            field=models.PositiveIntegerField(default=10),
        ),
        migrations.AddField(
            model_name='practicesession',
            name='generated_exercises_count',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='practicesession',
            name='generation_config',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='practicesession',
            name='started_at',
            field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='practicesession',
            name='expires_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='practicesession',
            name='status',
            field=models.CharField(choices=[('created', 'Created'), ('in_progress', 'In progress'), ('completed', 'Completed'), ('abandoned', 'Abandoned'), ('expired', 'Expired'), ('active', 'Active')], default='created', max_length=16),
        ),
        migrations.AddField(
            model_name='exerciseattempt',
            name='position',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='exerciseattempt',
            name='learning_items',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.RunPython(backfill_session_and_attempt_fields, migrations.RunPython.noop),
        migrations.AddIndex(
            model_name='exerciseattempt',
            index=models.Index(fields=['session', 'position'], name='idx_attempt_session_position'),
        ),
        migrations.AddConstraint(
            model_name='exerciseattempt',
            constraint=models.UniqueConstraint(fields=('session', 'position'), name='unique_attempt_position_in_session'),
        ),
    ]

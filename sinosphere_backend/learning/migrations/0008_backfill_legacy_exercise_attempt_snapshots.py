from django.db import migrations


BATCH_SIZE = 500
HANDLER_KINDS = {'translation_ru', 'translation_cn', 'multiple_choice', 'matching', 'writing'}


def backfill_legacy_attempts(apps, schema_editor):
    ExerciseAttempt = apps.get_model('learning', 'ExerciseAttempt')
    processed = 0
    skipped = 0

    queryset = ExerciseAttempt.objects.order_by('id')
    for attempt in queryset.iterator(chunk_size=BATCH_SIZE):
        update_fields = []
        exercise_type = attempt.exercise_type or attempt.kind or ''

        if not attempt.kind and exercise_type:
            attempt.kind = exercise_type
            update_fields.append('kind')

        if not attempt.handler_version:
            attempt.handler_version = 1
            update_fields.append('handler_version')

        if attempt.is_correct is not None and attempt.status != 'submitted':
            attempt.status = 'submitted'
            update_fields.append('status')
        elif attempt.is_correct is None and not attempt.status:
            attempt.status = 'pending'
            update_fields.append('status')

        if not attempt.learning_items and attempt.word_id:
            attempt.learning_items = [{'item_type': 'word', 'item_id': attempt.word_id, 'payload': {}}]
            update_fields.append('learning_items')

        if not attempt.private_state and attempt.grading_payload:
            attempt.private_state = attempt.grading_payload
            update_fields.append('private_state')

        if not attempt.public_payload and attempt.word_id and exercise_type in HANDLER_KINDS:
            attempt.public_payload = {
                'type': exercise_type,
                'kind': exercise_type,
                'handler_version': attempt.handler_version or 1,
                'word_id': attempt.word_id,
                'attempt_id': attempt.id,
                'session_id': attempt.session_id,
            }
            update_fields.append('public_payload')

        if not attempt.result and attempt.is_correct is not None:
            score = 1.0 if attempt.is_correct else 0.0
            attempt.result = {
                'score': score,
                'is_fully_correct': bool(attempt.is_correct),
                'item_results': [{
                    'source_item_id': attempt.word_id or attempt.id,
                    'is_correct': bool(attempt.is_correct),
                    'score': score,
                    'duration_ms': attempt.duration_ms,
                    'used_hint': False,
                    'attempts_count': 1,
                    'error_code': attempt.error_code or None,
                }],
                'feedback': {},
                'legacy_snapshot': True,
            }
            update_fields.append('result')

        if update_fields:
            attempt.save(update_fields=sorted(set(update_fields)))
            processed += 1
        else:
            skipped += 1

    print(f'Backfilled legacy exercise attempts: processed={processed}, skipped={skipped}')


class Migration(migrations.Migration):

    dependencies = [
        ('learning', '0007_exerciseeventconsumerreceipt_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill_legacy_attempts, migrations.RunPython.noop),
    ]
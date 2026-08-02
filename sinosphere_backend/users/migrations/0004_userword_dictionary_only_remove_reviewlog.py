from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0003_usertopicprogress_attempt_counters'),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name='userword',
            name='idx_user_due',
        ),
        migrations.RemoveIndex(
            model_name='userword',
            name='idx_due',
        ),
        migrations.RemoveIndex(
            model_name='userword',
            name='idx_state',
        ),
        migrations.DeleteModel(
            name='ReviewLog',
        ),
        migrations.AlterModelOptions(
            name='userword',
            options={
                'verbose_name': 'User dictionary word',
                'verbose_name_plural': 'User dictionary words',
            },
        ),
        migrations.RemoveField(
            model_name='userword',
            name='avg_response_time',
        ),
        migrations.RemoveField(
            model_name='userword',
            name='consecutive_correct',
        ),
        migrations.RemoveField(
            model_name='userword',
            name='correct_attempts',
        ),
        migrations.RemoveField(
            model_name='userword',
            name='difficulty',
        ),
        migrations.RemoveField(
            model_name='userword',
            name='due',
        ),
        migrations.RemoveField(
            model_name='userword',
            name='elapsed_days',
        ),
        migrations.RemoveField(
            model_name='userword',
            name='lapses',
        ),
        migrations.RemoveField(
            model_name='userword',
            name='last_review',
        ),
        migrations.RemoveField(
            model_name='userword',
            name='reps',
        ),
        migrations.RemoveField(
            model_name='userword',
            name='scheduled_days',
        ),
        migrations.RemoveField(
            model_name='userword',
            name='stability',
        ),
        migrations.RemoveField(
            model_name='userword',
            name='state',
        ),
        migrations.RemoveField(
            model_name='userword',
            name='total_attempts',
        ),
        migrations.AddIndex(
            model_name='userword',
            index=models.Index(fields=['user', 'added_date'], name='idx_user_word_added'),
        ),
    ]

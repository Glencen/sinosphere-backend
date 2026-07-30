# Generated manually to add persisted generated practice sessions.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dictionary', '0003_examplesentence_topic_alter_wordtag_options_and_more'),
        ('learning', '0002_dailygoal_user_date_unique'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='PracticeSession',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('session_type', models.CharField(default='mixed', max_length=32)),
                ('requested_count', models.PositiveSmallIntegerField(default=10)),
                ('settings', models.JSONField(blank=True, default=dict)),
                ('status', models.CharField(choices=[('active', 'Active'), ('completed', 'Completed'), ('abandoned', 'Abandoned')], default='active', max_length=16)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('topic', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='practice_sessions', to='dictionary.topic')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='practice_sessions', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='ExerciseAttempt',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('exercise_type', models.CharField(max_length=32)),
                ('order', models.PositiveSmallIntegerField(default=0)),
                ('public_payload', models.JSONField(default=dict)),
                ('grading_payload', models.JSONField(default=dict)),
                ('answer', models.JSONField(blank=True, null=True)),
                ('is_correct', models.BooleanField(blank=True, null=True)),
                ('time_spent', models.FloatField(default=0)),
                ('rating', models.PositiveSmallIntegerField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('submitted_at', models.DateTimeField(blank=True, null=True)),
                ('session', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='attempts', to='learning.practicesession')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='exercise_attempts', to=settings.AUTH_USER_MODEL)),
                ('word', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='exercise_attempts', to='dictionary.word')),
            ],
            options={
                'ordering': ['session', 'order'],
            },
        ),
        migrations.AddIndex(
            model_name='practicesession',
            index=models.Index(fields=['user', 'status'], name='idx_practice_user_status'),
        ),
        migrations.AddIndex(
            model_name='practicesession',
            index=models.Index(fields=['user', 'created_at'], name='idx_practice_user_created'),
        ),
        migrations.AddIndex(
            model_name='exerciseattempt',
            index=models.Index(fields=['user', 'is_correct'], name='idx_attempt_user_correct'),
        ),
        migrations.AddIndex(
            model_name='exerciseattempt',
            index=models.Index(fields=['session', 'order'], name='idx_attempt_session_order'),
        ),
        migrations.AddConstraint(
            model_name='exerciseattempt',
            constraint=models.UniqueConstraint(fields=('session', 'order'), name='unique_session_attempt_order'),
        ),
    ]

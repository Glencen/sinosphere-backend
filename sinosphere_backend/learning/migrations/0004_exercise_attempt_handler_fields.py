# Generated for exercise handler architecture stage 1.

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('learning', '0003_practicesession_exerciseattempt'),
    ]

    operations = [
        migrations.AddField(
            model_name='exerciseattempt',
            name='duration_ms',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='exerciseattempt',
            name='error_code',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
        migrations.AddField(
            model_name='exerciseattempt',
            name='handler_version',
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AddField(
            model_name='exerciseattempt',
            name='kind',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
        migrations.AddField(
            model_name='exerciseattempt',
            name='private_state',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='exerciseattempt',
            name='result',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='exerciseattempt',
            name='score',
            field=models.DecimalField(decimal_places=4, default=0, max_digits=6),
        ),
        migrations.AddField(
            model_name='exerciseattempt',
            name='started_at',
            field=models.DateTimeField(default=django.utils.timezone.now),
        ),
        migrations.AddField(
            model_name='exerciseattempt',
            name='static_exercise',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='attempts', to='learning.exercise'),
        ),
        migrations.AddField(
            model_name='exerciseattempt',
            name='status',
            field=models.CharField(choices=[('pending', 'Pending'), ('submitted', 'Submitted'), ('expired', 'Expired')], default='pending', max_length=16),
        ),
        migrations.AddIndex(
            model_name='exerciseattempt',
            index=models.Index(fields=['kind', 'handler_version'], name='idx_attempt_handler'),
        ),
        migrations.AddIndex(
            model_name='exerciseattempt',
            index=models.Index(fields=['user', 'status'], name='idx_attempt_user_status'),
        ),
    ]

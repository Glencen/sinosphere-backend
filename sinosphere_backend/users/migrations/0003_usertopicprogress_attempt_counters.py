# Generated manually to align UserTopicProgress with learning views.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0002_reviewlog_userexercisehistory_userlearningprofile_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='usertopicprogress',
            name='total_attempts',
            field=models.IntegerField(default=0, verbose_name='Всего попыток'),
        ),
        migrations.AddField(
            model_name='usertopicprogress',
            name='total_correct',
            field=models.IntegerField(default=0, verbose_name='Правильных попыток'),
        ),
    ]

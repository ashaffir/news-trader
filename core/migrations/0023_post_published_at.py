from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0022_twittersession'),
    ]

    operations = [
        migrations.AddField(
            model_name='post',
            name='published_at',
            field=models.DateTimeField(null=True, blank=True),
        ),
    ]



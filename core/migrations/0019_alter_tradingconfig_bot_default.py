from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0018_alertsettings_heartbeat_enabled_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='tradingconfig',
            name='bot_enabled',
            field=models.BooleanField(
                default=False,
                help_text='Master switch to enable/disable all bot activities (scraping, analysis, trading)'
            ),
        ),
    ]



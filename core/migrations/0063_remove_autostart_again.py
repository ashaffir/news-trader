from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0062_tradingconfig_autostart"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="tradingconfig",
            name="autostart",
        ),
    ]



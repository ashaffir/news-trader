from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0060_drop_trading_flags"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="tradingconfig",
            name="autostart",
        ),
    ]



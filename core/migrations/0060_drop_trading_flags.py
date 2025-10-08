from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0058_tradingconfig_allow_untracked_symbols"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="tradingconfig",
            name="trading_enabled",
        ),
        migrations.RemoveField(
            model_name="tradingconfig",
            name="market_hours_only",
        ),
    ]



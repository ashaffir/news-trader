from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0035_tradingconfig_intraday_close_minutes_before_and_more"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="analysis",
            name="sentiment_score",
        ),
        migrations.RemoveField(
            model_name="analysis",
            name="market_impact_score",
        ),
    ]



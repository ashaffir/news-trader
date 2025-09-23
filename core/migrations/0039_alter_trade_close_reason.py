from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0038_add_stale_close_reason"),
    ]

    operations = [
        migrations.AlterField(
            model_name="trade",
            name="close_reason",
            field=models.CharField(
                choices=[
                    ("manual", "Manual Close"),
                    ("stop_loss", "Stop Loss"),
                    ("take_profit", "Take Profit"),
                    ("time_limit", "Time Limit"),
                    ("market_close", "Market Close"),
                    ("market_consensus_lost", "Market Consensus Lost"),
                    ("stale", "Stale - Time Limit Reached"),
                ],
                max_length=25,
                blank=True,
                null=True,
            ),
        ),
    ]



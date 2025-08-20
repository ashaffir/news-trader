from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0023_post_published_at"),
    ]

    operations = [
        # TradingConfig trailing fields
        migrations.AddField(
            model_name="tradingconfig",
            name="trailing_stop_enabled",
            field=models.BooleanField(
                default=False,
                help_text="Enable trailing stop loss management for open positions",
            ),
        ),
        migrations.AddField(
            model_name="tradingconfig",
            name="trailing_stop_distance_percentage",
            field=models.FloatField(
                default=1.0,
                validators=[
                    django.core.validators.MinValueValidator(0.1),
                    django.core.validators.MaxValueValidator(50.0),
                ],
                help_text="Distance of trailing stop from favorable extreme (in %)",
            ),
        ),
        migrations.AddField(
            model_name="tradingconfig",
            name="trailing_stop_activation_profit_percentage",
            field=models.FloatField(
                default=0.0,
                validators=[
                    django.core.validators.MinValueValidator(0.0),
                    django.core.validators.MaxValueValidator(100.0),
                ],
                help_text="Activate trailing stop only after unrealized profit reaches this %",
            ),
        ),

        # Trade trailing tracking fields
        migrations.AddField(
            model_name="trade",
            name="highest_price_since_open",
            field=models.FloatField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name="trade",
            name="lowest_price_since_open",
            field=models.FloatField(null=True, blank=True),
        ),
    ]



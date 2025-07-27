# Generated manually to handle adding fields to existing models

from django.db import migrations, models
import django.core.validators
import django.db.models.deletion
from django.utils import timezone


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0006_alter_post_source_apiresponse_post_api_response"),
    ]

    operations = [
        # Create TradingConfig model
        migrations.CreateModel(
            name="TradingConfig",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(default="Default Config", max_length=255)),
                (
                    "default_position_size",
                    models.FloatField(
                        default=100.0, help_text="Default position size in dollars"
                    ),
                ),
                (
                    "max_position_size",
                    models.FloatField(
                        default=1000.0, help_text="Maximum position size in dollars"
                    ),
                ),
                (
                    "position_sizing_method",
                    models.CharField(
                        choices=[
                            ("fixed", "Fixed Amount"),
                            ("percentage", "Percentage of Portfolio"),
                            ("risk_based", "Risk-Based Sizing"),
                        ],
                        default="fixed",
                        max_length=20,
                    ),
                ),
                (
                    "stop_loss_percentage",
                    models.FloatField(
                        default=5.0,
                        help_text="Stop loss percentage (1.0 = 1%)",
                        validators=[
                            django.core.validators.MinValueValidator(0.1),
                            django.core.validators.MaxValueValidator(50.0),
                        ],
                    ),
                ),
                (
                    "take_profit_percentage",
                    models.FloatField(
                        default=10.0,
                        help_text="Take profit percentage (1.0 = 1%)",
                        validators=[
                            django.core.validators.MinValueValidator(0.1),
                            django.core.validators.MaxValueValidator(100.0),
                        ],
                    ),
                ),
                (
                    "max_daily_trades",
                    models.IntegerField(default=10, help_text="Maximum trades per day"),
                ),
                (
                    "min_confidence_threshold",
                    models.FloatField(
                        default=0.7,
                        help_text="Minimum LLM confidence to execute trade",
                        validators=[
                            django.core.validators.MinValueValidator(0.0),
                            django.core.validators.MaxValueValidator(1.0),
                        ],
                    ),
                ),
                (
                    "llm_model",
                    models.CharField(default="gpt-3.5-turbo", max_length=100),
                ),
                (
                    "llm_prompt_template",
                    models.TextField(
                        default='You are a financial analyst. Analyze the given text for potential financial impact on a stock. \nRespond with a JSON object: { "symbol": "STOCK_SYMBOL", "direction": "buy", "confidence": 0.87, "reason": "Explanation" }. \nDirection can be \'buy\', \'sell\', or \'hold\'. Confidence is a float between 0 and 1.',
                        help_text="LLM prompt template for financial analysis",
                    ),
                ),
                ("trading_enabled", models.BooleanField(default=True)),
                (
                    "market_hours_only",
                    models.BooleanField(
                        default=True, help_text="Only trade during market hours"
                    ),
                ),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["-is_active", "-created_at"],
            },
        ),
        # Add new fields to Source model
        migrations.AddField(
            model_name="source",
            name="data_extraction_config",
            field=models.JSONField(
                blank=True,
                help_text="JSON config for data extraction rules (CSS selectors, JSON paths, etc.)",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="source",
            name="scraping_enabled",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="source",
            name="scraping_interval_minutes",
            field=models.IntegerField(
                default=5, help_text="Scraping interval in minutes"
            ),
        ),
        migrations.AddField(
            model_name="source",
            name="last_scraped_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="source",
            name="scraping_status",
            field=models.CharField(
                choices=[
                    ("idle", "Idle"),
                    ("running", "Running"),
                    ("error", "Error"),
                    ("disabled", "Disabled"),
                ],
                default="idle",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="source",
            name="error_count",
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name="source",
            name="last_error",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="source",
            name="created_at",
            field=models.DateTimeField(default=timezone.now),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="source",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),
        # Add new fields to Analysis model
        migrations.AddField(
            model_name="analysis",
            name="trading_config_used",
            field=models.ForeignKey(
                blank=True,
                help_text="Trading config used for this analysis",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to="core.tradingconfig",
            ),
        ),
        migrations.AddField(
            model_name="analysis",
            name="sentiment_score",
            field=models.FloatField(
                blank=True, help_text="Sentiment score from -1 to 1", null=True
            ),
        ),
        migrations.AddField(
            model_name="analysis",
            name="market_impact_score",
            field=models.FloatField(
                blank=True, help_text="Predicted market impact score", null=True
            ),
        ),
        # Update Trade model with new status choices and fields
        migrations.AlterField(
            model_name="trade",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("open", "Open"),
                    ("closed", "Closed"),
                    ("cancelled", "Cancelled"),
                    ("failed", "Failed"),
                ],
                default="pending",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="trade",
            name="alpaca_order_id",
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AddField(
            model_name="trade",
            name="stop_loss_price",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="trade",
            name="take_profit_price",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="trade",
            name="close_reason",
            field=models.CharField(
                blank=True,
                choices=[
                    ("manual", "Manual Close"),
                    ("stop_loss", "Stop Loss"),
                    ("take_profit", "Take Profit"),
                    ("time_limit", "Time Limit"),
                    ("market_close", "Market Close"),
                ],
                max_length=20,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="trade",
            name="unrealized_pnl",
            field=models.FloatField(default=0.0),
        ),
        migrations.AddField(
            model_name="trade",
            name="realized_pnl",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="trade",
            name="commission",
            field=models.FloatField(default=0.0),
        ),
        migrations.AddField(
            model_name="trade",
            name="opened_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="trade",
            name="closed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]

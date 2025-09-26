from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0041_add_duplicate_sync_reason"),
    ]

    operations = [
        migrations.AddField(
            model_name="tradingconfig",
            name="confidence_weight_impact_size",
            field=models.FloatField(default=0.35, validators=[django.core.validators.MinValueValidator(0.0), django.core.validators.MaxValueValidator(1.0)], help_text="Weight for impact_size when computing final confidence (0-1)"),
        ),
        migrations.AddField(
            model_name="tradingconfig",
            name="confidence_weight_time_proximity",
            field=models.FloatField(default=0.25, validators=[django.core.validators.MinValueValidator(0.0), django.core.validators.MaxValueValidator(1.0)], help_text="Weight for time_proximity when computing final confidence (0-1)"),
        ),
        migrations.AddField(
            model_name="tradingconfig",
            name="confidence_weight_clarity",
            field=models.FloatField(default=0.15, validators=[django.core.validators.MinValueValidator(0.0), django.core.validators.MaxValueValidator(1.0)], help_text="Weight for clarity when computing final confidence (0-1)"),
        ),
        migrations.AddField(
            model_name="tradingconfig",
            name="confidence_weight_volatility_sensitivity",
            field=models.FloatField(default=0.15, validators=[django.core.validators.MinValueValidator(0.0), django.core.validators.MaxValueValidator(1.0)], help_text="Weight for volatility_sensitivity when computing final confidence (0-1)"),
        ),
        migrations.AddField(
            model_name="tradingconfig",
            name="confidence_weight_duration",
            field=models.FloatField(default=0.1, validators=[django.core.validators.MinValueValidator(0.0), django.core.validators.MaxValueValidator(1.0)], help_text="Weight for duration when computing final confidence (0-1)"),
        ),
        migrations.AddField(
            model_name="tradingconfig",
            name="hold_time_time_to_peak_min_hours",
            field=models.FloatField(default=0.25, validators=[django.core.validators.MinValueValidator(0.0)], help_text="Minimum time to peak impact in hours"),
        ),
        migrations.AddField(
            model_name="tradingconfig",
            name="hold_time_time_to_peak_max_hours",
            field=models.FloatField(default=8.0, validators=[django.core.validators.MinValueValidator(0.0)], help_text="Maximum time to peak impact in hours"),
        ),
        migrations.AddField(
            model_name="tradingconfig",
            name="hold_time_time_proximity_exponent",
            field=models.FloatField(default=1.7, validators=[django.core.validators.MinValueValidator(0.0)], help_text="Exponent applied to (1 - time_proximity) when computing time_to_peak"),
        ),
        migrations.AddField(
            model_name="tradingconfig",
            name="hold_time_tail_multiplier",
            field=models.FloatField(default=2.0, validators=[django.core.validators.MinValueValidator(0.0)], help_text="Multiplier applied to tail duration component"),
        ),
        migrations.AddField(
            model_name="tradingconfig",
            name="hold_time_tail_duration_exponent",
            field=models.FloatField(default=1.2, validators=[django.core.validators.MinValueValidator(0.0)], help_text="Exponent applied to duration when computing tail"),
        ),
        migrations.AddField(
            model_name="tradingconfig",
            name="hold_time_tail_impact_base",
            field=models.FloatField(default=0.5, validators=[django.core.validators.MinValueValidator(0.0)], help_text="Base factor for impact contribution in tail"),
        ),
        migrations.AddField(
            model_name="tradingconfig",
            name="hold_time_tail_impact_scale",
            field=models.FloatField(default=0.5, validators=[django.core.validators.MinValueValidator(0.0)], help_text="Scale factor for impact contribution in tail"),
        ),
    ]



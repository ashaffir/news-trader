from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0042_add_llm_calculation_params"),
    ]

    operations = [
        migrations.AddField(
            model_name="tradingconfig",
            name="hold_time_min_hours",
            field=models.FloatField(default=0.5, validators=[django.core.validators.MinValueValidator(0.0)], help_text="Minimum holding time in hours to enforce on computed per-analysis value"),
        ),
    ]



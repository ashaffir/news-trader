from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0036_remove_analysis_sentiment_and_impact"),
    ]

    operations = [
        migrations.AddField(
            model_name="analysis",
            name="max_holding_time_hours",
            field=models.FloatField(blank=True, null=True, help_text="Maximum holding time in hours suggested by LLM for this analysis"),
        ),
        migrations.AddField(
            model_name="trade",
            name="max_holding_time_hours",
            field=models.FloatField(blank=True, null=True, help_text="Per-trade maximum holding time in hours; if set, overrides global config"),
        ),
    ]



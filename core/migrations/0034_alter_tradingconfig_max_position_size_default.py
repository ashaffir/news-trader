from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0033_analysis_used_llm_model"),
    ]

    operations = [
        migrations.AlterField(
            model_name="tradingconfig",
            name="max_position_size",
            field=models.FloatField(default=100.0, help_text="Maximum position size in dollars"),
        ),
    ]



from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0032_add_tradingconfig_autostart"),
    ]

    operations = [
        migrations.AddField(
            model_name="analysis",
            name="used_llm_model",
            field=models.CharField(
                max_length=200,
                null=True,
                blank=True,
                help_text="LLM model identifier used when creating this analysis",
            ),
        ),
    ]



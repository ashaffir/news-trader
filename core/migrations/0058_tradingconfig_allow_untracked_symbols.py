from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0057_tradingconfig_overnight_max_age_hours"),
    ]

    operations = [
        migrations.AddField(
            model_name="tradingconfig",
            name="allow_untracked_symbols",
            field=models.BooleanField(default=True, help_text="If True, do not enforce TrackedCompany membership before trading"),
        ),
    ]



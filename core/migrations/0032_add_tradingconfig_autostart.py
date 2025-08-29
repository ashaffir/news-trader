from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0031_rename_core_config_name_idx_core_config_name_8a439d_idx_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="tradingconfig",
            name="autostart",
            field=models.BooleanField(
                default=False,
                help_text="Automatically enable bot during market hours and disable when closed",
            ),
        ),
    ]



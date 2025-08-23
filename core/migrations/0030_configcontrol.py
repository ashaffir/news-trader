from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0029_alertsettings_system_errors_enabled"),
    ]

    operations = [
        migrations.CreateModel(
            name="ConfigControl",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=255, unique=True)),
                ("value_type", models.CharField(choices=[("string", "String"), ("integer", "Integer"), ("float", "Float"), ("json", "JSON")], default="string", max_length=20)),
                ("value_string", models.TextField(blank=True, null=True)),
                ("value_int", models.IntegerField(blank=True, null=True)),
                ("value_float", models.FloatField(blank=True, null=True)),
                ("value_json", models.JSONField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["name"],
            },
        ),
        migrations.AddIndex(
            model_name="configcontrol",
            index=models.Index(fields=["name"], name="core_config_name_idx"),
        ),
    ]



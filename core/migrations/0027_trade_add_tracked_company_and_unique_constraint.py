from django.db import migrations, models
import django.db.models.deletion
import django.db.models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0026_alter_trackedcompany_symbol"),
    ]

    operations = [
        migrations.AddField(
            model_name="trade",
            name="tracked_company",
            field=models.ForeignKey(
                related_name="trades",
                on_delete=django.db.models.deletion.PROTECT,
                to="core.trackedcompany",
                null=True,
                blank=True,
            ),
        ),
        migrations.RemoveConstraint(
            model_name="trade",
            name="unique_active_trade_per_symbol",
        ),
        migrations.AddConstraint(
            model_name="trade",
            constraint=models.UniqueConstraint(
                fields=["tracked_company"],
                condition=django.db.models.Q(
                    ("status__in", ["open", "pending", "pending_close"]) 
                ),
                name="unique_active_trade_per_company",
            ),
        ),
    ]



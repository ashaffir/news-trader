from django.db import migrations, models
import django.db.models


class Migration(migrations.Migration):

	dependencies = [
		("core", "0027_trade_add_tracked_company_and_unique_constraint"),
	]

	operations = [
		migrations.AddConstraint(
			model_name="trade",
			constraint=models.UniqueConstraint(
				fields=["symbol"],
				condition=django.db.models.Q(
					("tracked_company__isnull", True),
					("status__in", ["open", "pending", "pending_close"]),
				),
				name="unique_active_trade_per_symbol_when_untracked",
			),
		),
	]



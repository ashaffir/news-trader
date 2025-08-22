from django.db import migrations


def forwards(apps, schema_editor):
    Trade = apps.get_model("core", "Trade")
    TrackedCompany = apps.get_model("core", "TrackedCompany")

    # Build a quick lookup for symbols -> company id
    symbol_to_id = {tc.symbol.upper(): tc.id for tc in TrackedCompany.objects.all()}

    # Iterate trades without tracked_company and try to map by symbol
    for trade in Trade.objects.filter(tracked_company__isnull=True).only("id", "symbol"):
        symbol = (trade.symbol or "").upper().strip()
        company_id = symbol_to_id.get(symbol)
        if company_id:
            Trade.objects.filter(id=trade.id).update(tracked_company_id=company_id)


def backwards(apps, schema_editor):
    Trade = apps.get_model("core", "Trade")
    # Safe to null out FK; symbol column remains for backward compatibility
    Trade.objects.update(tracked_company=None)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0027_trade_add_tracked_company_and_unique_constraint"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]



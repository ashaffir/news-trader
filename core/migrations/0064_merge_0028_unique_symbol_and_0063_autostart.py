from django.db import migrations


class Migration(migrations.Migration):

    # Merge the two heads:
    # - 0028_trade_add_fallback_symbol_unique_constraint
    # - 0063_remove_autostart_again
    dependencies = [
        ("core", "0028_trade_add_fallback_symbol_unique_constraint"),
        ("core", "0063_remove_autostart_again"),
    ]

    operations = []



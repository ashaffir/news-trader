from __future__ import annotations

from typing import Any


def get_config_value(name: str, default: Any | None = None) -> Any:
    """Fetch configuration value from ConfigControl by name.

    Returns `default` if not found or if table is unavailable (e.g., during early
    migrations/tests).
    """
    try:
        from core.models import ConfigControl
        cfg = ConfigControl.objects.filter(name=name).first()
        if cfg is not None:
            return cfg.value
    except Exception:
        # Table may not exist or DB not ready; return default
        pass
    return default



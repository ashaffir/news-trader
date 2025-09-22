"""Celery task wrappers for trading operations.

Ensure Celery autodiscovery imports the actual task module.
Celery imports <app>.tasks, so we must import our submodule for side-effects.
"""

# Import submodule so @shared_task functions register with Celery
from . import trades as _trades  # noqa: F401


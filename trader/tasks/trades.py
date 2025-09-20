import logging
from celery import shared_task


logger = logging.getLogger(__name__)


@shared_task
def execute_trade(analysis_id):
    """Delegate to legacy implementation to avoid breakage during migration."""
    try:
        from core.tasks import execute_trade as core_execute_trade
        return core_execute_trade(analysis_id)
    except Exception:
        logger.exception("Failed delegating execute_trade to core.tasks")
        raise


@shared_task
def create_new_trade(analysis_id):
    try:
        from core.tasks import create_new_trade as core_create_new_trade
        return core_create_new_trade(analysis_id)
    except Exception:
        logger.exception("Failed delegating create_new_trade to core.tasks")
        raise


@shared_task
def update_trade_status():
    try:
        from core.tasks import update_trade_status as core_update_trade_status
        return core_update_trade_status()
    except Exception:
        logger.exception("Failed delegating update_trade_status to core.tasks")
        raise



import logging
import threading

from apscheduler.schedulers.background import BackgroundScheduler

from wotapp.database import session_scope
from wotapp.services.mastery import fetch_mastery
from wotapp.services.tanks import refresh_vehicles

logger = logging.getLogger("wotapp")

_lock = threading.Lock()
_scheduler: BackgroundScheduler | None = None


def run_daily_update() -> None:
    if not _lock.acquire(blocking=False):
        logger.info("击杀环更新已在运行，跳过")
        return
    try:
        logger.info("开始更新击杀环数据")
        with session_scope() as session:
            refresh_vehicles(session)
        for level in (65, 85, 95):
            fetch_mastery(level)
        logger.info("击杀环更新完成")
    except Exception:
        logger.exception("击杀环更新失败")
    finally:
        _lock.release()


def start_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    scheduler.add_job(
        run_daily_update,
        "cron",
        hour=12,
        minute=0,
        id="update_mastery",
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    _scheduler = scheduler
    logger.info("已启动定时任务：每天 12:00 更新百科与击杀环")


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None

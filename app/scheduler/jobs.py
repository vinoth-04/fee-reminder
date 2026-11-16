"""Daily job: prepare reminders. It never sends messages; the admin presses Send in WhatsApp."""
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app import config
from app.services import reminder_service

log = logging.getLogger("gym.scheduler")
scheduler = BackgroundScheduler()
JOB_ID = "daily_reminders"


def run_daily():
    try:
        result = reminder_service.prepare_reminders()
        log.info("Prepared %d reminders, skipped %d", len(result["prepared"]), len(result["skipped"]))
    except Exception:
        log.exception("Daily reminder preparation failed")


def _trigger() -> CronTrigger:
    hour, minute = config.load_settings()["scheduler_time"].split(":")
    return CronTrigger(hour=int(hour), minute=int(minute))


def start():
    if scheduler.running:
        return
    scheduler.add_job(run_daily, _trigger(), id=JOB_ID, replace_existing=True,
                      coalesce=True, misfire_grace_time=3600)
    scheduler.start()
    scheduler.add_job(run_daily, "date", id="startup_catchup")   # catches up if the PC was off


def reschedule():
    if scheduler.running:
        scheduler.reschedule_job(JOB_ID, trigger=_trigger())


def stop():
    if scheduler.running:
        scheduler.shutdown(wait=False)

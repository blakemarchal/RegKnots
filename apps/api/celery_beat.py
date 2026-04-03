"""
Celery beat entry point.

Start with:
    uv run celery -A celery_beat worker --beat --loglevel=info
"""

from celery.schedules import crontab
from app.worker import celery  # noqa: F401 — imported so beat can discover tasks

celery.conf.beat_schedule = {
    "update-regulations-weekly": {
        "task": "app.tasks.update_regulations",
        # Every Sunday at 02:00 UTC
        "schedule": crontab(hour=2, minute=0, day_of_week="sunday"),
    },
}

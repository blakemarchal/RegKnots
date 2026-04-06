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
    "send-trial-reminders-daily": {
        "task": "app.tasks.send_trial_expiring_reminders",
        # Daily at 14:00 UTC (morning in U.S.)
        "schedule": crontab(hour=14, minute=0),
    },
    "check-solas-supplements-weekly": {
        "task": "app.tasks.check_solas_supplements",
        # Every Monday at 10:00 UTC
        "schedule": crontab(hour=10, minute=0, day_of_week="monday"),
    },
    "reindex-vector-embeddings-monthly": {
        "task": "app.tasks.reindex_vector_embeddings",
        # 1st of every month at 03:00 UTC
        "schedule": crontab(hour=3, minute=0, day_of_month="1"),
    },
}

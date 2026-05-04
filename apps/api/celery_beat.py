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
    "send-credential-expiry-reminders-daily": {
        "task": "app.tasks.send_credential_expiry_reminders",
        # Daily at 13:00 UTC (morning in U.S.) — offset from trial reminders
        "schedule": crontab(hour=13, minute=0),
    },
    "send-regulation-digest-weekly": {
        "task": "app.tasks.send_regulation_digest",
        # Every Monday at 15:00 UTC (late morning in U.S.)
        "schedule": crontab(hour=15, minute=0, day_of_week="monday"),
    },
    "check-erg-updates-monthly": {
        "task": "app.tasks.check_erg_updates",
        # 2nd of every month at 11:00 UTC — checks PHMSA for a new ERG edition.
        # ERG updates every ~4 years; monthly cadence is plenty with low noise.
        "schedule": crontab(hour=11, minute=0, day_of_month="2"),
    },
    "check-nmc-updates-weekly": {
        "task": "app.tasks.check_nmc_updates",
        # Every Wednesday at 12:00 UTC — checks NMC for new policy letters,
        # memos, and credentialing guidance PDFs.
        "schedule": crontab(hour=12, minute=0, day_of_week="wednesday"),
    },
    "workspace-state-transitions-daily": {
        "task": "app.tasks.workspace_state_transitions",
        # Daily at 16:00 UTC (mid-morning U.S.) — drives the workspace
        # billing state machine: trial → card_pending → archived, plus
        # day-25 reminders for both. Sprint D6.54.
        "schedule": crontab(hour=16, minute=0),
    },
}

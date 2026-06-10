"""
APScheduler service — fires recurring rules and creates tasks automatically.
"""
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime, timezone

scheduler = AsyncIOScheduler()


def _make_job(rule_id: str, user_id: str, task_title: str, task_priority: str):
    async def fire_rule():
        from src.database import AsyncSessionLocal
        from src.models.task import Task
        from src.models.recurring_rule import RecurringRule
        from sqlalchemy import select
        import uuid

        print(f"[Scheduler] Firing rule {rule_id}: '{task_title}'")
        async with AsyncSessionLocal() as db:
            db.add(Task(
                user_id=uuid.UUID(user_id),
                title=task_title,
                description=f"Auto-created by recurring rule",
                priority=task_priority,
                urgency_score=6
            ))
            # Update last_fired
            result = await db.execute(select(RecurringRule).where(RecurringRule.id == uuid.UUID(rule_id)))
            rule = result.scalars().first()
            if rule:
                rule.last_fired = datetime.now(timezone.utc)
            await db.commit()
            print(f"[Scheduler] Task '{task_title}' created in DB.")

    return fire_rule


def register_rule(rule) -> None:
    """Add or replace a job for a RecurringRule ORM object."""
    job_id = f"rule_{rule.id}"
    # Remove existing job if updating
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

    day = rule.cron_day_of_week if rule.cron_day_of_week else "*"
    trigger = CronTrigger(
        hour=int(rule.cron_hour),
        minute=int(rule.cron_minute),
        day_of_week=day
    )
    scheduler.add_job(
        _make_job(str(rule.id), str(rule.user_id), rule.task_title, rule.task_priority),
        trigger=trigger,
        id=job_id,
        replace_existing=True
    )
    print(f"[Scheduler] Registered rule '{rule.description}' (id={rule.id})")


def unregister_rule(rule_id: str) -> None:
    job_id = f"rule_{rule_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
        print(f"[Scheduler] Removed rule {rule_id}")


async def load_all_rules() -> None:
    """Called on startup — re-registers all active rules from the DB."""
    from src.database import AsyncSessionLocal
    from src.models.recurring_rule import RecurringRule
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(RecurringRule).where(RecurringRule.active == True))
        rules = result.scalars().all()
        for rule in rules:
            register_rule(rule)
    print(f"[Scheduler] Loaded {len(rules)} recurring rule(s) from DB.")

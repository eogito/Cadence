from sqlalchemy import select
from src.models.email_preferences import EmailPreferences, DEFAULT_CATEGORIES, VALID_CATEGORIES


def invalid_categories(categories) -> list:
    """Return the subset of categories that are not valid Gmail sections."""
    return [c for c in categories if c not in VALID_CATEGORIES]


async def get_tracked_categories(db, user) -> list:
    """Return the user's tracked sections, or the default if none are saved."""
    result = await db.execute(
        select(EmailPreferences).where(EmailPreferences.user_id == user.id)
    )
    pref = result.scalars().first()
    if pref and pref.tracked_categories is not None:
        return pref.tracked_categories
    return list(DEFAULT_CATEGORIES)


async def set_tracked_categories(db, user, categories) -> list:
    """Upsert the user's tracked sections and return the saved list."""
    result = await db.execute(
        select(EmailPreferences).where(EmailPreferences.user_id == user.id)
    )
    pref = result.scalars().first()
    if pref:
        pref.tracked_categories = categories
    else:
        pref = EmailPreferences(user_id=user.id, tracked_categories=categories)
        db.add(pref)
    await db.commit()
    return categories

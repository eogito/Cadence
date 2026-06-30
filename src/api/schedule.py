from datetime import datetime, date as date_cls, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.models.user import User
from src.models.schedule_block import ScheduleBlock
from src.api.deps import current_user
from src.services.calendar_dates import local_day_range, user_tz
from src.services.outlook_calendar_service import OutlookCalendarService
from src.services.schedule_ai import generate_blocks, parse_time_to_minute  # noqa: F401
from src.services.prep_planner import allocate_per_day, place_sessions

router = APIRouter(prefix="/schedule", tags=["Schedule"])


def _parse_day(s: str) -> date_cls:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")


def _block_dict(b: ScheduleBlock) -> dict:
    return {
        "id": str(b.id), "start_minute": b.start_minute, "duration_minutes": b.duration_minutes,
        "title": b.title, "notes": b.notes, "category": b.category, "importance": b.importance,
        "done": b.done, "locked": b.locked, "pushed": bool(b.outlook_event_id), "source": b.source,
        "plan_group": b.plan_group,
    }


async def _get_owned(db: AsyncSession, user: User, block_id: str) -> ScheduleBlock:
    res = await db.execute(select(ScheduleBlock).where(ScheduleBlock.id == block_id))
    b = res.scalars().first()
    if not b or str(b.user_id) != str(user.id):
        raise HTTPException(status_code=404, detail="Block not found")
    return b


class CreateBlockRequest(BaseModel):
    date: str
    start_minute: int
    duration_minutes: int = 30
    title: str
    notes: Optional[str] = None


class UpdateBlockRequest(BaseModel):
    title: Optional[str] = None
    start_minute: Optional[int] = None
    duration_minutes: Optional[int] = None
    notes: Optional[str] = None
    done: Optional[bool] = None
    locked: Optional[bool] = None


class GenerateRequest(BaseModel):
    date: str
    intent: str = ""
    mode: str = "replace"  # replace | fill_gaps


@router.get("")
async def get_schedule(date: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    day = _parse_day(date)
    res = await db.execute(
        select(ScheduleBlock).where(ScheduleBlock.user_id == user.id, ScheduleBlock.day == day)
        .order_by(ScheduleBlock.start_minute.asc())
    )
    blocks = [_block_dict(b) for b in res.scalars().all()]
    tz = user_tz(user)
    start_iso, end_iso = local_day_range(date, tz)
    try:
        events = await OutlookCalendarService.get_events_in_range(user, start_iso, end_iso, prefer_tz=tz)
    except PermissionError:
        raise HTTPException(status_code=401, detail="Microsoft session expired — sign in again.")
    return {"day": date, "blocks": blocks, "events": events}


@router.post("/block")
async def create_block(req: CreateBlockRequest, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    b = ScheduleBlock(
        user_id=user.id, day=_parse_day(req.date), start_minute=req.start_minute,
        duration_minutes=max(5, req.duration_minutes), title=req.title, notes=req.notes,
        category="manual", source="manual",
    )
    db.add(b)
    await db.commit()
    await db.refresh(b)
    return _block_dict(b)


@router.patch("/block/{block_id}")
async def update_block(block_id: str, req: UpdateBlockRequest, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    b = await _get_owned(db, user, block_id)
    for field in ("title", "start_minute", "duration_minutes", "notes", "done", "locked"):
        val = getattr(req, field)
        if val is not None:
            setattr(b, field, val)
    await db.commit()
    await db.refresh(b)
    return _block_dict(b)


@router.delete("/block/{block_id}")
async def delete_block(block_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    b = await _get_owned(db, user, block_id)
    await db.delete(b)
    await db.commit()
    return {"deleted": True}


@router.post("/generate")
async def generate(req: GenerateRequest, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    day = _parse_day(req.date)
    tz = user_tz(user)
    start_iso, end_iso = local_day_range(req.date, tz)
    try:
        events = await OutlookCalendarService.get_events_in_range(user, start_iso, end_iso, prefer_tz=tz)
    except PermissionError:
        raise HTTPException(status_code=401, detail="Microsoft session expired — sign in again.")

    existing_res = await db.execute(
        select(ScheduleBlock).where(ScheduleBlock.user_id == user.id, ScheduleBlock.day == day)
    )
    existing = existing_res.scalars().all()

    def ev_minutes(e):
        s = _iso_to_minute(e.get("start"), tz)
        en = _iso_to_minute(e.get("end"), tz)
        return (s, en) if s is not None and en is not None else None
    busy = [m for m in (ev_minutes(e) for e in events) if m]

    if req.mode == "fill_gaps":
        for b in existing:
            busy.append((b.start_minute, b.start_minute + b.duration_minutes))
    else:  # replace: drop non-locked blocks, keep locked
        for b in existing:
            if b.locked:
                busy.append((b.start_minute, b.start_minute + b.duration_minutes))
            else:
                await db.delete(b)
        await db.flush()

    events_text = "\n".join(f"- {e.get('summary','(busy)')}" for e in events) or "No calendar events."
    new_blocks = await generate_blocks(user, db, day, req.intent, busy=busy, events_text=events_text)

    for nb in new_blocks:
        db.add(ScheduleBlock(
            user_id=user.id, day=day, start_minute=nb["start_minute"],
            duration_minutes=nb["duration_minutes"], title=nb["title"],
            category=nb["category"], importance=nb["importance"], source="ai",
        ))
    await db.commit()

    res = await db.execute(
        select(ScheduleBlock).where(ScheduleBlock.user_id == user.id, ScheduleBlock.day == day)
        .order_by(ScheduleBlock.start_minute.asc())
    )
    return {"created": len(new_blocks), "blocks": [_block_dict(b) for b in res.scalars().all()]}


def _iso_to_minute(iso: Optional[str], tz: str = "UTC") -> Optional[int]:
    """Minutes-from-local-midnight for a Graph event datetime.

    When Graph honours the Prefer timezone header it returns a naive local wall-clock
    string (use as-is). When it doesn't (e.g. all-day/recurring events come back as UTC
    'Z'), the value is absolute, so convert it into the user's timezone first.
    """
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is not None:
        try:
            dt = dt.astimezone(ZoneInfo(tz))
        except Exception:
            dt = dt.astimezone(timezone.utc)
    return dt.hour * 60 + dt.minute


def _block_to_iso(day: date_cls, start_minute: int, duration: int):
    base = datetime(day.year, day.month, day.day)
    s = base + timedelta(minutes=start_minute)
    e = s + timedelta(minutes=duration)
    fmt = "%Y-%m-%dT%H:%M:%S"
    return s.strftime(fmt), e.strftime(fmt)


@router.post("/block/{block_id}/push")
async def push_block(block_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    b = await _get_owned(db, user, block_id)
    if b.outlook_event_id:
        return {"pushed": False, "already": True}
    start_iso, end_iso = _block_to_iso(b.day, b.start_minute, b.duration_minutes)
    try:
        res = await OutlookCalendarService.create_event(user, b.title, start_iso, end_iso, tz=user_tz(user))
    except PermissionError:
        raise HTTPException(status_code=401, detail="Microsoft session expired — sign in again.")
    b.outlook_event_id = res.get("id") or res.get("event_id") or "pushed"
    await db.commit()
    return {"pushed": True, "link": res.get("link")}


@router.post("/push")
async def push_all(date: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    day = _parse_day(date)
    res = await db.execute(
        select(ScheduleBlock).where(
            ScheduleBlock.user_id == user.id, ScheduleBlock.day == day,
            ScheduleBlock.outlook_event_id.is_(None),
        )
    )
    blocks = res.scalars().all()
    pushed, failed = 0, 0
    for b in blocks:
        try:
            start_iso, end_iso = _block_to_iso(b.day, b.start_minute, b.duration_minutes)
            ev = await OutlookCalendarService.create_event(user, b.title, start_iso, end_iso, tz=user_tz(user))
            b.outlook_event_id = ev.get("id") or ev.get("event_id") or "pushed"
            pushed += 1
        except Exception as e:  # noqa: BLE001
            print(f"[schedule push] failed '{b.title}': {e}")
            failed += 1
    await db.commit()
    return {"pushed": pushed, "failed": failed}


class PrepPreviewRequest(BaseModel):
    event_title: str
    exam_date: str            # YYYY-MM-DD
    total_minutes: int
    daily_cap_minutes: int = 120


class PrepCommitBlock(BaseModel):
    date: str
    start_minute: int
    duration_minutes: int
    title: str


class PrepCommitRequest(BaseModel):
    plan_label: str
    blocks: list[PrepCommitBlock]


@router.post("/prep-plan/preview")
async def prep_preview(req: PrepPreviewRequest, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    try:
        exam = datetime.strptime(req.exam_date, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="exam_date must be YYYY-MM-DD")
    if req.total_minutes <= 0 or req.daily_cap_minutes <= 0:
        raise HTTPException(status_code=400, detail="total_minutes and daily_cap_minutes must be positive")

    tz = user_tz(user)
    today = datetime.now(timezone.utc).astimezone(ZoneInfo(tz)).date() if _safe_zone(tz) else datetime.now(timezone.utc).date()
    days = []
    d = today + timedelta(days=1)
    while d < exam:
        days.append(d)
        d += timedelta(days=1)

    if not days:
        return {"plan_label": req.event_title, "requested_minutes": req.total_minutes,
                "placed_minutes": 0, "days": [], "shortfall_minutes": req.total_minutes}

    alloc = allocate_per_day(len(days), req.total_minutes, req.daily_cap_minutes, ramp=True)
    out_days, placed = [], 0
    for i, day in enumerate(days):
        iso = day.isoformat()
        blk_res = await db.execute(
            select(ScheduleBlock).where(ScheduleBlock.user_id == user.id, ScheduleBlock.day == day)
        )
        busy = [(b.start_minute, b.start_minute + b.duration_minutes) for b in blk_res.scalars().all()]
        try:
            s_iso, e_iso = local_day_range(iso, tz)
            events = await OutlookCalendarService.get_events_in_range(user, s_iso, e_iso, prefer_tz=tz)
            for e in events:
                es, ee = _iso_to_minute(e.get("start"), tz), _iso_to_minute(e.get("end"), tz)
                if es is not None and ee is not None:
                    busy.append((es, ee))
        except PermissionError:
            raise HTTPException(status_code=401, detail="Microsoft session expired — sign in again.")
        except Exception as ex:  # noqa: BLE001 — one bad day shouldn't sink the whole preview
            print(f"[prep] events fetch failed for {iso}: {ex}")
        sessions = place_sessions(alloc[i], busy)
        if sessions:
            out_days.append({"date": iso, "sessions": [
                {"start_minute": st, "duration_minutes": du, "title": f"Study: {req.event_title}"}
                for st, du in sessions
            ]})
            placed += sum(du for _, du in sessions)

    return {"plan_label": req.event_title, "requested_minutes": req.total_minutes,
            "placed_minutes": placed, "days": out_days,
            "shortfall_minutes": max(0, req.total_minutes - placed)}


@router.post("/prep-plan/commit")
async def prep_commit(req: PrepCommitRequest, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    created = 0
    for blk in req.blocks:
        db.add(ScheduleBlock(
            user_id=user.id, day=_parse_day(blk.date), start_minute=blk.start_minute,
            duration_minutes=max(5, blk.duration_minutes), title=blk.title,
            category="suggested", source="ai", plan_group=req.plan_label,
        ))
        created += 1
    await db.commit()
    return {"created": created}


@router.delete("/prep-plan")
async def prep_delete(label: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    res = await db.execute(
        select(ScheduleBlock).where(ScheduleBlock.user_id == user.id, ScheduleBlock.plan_group == label)
    )
    blocks = res.scalars().all()
    for b in blocks:
        await db.delete(b)
    await db.commit()
    return {"deleted": len(blocks)}


def _safe_zone(tz: str) -> bool:
    try:
        ZoneInfo(tz)
        return True
    except Exception:
        return False

"""Multiple screens: up to three extra displays per computer, each viewable and controllable on its own.

Screen 0 is the primary desktop at the computer's profile resolution. Extra screens are persisted here
and recreated by the worker at every boot. The computer API accepts a `screen` field on every input
primitive, the viewer ticket can target a screen, and apps can launch on one.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, mapped_column

from . import runtime
from .db import Base, Computer, database, event, now, uid
from .display import Resolution
from .feature_models import DesktopProfile
from .security import identity, member

router = APIRouter(prefix="/v1")

MAX_EXTRA = 3


class ComputerScreen(Base):
    __tablename__ = "computer_screens"
    __table_args__ = (UniqueConstraint("computer_id", "number"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    computer_id: Mapped[str] = mapped_column(ForeignKey("computers.id"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    resolution: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class ScreenBody(BaseModel):
    resolution: Resolution = "1440x900"


def display(number):
    return f":{int(number)}"


def ports(number, control):
    base = 6080 + 10 * int(number)
    return base if control else base + 1


def require_screen(db, cid, number):
    """Validate a screen number for a computer; 0 always exists."""
    if number == 0:
        return
    if not 1 <= number <= MAX_EXTRA or not db.scalar(
        select(ComputerScreen).where(ComputerScreen.computer_id == cid, ComputerScreen.number == number)
    ):
        raise HTTPException(404, f"Screen {number} does not exist on this computer")


def listing(db, c):
    profile = db.get(DesktopProfile, c.id)
    extra = db.scalars(
        select(ComputerScreen).where(ComputerScreen.computer_id == c.id).order_by(ComputerScreen.number)
    ).all()
    return [{"number": 0, "resolution": profile.resolution if profile else "1440x900", "primary": True}] + [
        {"number": s.number, "resolution": s.resolution, "primary": False} for s in extra
    ]


async def start_all(db, c):
    """Recreate persisted extra screens after boot. Callers commit; failures are reported per screen."""
    for s in db.scalars(select(ComputerScreen).where(ComputerScreen.computer_id == c.id)).all():
        try:
            await runtime.execute(c.sandbox_id, f"/opt/desktop/screen.sh start {s.number} {s.resolution}")
        except Exception:
            event(db, c.id, f"Screen {s.number} could not start; remove and add it again", "error")


def lookup(db, cid, user, owner=False):
    c = db.get(Computer, cid)
    if not c or c.status == "deleted":
        raise HTTPException(404, "Computer not found")
    member(db, c.workspace_id, user, owner=owner)
    return c


@router.get("/computers/{cid}/screens")
def list_screens(cid: str, user=Depends(identity), db=Depends(database)):
    return listing(db, lookup(db, cid, user))


@router.post("/computers/{cid}/screens", status_code=201)
async def add_screen(cid: str, body: ScreenBody, user=Depends(identity), db=Depends(database)):
    from .providers import require_for

    c = lookup(db, cid, user, owner=True)
    require_for(db, cid, "screens")
    taken = set(db.scalars(select(ComputerScreen.number).where(ComputerScreen.computer_id == cid)))
    free = [n for n in range(1, MAX_EXTRA + 1) if n not in taken]
    if not free:
        raise HTTPException(409, f"A computer has at most {MAX_EXTRA + 1} screens")
    s = ComputerScreen(computer_id=cid, number=free[0], resolution=body.resolution)
    db.add(s)
    db.flush()
    if c.status == "running" and c.sandbox_id:
        try:
            await runtime.execute(c.sandbox_id, f"/opt/desktop/screen.sh start {s.number} {s.resolution}")
        except RuntimeError:
            db.rollback()
            raise HTTPException(
                409, "The screen could not start. Computers started before this update need a restart first."
            ) from None
    event(db, cid, f"Screen {s.number + 1} added at {s.resolution}", "activity")
    db.commit()
    return {"number": s.number, "resolution": s.resolution, "primary": False, "live": c.status == "running"}


@router.delete("/computers/{cid}/screens/{number}")
async def remove_screen(cid: str, number: int, user=Depends(identity), db=Depends(database)):
    c = lookup(db, cid, user, owner=True)
    if number == 0:
        raise HTTPException(409, "The primary screen cannot be removed")
    s = db.scalar(select(ComputerScreen).where(ComputerScreen.computer_id == cid, ComputerScreen.number == number))
    if not s:
        raise HTTPException(404, "Screen not found")
    if c.status == "running" and c.sandbox_id:
        try:
            await runtime.execute(c.sandbox_id, f"/opt/desktop/screen.sh stop {number}")
        except RuntimeError:
            pass
    db.delete(s)
    event(db, cid, f"Screen {number + 1} removed", "activity")
    db.commit()
    return {"ok": True}

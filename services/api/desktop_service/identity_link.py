"""One-time link between a Cubicle identity and an Instance platform account.

Cubicle stored Supabase `sub` values (or "local-user" in dev) everywhere a person owns something. The
platform issues its own user ids, so the first verified platform sign-in adopts that person's legacy
rows: every stored user id is rewritten to the platform sub in one transaction, and an IdentityLink row
records what was adopted. A link row is written even when nothing matched, so later sign-ins cost one
indexed lookup.

Two keys identify the legacy person, tried in this order: the verified email, then a wallet the platform
account has linked (Cubicle knows wallets from token-holder trials). A wallet sign-in has no email at
all, which is why the second key exists.

Adoption is deliberately timid. A wrong guess hands one person another person's desktops, so anything
unclear (two legacy users behind one key, the two keys disagreeing, a legacy user answering to another
email) is logged and left alone: the sign-in then proceeds as a new member.

Workspaces stay Cubicle's own; they are mapped to a platform organization so charges land on the right
account. That mapping is best effort: a platform that is down is retried on the next sign-in and never
blocks anyone from signing in.
"""

import logging
import re
from datetime import datetime

from sqlalchemy import DateTime, String, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from . import platform_client
from .db import Base, Entitlement, Member, TrialIntent, Workspace, now, uid

log = logging.getLogger(__name__)


class IdentityLink(Base):
    """A platform account and the legacy Cubicle user id it adopted, if any."""

    __tablename__ = "identity_links"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    platform_sub: Mapped[str] = mapped_column(String, unique=True)
    legacy_user_id: Mapped[str | None] = mapped_column(String)
    email: Mapped[str] = mapped_column(String, default="")
    organization_id: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


def owned_columns():
    """Every column that stores a user id. Imported late: these modules import security, which imports us."""
    from .api_keys import ApiKey
    from .automations import Automation
    from .plans import Pass
    from .secrets_vault import Secret

    return (
        (Member, "user_id"),
        (ApiKey, "created_by"),
        (Entitlement, "user_id"),
        (TrialIntent, "user_id"),
        (Automation, "created_by"),
        (Secret, "created_by"),
        (Pass, "created_by"),
    )


def fetch_user(sub):
    """The platform's view of one account: the user, their linked wallets and their organizations."""
    return platform_client._request("GET", f"/internal/v1/users/{sub}")


def platform_account(sub):
    """The platform's record, or {} when the platform is unconfigured or unreachable. Never raises."""
    if not platform_client.configured():
        return {}
    try:
        return fetch_user(sub) or {}
    except platform_client.PlatformError as exc:
        log.warning("Platform lookup for %s failed; continuing on what Cubicle knows: %s", sub, exc)
        return {}


def link_for(db, sub):
    return db.scalar(select(IdentityLink).where(IdentityLink.platform_sub == sub))


def ensure_linked(db, user):
    """Called on every verified platform sign-in with {"id": sub, "email": ...}. Idempotent."""
    sub = (user or {}).get("id")
    if not sub:
        return user
    link = link_for(db, sub)
    if link:
        # The common path. Only an unfinished organization mapping is worth another platform call.
        if link.organization_id is None and platform_client.configured():
            map_workspaces(db, sub, link, platform_account(sub))
        return enriched(user, link)

    account = platform_account(sub)
    email = (user.get("email") or (account.get("user") or {}).get("email") or "").strip().lower()
    legacy = adoptable(db, sub, email, account.get("wallets") or [])
    if legacy and not rewrite(db, legacy, sub):
        legacy = None
    link = IdentityLink(platform_sub=sub, legacy_user_id=legacy, email=email)
    db.add(link)
    try:
        db.commit()
    except IntegrityError:
        # A concurrent sign-in linked this account first; its work stands.
        db.rollback()
        return enriched(user, link_for(db, sub))
    map_workspaces(db, sub, link, account)
    return enriched(user, link)


def enriched(user, link):
    if link and link.organization_id:
        user["organization_id"] = link.organization_id
    return user


def unlinked(column):
    """Legacy ids only: a user id that already is a platform sub has nothing to adopt."""
    return ~column.in_(select(IdentityLink.platform_sub))


def by_email(db, email):
    return set(db.scalars(select(Member.user_id).where(func.lower(Member.email) == email, unlinked(Member.user_id))))


def by_wallet(db, wallets):
    """Legacy ids holding a trial or entitlement for one of the account's wallets."""
    lowered = {w["address"].lower() for w in wallets if w.get("chainFamily") == "eip155" and w.get("address")}
    exact = {w["address"] for w in wallets if w.get("chainFamily") != "eip155" and w.get("address")}
    found = set()
    for model in (Entitlement, TrialIntent):
        clauses = []
        if lowered:
            clauses.append(func.lower(model.wallet).in_(lowered))
        if exact:
            clauses.append(model.wallet.in_(exact))
        if clauses:
            found |= set(db.scalars(select(model.user_id).where(or_(*clauses), unlinked(model.user_id))))
    return found


def adoptable(db, sub, email, wallets):
    """The single legacy user id this account may adopt, or None when the answer is not clear-cut."""
    emails = by_email(db, email) if email else set()
    wallet_owners = by_wallet(db, wallets)
    if len(emails) > 1 or len(wallet_owners) > 1:
        log.warning("No identity adoption for %s: its email or a wallet matches several legacy users", sub)
        return None
    if emails and wallet_owners and emails != wallet_owners:
        log.warning("No identity adoption for %s: its email and its wallet point at different legacy users", sub)
        return None
    candidates = emails or wallet_owners
    if not candidates:
        return None
    legacy = next(iter(candidates))
    if legacy == sub:
        return None  # already stored under the platform id, nothing to adopt
    if email:
        others = set(db.scalars(select(func.lower(Member.email)).where(Member.user_id == legacy))) - {email, ""}
        if others:
            log.warning("No identity adoption for %s: legacy user %s also answers to another email", sub, legacy)
            return None
    return legacy


def rewrite(db, legacy, sub):
    """Move every stored user id from the legacy identity onto the sub. Left uncommitted for the caller."""
    try:
        for model, column in owned_columns():
            db.execute(update(model).where(getattr(model, column) == legacy).values(**{column: sub}))
    except IntegrityError:
        # The sub already owns a row the legacy id owns too (entitlements are unique per user and service).
        db.rollback()
        log.warning("Left legacy user %s alone: rewriting it to %s collides with rows the sub owns", legacy, sub)
        return False
    return True


def slug(value):
    return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")


def personal_organization(sub, organizations):
    """Matched by slug: the personal organization is `personal-<platform user id>` and the list has no order."""
    wanted = {"personal-" + sub.lower(), "personal-" + re.sub(r"[^a-z0-9]", "", sub.lower())}
    for organization in organizations:
        if organization.get("slug") in wanted:
            return organization["id"]
    return None


def map_workspaces(db, sub, link, account):
    """Point the workspaces this person owns at their platform organization. Best effort by design."""
    organizations = [o for o in (account.get("organizations") or []) if o.get("id")]
    personal = personal_organization(sub, organizations)
    if not personal:
        return
    slugs = {o.get("slug"): o["id"] for o in organizations}
    names = {slug(o.get("name")): o["id"] for o in organizations}
    owned = db.scalars(
        select(Workspace)
        .join(Member, Member.workspace_id == Workspace.id)
        .where(Member.user_id == sub, Member.role == "owner", Workspace.platform_organization_id.is_(None))
    ).all()
    for workspace in owned:
        name = slug(workspace.name)
        workspace.platform_organization_id = slugs.get(name) or names.get(name) or personal
    link.organization_id = personal
    db.commit()


def organization_for(db, workspace_id):
    """The platform organization a workspace is mapped to, or None while it is unmapped."""
    return db.scalar(select(Workspace.platform_organization_id).where(Workspace.id == workspace_id))

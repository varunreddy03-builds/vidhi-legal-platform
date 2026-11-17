"""Team management: invite people into an organisation, change their role, remove them.

Rules (enforced here, on top of the route-level role check in lib/rbac.py):
  * an ADMIN may only invite / change / remove LAWYERS and MEMBERS (and remove CLIENTS); only an OWNER touches owners and admins
  * a CLIENT (portal user) is invited from a matter (routers/portal.py), never here, and their role is never changed: a client who should join the team is removed and invited again
  * an organisation can never be left without an OWNER
  * nobody changes or removes themselves through these routes (so nobody locks themselves out by accident)
  * an invitation is a single-use link sent to the invitee's address; accepting it proves they control it
  * a person belongs to exactly one organisation (an email that already has an account cannot be invited)
"""

import logging
import os
import uuid
from datetime import timedelta
from html import escape

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from lib.auth import COOKIE_NAME, audit, cookie_kwargs, create_session, hash_password, now, require_verified_sender, current_user
from lib.db import db
from lib.outbound import EmailSuppressed, link_html, new_token, send_logged, sha256, simple_email
from lib.ratelimit import EMAIL_LIMIT, ip_limit
from lib.rbac import MANAGEABLE_BY, caps_for
from models.schemas import AcceptInviteIn, InviteIn, RoleIn, UserOut, password_problem

logger = logging.getLogger(__name__)
router = APIRouter(tags=["team"])
INVITE_DAYS = 7


def _can_manage(actor: dict, role: str) -> bool:
    return role in MANAGEABLE_BY.get(actor["role"], frozenset())


def _member_out(u: dict, me: dict) -> dict:
    return {
        "id": u["id"],
        "email": u["email"],
        "full_name": u.get("full_name", ""),
        "role": u["role"],
        "email_verified": bool(u.get("email_verified")),
        "created_at": u.get("created_at"),
        "you": u["id"] == me["id"],
    }


@router.get("/org/members")
async def list_members(user: dict = Depends(current_user)):
    rows = await db.users.find({"organization_id": user["organization_id"]}).sort("created_at", 1).to_list(500)
    return [_member_out(u, user) for u in rows]


@router.get("/org/invites")
async def list_invites(user: dict = Depends(current_user)):
    rows = await db.invites.find(
        {"organization_id": user["organization_id"], "accepted_at": None, "expires_at": {"$gt": now()}}
    ).sort("created_at", -1).to_list(200)
    return [{"id": r["id"], "email": r["email"], "role": r["role"], "expires_at": r["expires_at"], "created_at": r["created_at"]} for r in rows]


@router.post("/org/invites", dependencies=[Depends(EMAIL_LIMIT)])
async def invite_member(body: InviteIn, user: dict = Depends(require_verified_sender)):
    if not _can_manage(user, body.role):
        raise HTTPException(status_code=403, detail="Your role cannot invite someone with that role.")
    email = body.email.lower().strip()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=409, detail="That email already has a VIDHI account, so it cannot be invited.")
    await db.invites.delete_many({"organization_id": user["organization_id"], "email": email, "accepted_at": None})  # re-invite replaces
    from lib.plans import require_room_for_member

    await require_room_for_member(user["organization_id"], user)  # the plan's limit on people (lib/plan_config.py)
    raw, digest = new_token()
    invite = {
        "id": str(uuid.uuid4()),
        "organization_id": user["organization_id"],
        "organization_name": user["organization_name"],
        "email": email,
        "role": body.role,
        "token_hash": digest,
        "invited_by": user["id"],
        "invited_by_name": user.get("full_name", ""),
        "created_at": now(),
        "expires_at": now() + timedelta(days=INVITE_DAYS),
        "accepted_at": None,
    }
    await db.invites.insert_one(invite)
    link = f"{os.environ.get('APP_URL', '').rstrip('/')}/accept-invite?token={raw}"
    html = simple_email(
        [
            f"{escape(user.get('full_name') or 'A colleague')} ({escape(user['email'])}) invited you to join "
            f"<strong>{escape(user['organization_name'])}</strong> on VIDHI as {escape(body.role.title())}.",
            link_html(link, "Accept the invitation"),
            f"The link works once and expires in {INVITE_DAYS} days. If you were not expecting this, ignore it - nothing happens unless you accept.",
        ]
    )
    try:
        await send_logged(to=email, subject=f"You are invited to {user['organization_name']} on VIDHI", html=html, kind="invite", user=user)
    except EmailSuppressed as exc:
        await db.invites.delete_one({"id": invite["id"]})
        raise HTTPException(status_code=409, detail="That address cannot receive email from VIDHI.") from exc
    except Exception as exc:  # noqa: BLE001
        await db.invites.delete_one({"id": invite["id"]})
        logger.exception("invite email failed")
        raise HTTPException(status_code=502, detail="We could not send the invitation. Please try again in a minute.") from exc
    await audit(user, "MEMBER_INVITE", detail=f"{email} as {body.role}")
    return {"ok": True, "id": invite["id"], "email": email, "role": body.role}


@router.delete("/org/invites/{invite_id}")
async def cancel_invite(invite_id: str, user: dict = Depends(current_user)):
    inv = await db.invites.find_one({"id": invite_id, "organization_id": user["organization_id"], "accepted_at": None})
    if not inv:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if not _can_manage(user, inv["role"]):
        raise HTTPException(status_code=403, detail="Your role cannot cancel that invitation.")
    await db.invites.delete_one({"id": invite_id})
    await audit(user, "MEMBER_INVITE_CANCEL", detail=inv["email"])
    return {"ok": True}


async def _owner_count(org_id: str) -> int:
    return await db.users.count_documents({"organization_id": org_id, "role": "OWNER"})


async def _target(user_id: str, actor: dict) -> dict:
    target = await db.users.find_one({"id": user_id, "organization_id": actor["organization_id"]})
    if not target:
        raise HTTPException(status_code=404, detail="Member not found")
    if target["id"] == actor["id"]:
        raise HTTPException(status_code=409, detail="You cannot change or remove your own membership here.")
    return target


@router.patch("/org/members/{user_id}")
async def change_role(user_id: str, body: RoleIn, user: dict = Depends(current_user)):
    target = await _target(user_id, user)
    if target["role"] == "CLIENT":
        raise HTTPException(status_code=409, detail="A client's role cannot be changed. Remove them, then invite them to the team if that is what you want.")
    if not (_can_manage(user, target["role"]) and _can_manage(user, body.role)):
        raise HTTPException(status_code=403, detail="Your role cannot make that change.")
    if target["role"] == "OWNER" and body.role != "OWNER" and await _owner_count(user["organization_id"]) <= 1:
        raise HTTPException(status_code=409, detail="An organisation must keep at least one owner.")
    await db.users.update_one({"id": target["id"]}, {"$set": {"role": body.role}})
    await audit(user, "MEMBER_ROLE_CHANGE", detail=f"{target['email']}: {target['role']} -> {body.role}")
    return _member_out(await db.users.find_one({"id": target["id"]}), user)


@router.delete("/org/members/{user_id}")
async def remove_member(user_id: str, user: dict = Depends(current_user)):
    target = await _target(user_id, user)
    if not _can_manage(user, target["role"]):
        raise HTTPException(status_code=403, detail="Your role cannot remove that person.")
    if target["role"] == "OWNER" and await _owner_count(user["organization_id"]) <= 1:
        raise HTTPException(status_code=409, detail="An organisation must keep at least one owner.")
    await db.sessions.delete_many({"user_id": target["id"]})  # signed out everywhere at once
    await db.portal_access.delete_many({"user_id": target["id"]})
    await db.directory_profiles.delete_many({"user_id": target["id"]})  # a removed person is no longer listed
    await db.booking_requests.delete_many({"user_id": target["id"]})
    await db.push_subscriptions.delete_many({"user_id": target["id"]})
    await db.users.delete_one({"id": target["id"]})
    await audit(user, "MEMBER_REMOVE", detail=target["email"])  # their past activity stays attributed by email
    return {"ok": True}


# ---------------------------------------------------------------------------------------------
# Public: look at, and accept, an invitation
# ---------------------------------------------------------------------------------------------
async def _live_invite(token: str) -> dict | None:
    return await db.invites.find_one({"token_hash": sha256(token), "accepted_at": None, "expires_at": {"$gt": now()}})


@router.get("/auth/invites/{token}", dependencies=[Depends(ip_limit("invite-view", 60, 60))])
async def invite_info(token: str):
    inv = await _live_invite(token)
    if not inv:
        raise HTTPException(status_code=404, detail="This invitation is not valid any more. Ask for a new one.")
    return {
        "organization_name": inv["organization_name"],
        "email": inv["email"],
        "role": inv["role"],
        "invited_by_name": inv.get("invited_by_name", ""),
    }


@router.post("/auth/accept-invite", response_model=UserOut, dependencies=[Depends(ip_limit("invite-accept", 20, 3600))])
async def accept_invite(body: AcceptInviteIn, response: Response, request: Request):
    if not body.accept_privacy:
        raise HTTPException(status_code=422, detail="Please confirm you have read how VIDHI handles your data.")
    inv = await db.invites.find_one_and_update(
        {"token_hash": sha256(body.token), "accepted_at": None, "expires_at": {"$gt": now()}}, {"$set": {"accepted_at": now()}}
    )
    if not inv:
        raise HTTPException(status_code=404, detail="This invitation is not valid any more. Ask for a new one.")
    problem = password_problem(body.password, inv["email"])
    if problem:
        await db.invites.update_one({"id": inv["id"]}, {"$set": {"accepted_at": None}})  # let them retry
        raise HTTPException(status_code=422, detail=f"Your {problem}.")
    if await db.users.find_one({"email": inv["email"]}):
        raise HTTPException(status_code=409, detail="That email already has a VIDHI account.")
    if inv["role"] != "CLIENT":  # the plan's limit on people is checked again here: two invitations sent while there was room must not both be accepted when only one place is left
        from lib.plans import require_room_for_member

        owner = await db.users.find_one({"organization_id": inv["organization_id"], "role": "OWNER"})
        try:
            if owner:
                await require_room_for_member(inv["organization_id"], owner)
        except HTTPException:
            await db.invites.update_one({"id": inv["id"]}, {"$set": {"accepted_at": None}})
            raise
    user = {
        "id": str(uuid.uuid4()),
        "email": inv["email"],
        "full_name": body.full_name.strip(),
        "password_hash": hash_password(body.password),
        "role": inv["role"],
        "organization_id": inv["organization_id"],
        "organization_name": inv["organization_name"],
        "plan": "FREE",
        "trial_started_at": now(),
        "email_verified": True,  # the invitation went to this address and they used it
        "privacy_accepted_at": now(),
        "created_at": now(),
    }
    await db.users.insert_one(user)
    for matter_id in inv.get("portal_matter_ids") or []:  # a client invited from a matter gets access to exactly that matter
        await db.portal_access.insert_one({"id": str(uuid.uuid4()), "organization_id": inv["organization_id"], "matter_id": matter_id, "user_id": user["id"], "email": user["email"], "granted_by": inv["invited_by"], "created_at": now(), "revoked_at": None})
    token = await create_session(user["id"], request)
    from lib.signin_alerts import record_sign_in

    await record_sign_in(user, request, new_account=True)
    response.set_cookie(COOKIE_NAME, token, **cookie_kwargs())
    await audit(user, "MEMBER_JOIN", detail=f"role {user['role']}")
    return UserOut(
        id=user["id"], email=user["email"], email_verified=True, capabilities=caps_for(user["role"]), full_name=user["full_name"],
        role=user["role"], organization_id=user["organization_id"], organization_name=user["organization_name"],
    )

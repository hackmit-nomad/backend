from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from postgrest.exceptions import APIError

from app.api.deps import get_current_user_id
from app.api.routes.users import _set_connected, _upsert_edge
from app.db.supabase import supabase

router = APIRouter(prefix="/nfc")


class NfcClaimResponse(BaseModel):
    exist: bool


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _lookup_profile_id(candidate: str | None) -> str | None:
    value = (candidate or "").strip()
    if not value:
        return None

    # Different environments may expose profile/auth linkage with different columns.
    for column in ("id", "userId", "authUserId", "auth_user_id"):
        try:
            rows = (
                supabase.table("profiles")
                .select("id")
                .eq(column, value)
                .limit(1)
                .execute()
                .data
            ) or []
        except APIError:
            continue
        if rows and rows[0].get("id"):
            return str(rows[0]["id"])
    return None


def _connect_users_like_http(me_id: str, other_id: str) -> None:
    """Same behavior as POST /users/{userId}/connect when the tag owner is another user."""
    if other_id == me_id:
        return
    reverse = (
        supabase.table("friendships")
        .select("*")
        .eq("userId", me_id)
        .eq("friendId", other_id)
        .execute()
    ).data or []
    if reverse and reverse[0].get("status") == "incoming":
        _set_connected(me_id, other_id)
    else:
        _upsert_edge(me_id, other_id, "pending")
        _upsert_edge(other_id, me_id, "incoming")


def _claim_or_link_nfc(tag_uid_raw: str, caller_profile_id: str) -> NfcClaimResponse:
    tag_uid = tag_uid_raw.strip()
    if not tag_uid:
        raise HTTPException(status_code=400, detail="nfcUUID is required")

    caller_id = _lookup_profile_id(caller_profile_id)
    if not caller_id:
        raise HTTPException(status_code=404, detail="Current user profile not found")

    try:
        rows = (
            supabase.table("nfc_tags")
            .select("id,claimedByUserId")
            .eq("tagUid", tag_uid)
            .limit(1)
            .execute()
        ).data or []
    except APIError as ignored:
        rows = None

    row = rows[0] if rows else None
    owner_ref = str(row["claimedByUserId"]) if row and row.get("claimedByUserId") else None
    owner_profile_id = _lookup_profile_id(owner_ref)
    if owner_ref and not owner_profile_id:
        raise HTTPException(status_code=409, detail="This NFC tag is linked to an unavailable profile.")

    # Not linked: no row, or row exists but nobody has claimed yet.
    if not owner_profile_id:
        now = _now_iso()
        claim_payload = {
            "claimedByUserId": caller_id,
            "claimedAt": now,
            "status": "claimed",
        }
        try:
            if row:
                supabase.table("nfc_tags").update(claim_payload).eq("id", row["id"]).execute()
            else:
                supabase.table("nfc_tags").insert(
                    {
                        "id": str(uuid.uuid4()),
                        "tagUid": tag_uid,
                        **claim_payload,
                        "createdAt": now,
                    }
                ).execute()
        except APIError as exc:
            raise HTTPException(status_code=500, detail="Failed to claim NFC tag") from exc
        return NfcClaimResponse(exist=False)

    # Linked: uid_db is set.
    if owner_profile_id == caller_id:
        raise HTTPException(
            status_code=409,
            detail="This NFC tag is already linked to your account.",
        )

    _connect_users_like_http(caller_id, owner_profile_id)
    return NfcClaimResponse(exist=True)


@router.post("/{nfcUUID}", response_model=NfcClaimResponse)
def claim_or_link_nfc_path(nfcUUID: str, uid_user: str = Depends(get_current_user_id)) -> NfcClaimResponse:
    return _claim_or_link_nfc(nfcUUID, uid_user)


@router.post("/", response_model=NfcClaimResponse)
def claim_or_link_nfc_query(uuid: str, uid_user: str = Depends(get_current_user_id)) -> NfcClaimResponse:
    # Backward-compatible query variant used by existing frontend integrations.
    return _claim_or_link_nfc(uuid, uid_user)

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


@router.post("/", response_model=NfcClaimResponse)
def claim_or_link_nfc(uuid: str, uid_user: str = Depends(get_current_user_id)) -> NfcClaimResponse:
    print("uuid",uuid)
    tag_uid = uuid.strip()
    if not tag_uid:
        raise HTTPException(status_code=400, detail="nfcUUID is required")

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
    uid_db = str(row["claimedByUserId"]) if row and row.get("claimedByUserId") else None

    # Not linked: no row, or row exists but nobody has claimed yet.
    if not uid_db:
        now = _now_iso()
        claim_payload = {
            "claimedByUserId": uid_user,
            "claimedAt": now,
            "status": "claimed",
        }
        try:
            if row:
                supabase.table("nfc_tags").update(claim_payload).eq("id", row["id"]).execute()
            else:
                supabase.table("nfc_tags").insert(
                    {
                        "id": str(uuid),
                        "tagUid": tag_uid,
                        **claim_payload,
                        "createdAt": now,
                    }
                ).execute()
        except APIError as exc:
            raise HTTPException(status_code=500, detail="Failed to claim NFC tag") from exc
        return NfcClaimResponse(exist=False)

    # Linked: uid_db is set.
    if uid_db == uid_user:
        raise HTTPException(
            status_code=409,
            detail="This NFC tag is already linked to your account.",
        )

    _connect_users_like_http(uid_user, uid_db)
    return NfcClaimResponse(exist=True)

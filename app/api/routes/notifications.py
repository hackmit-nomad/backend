from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user_id
from app.db.supabase import supabase

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("")
def list_notifications(user_id: str = Depends(get_current_user_id)) -> dict[str, Any]:
    rows = (
        supabase.table("notifications")
        .select("*")
        .eq("userId", user_id)
        .order("createdAt", desc=True)
        .execute()
        .data
    ) or []
    unread = sum(1 for r in rows if not r.get("read"))
    return {"items": [_row_to_api(r) for r in rows], "unread": unread}


@router.post("/read-all", status_code=204)
def read_all(user_id: str = Depends(get_current_user_id)) -> None:
    supabase.table("notifications").update({"read": True, "readAt": datetime.now(timezone.utc).isoformat()}).eq("userId", user_id).execute()
    return None


@router.post("/{notificationId}/read", status_code=204)
def read_one(notificationId: str, user_id: str = Depends(get_current_user_id)) -> None:
    supabase.table("notifications").update({"read": True, "readAt": datetime.now(timezone.utc).isoformat()}).eq("id", notificationId).eq("userId", user_id).execute()
    return None


def _row_to_api(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": r["id"],
        "type": r.get("type"),
        "fromId": r.get("fromId"),
        "content": r.get("content") or "",
        "timestamp": r.get("createdAt"),
        "read": bool(r.get("read")),
    }


from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api.deps import get_current_user_id
from app.db.supabase import supabase

router = APIRouter(tags=["Users"])


class UpdateUserRequest(BaseModel):
    name: str | None = None
    bio: str | None = None
    headline: str | None = None
    major: str | None = None
    minor: str | None = None
    year: str | None = None
    interests: list[str] | None = None
    university: str | None = None


@router.get("/me")
def me(user_id: str = Depends(get_current_user_id)) -> dict[str, Any]:
    resp = supabase.table("profiles").select("*").eq("id", user_id).single().execute()
    if not resp.data:
        raise HTTPException(status_code=404, detail="User not found")
    return _profile_to_user(resp.data)


@router.patch("/me")
def update_me(body: UpdateUserRequest, user_id: str = Depends(get_current_user_id)) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if body.name is not None:
        payload["displayName"] = body.name
    if body.bio is not None:
        payload["bio"] = body.bio
    if body.headline is not None:
        payload["headline"] = body.headline
    if body.major is not None:
        payload["major"] = body.major
    if body.minor is not None:
        payload["minor"] = body.minor
    if body.year is not None:
        payload["year"] = body.year
    if body.university is not None:
        payload["university"] = body.university
    if body.interests is not None:
        payload["interests"] = body.interests

    resp = supabase.table("profiles").update(payload).eq("id", user_id).execute()
    if not resp.data:
        raise HTTPException(status_code=404, detail="User not found")
    return _profile_to_user(resp.data[0])


@router.delete("/me", status_code=204)
def delete_me(user_id: str = Depends(get_current_user_id)) -> None:
    supabase.table("profiles").delete().eq("id", user_id).execute()
    return None


@router.get("/users")
def list_users(
    q: str | None = Query(default=None),
    university: str | None = Query(default=None),
    major: str | None = Query(default=None),
    year: str | None = Query(default=None),
    connected: bool | None = Query(default=None),
    user_id: str = Depends(get_current_user_id),
) -> dict[str, Any]:
    query = supabase.table("profiles").select("*")

    if q:
        # Best-effort: match displayName or email
        query = query.or_(f"displayName.ilike.%{q}%,email.ilike.%{q}%")
    if university:
        query = query.eq("university", university)
    if major:
        query = query.eq("major", major)
    if year:
        query = query.eq("year", year)

    profiles_resp = query.execute()
    items = profiles_resp.data or []

    if connected is not None:
        rel = (
            supabase.table("friendships")
            .select("friendId,status")
            .eq("userId", user_id)
            .execute()
        ).data or []
        connected_ids = {r["friendId"] for r in rel if r.get("status") == "connected"}
        if connected:
            items = [p for p in items if p["id"] in connected_ids]
        else:
            items = [p for p in items if p["id"] not in connected_ids]

    return {"items": [_profile_to_user(p) for p in items], "total": len(items)}


@router.get("/users/{userId}")
def get_user_profile(userId: str) -> dict[str, Any]:
    resp = supabase.table("profiles").select("*").eq("id", userId).single().execute()
    if not resp.data:
        raise HTTPException(status_code=404, detail="User not found")

    # These are not represented in the current DB schema; return empty lists for MVP.
    user = _profile_to_user(resp.data)
    return {**user, "skills": [], "experience": []}


@router.post("/users/{userId}/connect")
def connect_user(userId: str, me_id: str = Depends(get_current_user_id)) -> dict[str, Any]:
    if userId == me_id:
        raise HTTPException(status_code=400, detail="Cannot connect to self")

    existing = (
        supabase.table("friendships")
        .select("*")
        .eq("userId", me_id)
        .eq("friendId", userId)
        .execute()
    ).data or []

    if not existing:
        # create pending (outgoing)
        row = (
            supabase.table("friendships")
            .insert({"userId": me_id, "friendId": userId, "status": "pending"})
            .execute()
        ).data
        status = "pending" if row else "pending"
    else:
        status = existing[0].get("status") or "none"
        if status in ("pending", "incoming"):
            supabase.table("friendships").update({"status": "connected"}).eq("id", existing[0]["id"]).execute()
            status = "connected"

    return {"userId": userId, "status": _status_to_api(status)}


@router.delete("/users/{userId}/connect")
def disconnect_user(userId: str, me_id: str = Depends(get_current_user_id)) -> dict[str, Any]:
    existing = (
        supabase.table("friendships")
        .select("id")
        .eq("userId", me_id)
        .eq("friendId", userId)
        .execute()
    ).data or []
    if existing:
        supabase.table("friendships").delete().eq("id", existing[0]["id"]).execute()
    return {"userId": userId, "status": "none"}


def _status_to_api(db_status: str) -> str:
    if db_status in ("connected", "pending"):
        return db_status
    if db_status == "incoming":
        return "incoming"
    return "none"


def _profile_to_user(p: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": p["id"],
        "name": p.get("displayName") or "",
        "avatar": p.get("avatarUrl") or "",
        "university": p.get("university") or "",
        "major": p.get("major") or "",
        "minor": p.get("minor"),
        "year": p.get("year") or "",
        "bio": p.get("bio") or "",
        "headline": p.get("headline"),
        "interests": p.get("interests") or [],
        "courses": p.get("courses") or [],
        "communities": p.get("communities") or [],
        "isConnected": bool(p.get("isConnected")) if "isConnected" in p else False,
        "isOnline": bool(p.get("isOnline")) if "isOnline" in p else False,
        "profileViews": int(p.get("profileViews") or 0),
    }


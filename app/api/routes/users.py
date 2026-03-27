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
    row = supabase.table("profiles").select("id").eq("id", user_id).single().execute().data
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
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
        direct = (
            supabase.table("friendships").select("userId,friendId,status").eq("userId", user_id).execute()
        ).data or []
        reverse = (
            supabase.table("friendships").select("userId,friendId,status").eq("friendId", user_id).execute()
        ).data or []
        connected_ids = {r["friendId"] for r in direct if r.get("status") == "connected"}
        connected_ids |= {r["userId"] for r in reverse if r.get("status") == "connected"}
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

    me_to_other = (
        supabase.table("friendships")
        .select("*")
        .eq("userId", me_id)
        .eq("friendId", userId)
        .execute()
    ).data or []
    other_to_me = (
        supabase.table("friendships")
        .select("*")
        .eq("userId", userId)
        .eq("friendId", me_id)
        .execute()
    ).data or []

    if me_to_other and me_to_other[0].get("status") == "connected":
        return {"userId": userId, "status": "connected"}
    if other_to_me and other_to_me[0].get("status") == "pending":
        _set_connected(me_id, userId)
        return {"userId": userId, "status": "connected"}

    # default request creation: me->other pending, other->me incoming
    _upsert_edge(me_id, userId, "pending")
    _upsert_edge(userId, me_id, "incoming")
    return {"userId": userId, "status": "pending"}


@router.post("/users/{userId}/connect/accept")
def accept_connection(userId: str, me_id: str = Depends(get_current_user_id)) -> dict[str, Any]:
    incoming = (
        supabase.table("friendships")
        .select("*")
        .eq("userId", me_id)
        .eq("friendId", userId)
        .execute()
    ).data or []
    if not incoming or incoming[0].get("status") not in ("incoming", "pending"):
        raise HTTPException(status_code=404, detail="No pending request from this user")

    _set_connected(me_id, userId)
    return {"userId": userId, "status": "connected"}


@router.post("/users/{userId}/connect/reject")
def reject_connection(userId: str, me_id: str = Depends(get_current_user_id)) -> dict[str, Any]:
    _remove_both_edges(me_id, userId)
    return {"userId": userId, "status": "none"}


@router.delete("/users/{userId}/connect")
def disconnect_user(userId: str, me_id: str = Depends(get_current_user_id)) -> dict[str, Any]:
    _remove_both_edges(me_id, userId)
    return {"userId": userId, "status": "none"}


def _set_connected(user_a: str, user_b: str) -> None:
    _upsert_edge(user_a, user_b, "connected")
    _upsert_edge(user_b, user_a, "connected")


def _upsert_edge(user_a: str, user_b: str, status: str) -> None:
    existing = (
        supabase.table("friendships")
        .select("id")
        .eq("userId", user_a)
        .eq("friendId", user_b)
        .execute()
    ).data or []
    if existing:
        supabase.table("friendships").update({"status": status}).eq("id", existing[0]["id"]).execute()
    else:
        supabase.table("friendships").insert({"userId": user_a, "friendId": user_b, "status": status}).execute()


def _remove_both_edges(user_a: str, user_b: str) -> None:
    supabase.table("friendships").delete().eq("userId", user_a).eq("friendId", user_b).execute()
    supabase.table("friendships").delete().eq("userId", user_b).eq("friendId", user_a).execute()


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


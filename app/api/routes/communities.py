from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_current_user_id
from app.db.supabase import supabase

router = APIRouter(prefix="/communities", tags=["Communities"])


@router.get("")
def list_communities(
    q: str | None = Query(default=None),
    joined: bool | None = Query(default=None),
    user_id: str = Depends(get_current_user_id),
) -> dict[str, Any]:
    query = supabase.table("communities").select("*")
    if q:
        query = query.or_(f"name.ilike.%{q}%,slug.ilike.%{q}%")
    resp = query.execute()
    items = resp.data or []

    if joined is not None:
        mem = (
            supabase.table("community_members")
            .select("communityId")
            .eq("userId", user_id)
            .execute()
        ).data or []
        joined_ids = {m["communityId"] for m in mem}
        if joined:
            items = [c for c in items if c["id"] in joined_ids]
        else:
            items = [c for c in items if c["id"] not in joined_ids]

    return {"items": [_community_to_api(c, user_id) for c in items]}


@router.get("/{communityId}")
def get_community(communityId: str, user_id: str = Depends(get_current_user_id)) -> dict[str, Any]:
    resp = supabase.table("communities").select("*").eq("id", communityId).single().execute()
    if not resp.data:
        raise HTTPException(status_code=404, detail="Community not found")
    return _community_to_api(resp.data, user_id)


@router.post("/{communityId}/join")
def join_community(communityId: str, user_id: str = Depends(get_current_user_id)) -> dict[str, Any]:
    supabase.table("community_members").upsert({"communityId": communityId, "userId": user_id}).execute()
    return {"isJoined": True}


@router.delete("/{communityId}/join")
def leave_community(communityId: str, user_id: str = Depends(get_current_user_id)) -> dict[str, Any]:
    supabase.table("community_members").delete().eq("communityId", communityId).eq("userId", user_id).execute()
    return {"isJoined": False}


def _community_to_api(c: dict[str, Any], user_id: str) -> dict[str, Any]:
    is_joined = (
        supabase.table("community_members")
        .select("communityId")
        .eq("communityId", c["id"])
        .eq("userId", user_id)
        .execute()
    ).data
    members_count = (
        supabase.table("community_members").select("communityId", count="exact").eq("communityId", c["id"]).execute()
    ).count or 0
    posts_count = (
        supabase.table("posts").select("id", count="exact").eq("communityId", c["id"]).execute()
    ).count or 0

    return {
        "id": c["id"],
        "name": c.get("name") or "",
        "description": c.get("introduction") or c.get("description") or "",
        "icon": c.get("icon") or "",
        "banner": c.get("banner"),
        "color": c.get("color") or "",
        "members": int(members_count),
        "posts": int(posts_count),
        "tags": c.get("tags") or [],
        "isJoined": bool(is_joined),
        "university": c.get("university"),
    }


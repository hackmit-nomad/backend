from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api.deps import get_current_user_id
from app.db.supabase import supabase

router = APIRouter(prefix="/communities", tags=["Communities"])


class CreateCommunityRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    icon: str | None = None
    banner: str | None = None
    color: str | None = None
    tags: list[str] | None = None
    university: str | None = None


class UpdateCommunityRequest(CreateCommunityRequest):
    pass


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

    mapped = [_community_to_api(c, user_id) for c in items]
    return {"items": mapped, "total": len(mapped)}


@router.post("", status_code=201)
def create_community(body: CreateCommunityRequest) -> dict[str, Any]:
    payload = {
        "name": body.name or "",
        "introduction": body.description or "",
        "description": body.description or "",
        "icon": body.icon or "",
        "banner": body.banner,
        "color": body.color or "",
        "tags": body.tags or [],
        "university": body.university,
    }
    resp = supabase.table("communities").insert(payload).execute()
    if not resp.data:
        raise HTTPException(status_code=500, detail="Failed to create community")
    return _community_to_api(resp.data[0], "")


@router.get("/{communityId}")
def get_community(communityId: str, user_id: str = Depends(get_current_user_id)) -> dict[str, Any]:
    resp = supabase.table("communities").select("*").eq("id", communityId).single().execute()
    if not resp.data:
        raise HTTPException(status_code=404, detail="Community not found")
    return _community_to_api(resp.data, user_id)


@router.patch("/{communityId}")
def update_community(communityId: str, body: UpdateCommunityRequest, user_id: str = Depends(get_current_user_id)) -> dict[str, Any]:
    payload = {
        "name": body.name,
        "description": body.description,
        "introduction": body.description,
        "icon": body.icon,
        "banner": body.banner,
        "color": body.color,
        "tags": body.tags,
        "university": body.university,
    }
    payload = {k: v for k, v in payload.items() if v is not None}
    resp = supabase.table("communities").update(payload).eq("id", communityId).execute()
    if not resp.data:
        raise HTTPException(status_code=404, detail="Community not found")
    return _community_to_api(resp.data[0], user_id)


@router.delete("/{communityId}", status_code=204)
def delete_community(communityId: str) -> None:
    supabase.table("communities").delete().eq("id", communityId).execute()
    return None


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


from __future__ import annotations

import re
from uuid import uuid4
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


def _slugify(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized or f"community-{uuid4().hex[:8]}"


def _build_unique_slug(name: str) -> str:
    base = _slugify(name)
    existing = (
        supabase.table("communities")
        .select("id")
        .eq("slug", base)
        .limit(1)
        .execute()
        .data
    ) or []
    if not existing:
        return base
    return f"{base}-{uuid4().hex[:6]}"


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

    memberships = (
        supabase.table("community_members").select("communityId").eq("userId", user_id).execute().data
    ) or []
    joined_ids = {m["communityId"] for m in memberships}

    if joined is not None:
        if joined:
            items = [c for c in items if c["id"] in joined_ids]
        else:
            items = [c for c in items if c["id"] not in joined_ids]

    community_ids = [c["id"] for c in items]
    member_counts_rows = (
        supabase.table("community_members").select("communityId").in_("communityId", community_ids).execute().data
    ) if community_ids else []
    post_counts_rows = (
        supabase.table("posts").select("communityId").in_("communityId", community_ids).execute().data
    ) if community_ids else []

    member_counts: dict[str, int] = {}
    for row in member_counts_rows or []:
        cid = row["communityId"]
        member_counts[cid] = member_counts.get(cid, 0) + 1
    post_counts: dict[str, int] = {}
    for row in post_counts_rows or []:
        cid = row["communityId"]
        post_counts[cid] = post_counts.get(cid, 0) + 1

    mapped = [
        {
            "id": c["id"],
            "name": c.get("name") or "",
            "description": c.get("introduction") or c.get("description") or "",
            "icon": c.get("icon") or "",
            "banner": c.get("banner"),
            "color": c.get("color") or "",
            "members": int(member_counts.get(c["id"], 0)),
            "posts": int(post_counts.get(c["id"], 0)),
            "tags": c.get("tags") or [],
            "isJoined": c["id"] in joined_ids,
            "university": c.get("university"),
        }
        for c in items
    ]
    return {"items": mapped, "total": len(mapped)}


@router.post("", status_code=201)
def create_community(body: CreateCommunityRequest, user_id: str = Depends(get_current_user_id)) -> dict[str, Any]:
    community_name = (body.name or "").strip() or "Untitled Community"
    payload = {
        "slug": _build_unique_slug(community_name),
        "name": community_name,
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
    return _community_to_api(resp.data[0], user_id)


@router.get("/{communityId}")
def get_community(communityId: str, user_id: str = Depends(get_current_user_id)) -> dict[str, Any]:
    resp = supabase.table("communities").select("*").eq("id", communityId).single().execute()
    if not resp.data:
        raise HTTPException(status_code=404, detail="Community not found")
    return _community_to_api(resp.data, user_id)

@router.get("/{communityId}/members")
def get_community_members(communityId: str, user_id: str = Depends(get_current_user_id)) -> dict[str, Any]:
    community = supabase.table("communities").select("id").eq("id", communityId).single().execute().data
    if not community:
        raise HTTPException(status_code=404, detail="Community not found")

    memberships = (
        supabase.table("community_members").select("userId").eq("communityId", communityId).execute().data
    ) or []
    member_ids = [m["userId"] for m in memberships if m.get("userId")]
    if not member_ids:
        return {"items": [], "total": 0}

    profiles = supabase.table("profiles").select("*").in_("id", member_ids).execute().data or []
    status_by_user = _connection_status_map(user_id)

    order = {member_id: idx for idx, member_id in enumerate(member_ids)}
    profiles = sorted(profiles, key=lambda p: order.get(p.get("id"), len(order)))
    return {
        "items": [_profile_to_user(p, status_by_user.get(p["id"], "none")) for p in profiles],
        "total": len(profiles),
    }


@router.patch("/{communityId}")
def update_community(communityId: str, body: UpdateCommunityRequest, user_id: str = Depends(get_current_user_id)) -> dict[str, Any]:
    payload = {
        "name": body.name,
        "slug": _build_unique_slug(body.name.strip()) if body.name is not None else None,
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
    row = supabase.table("communities").select("id").eq("id", communityId).single().execute().data
    if not row:
        raise HTTPException(status_code=404, detail="Community not found")
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


def _community_to_api(c: dict[str, Any], user_id: str | None) -> dict[str, Any]:
    is_joined = []
    if user_id:
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


def _connection_status_map(user_id: str) -> dict[str, str]:
    direct = (
        supabase.table("friendships").select("friendId,status").eq("userId", user_id).execute()
    ).data or []
    reverse = (
        supabase.table("friendships").select("userId,status").eq("friendId", user_id).execute()
    ).data or []

    status_by_user: dict[str, str] = {}
    for row in direct:
        friend_id = row.get("friendId")
        if friend_id:
            status_by_user[friend_id] = row.get("status") or "none"
    for row in reverse:
        friend_id = row.get("userId")
        if friend_id and friend_id not in status_by_user:
            status_by_user[friend_id] = row.get("status") or "none"
    return status_by_user


def _profile_to_user(profile: dict[str, Any], connection_status: str = "none") -> dict[str, Any]:
    return {
        "id": profile["id"],
        "name": profile.get("displayName") or "",
        "avatar": profile.get("avatarUrl") or "",
        "university": profile.get("university") or "",
        "major": profile.get("major") or "",
        "minor": profile.get("minor"),
        "year": profile.get("year") or "",
        "bio": profile.get("bio") or "",
        "headline": profile.get("headline"),
        "interests": profile.get("interests") or [],
        "courses": profile.get("courses") or [],
        "communities": profile.get("communities") or [],
        "isConnected": connection_status == "connected",
        "isOnline": bool(profile.get("isOnline")) if "isOnline" in profile else False,
        "profileViews": int(profile.get("profileViews") or 0),
    }


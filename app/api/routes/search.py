from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user_id
from app.db.supabase import supabase

router = APIRouter(tags=["Search"])


@router.get("/search")
def global_search(q: str = Query(...), user_id: str = Depends(get_current_user_id)) -> dict[str, Any]:
    users = (
        supabase.table("profiles")
        .select("*")
        .or_(f"displayName.ilike.%{q}%,email.ilike.%{q}%")
        .limit(10)
        .execute()
        .data
    ) or []
    courses = (
        supabase.table("course_versions")
        .select("*")
        .or_(f"code.ilike.%{q}%,title.ilike.%{q}%,description.ilike.%{q}%")
        .limit(10)
        .execute()
        .data
    ) or []
    communities = (
        supabase.table("communities")
        .select("*")
        .or_(f"name.ilike.%{q}%,slug.ilike.%{q}%")
        .limit(10)
        .execute()
        .data
    ) or []
    posts = (
        supabase.table("posts")
        .select("*")
        .or_(f"title.ilike.%{q}%,content.ilike.%{q}%")
        .is_("deletedAt", "null")
        .limit(10)
        .execute()
        .data
    ) or []

    return {
        "users": [_profile_to_user(p) for p in users],
        "courses": [_cv_to_course(c) for c in courses],
        "communities": [_community_to_api(c) for c in communities],
        "posts": [_post_to_api(p) for p in posts],
    }


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
        "isConnected": False,
        "isOnline": False,
        "profileViews": int(p.get("profileViews") or 0),
    }


def _cv_to_course(cv: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": cv["id"],
        "code": cv.get("code") or "",
        "title": cv.get("title") or "",
        "credits": int(cv.get("credits") or 0),
        "description": cv.get("description") or "",
        "department": cv.get("department") or cv.get("subjectCode") or "",
        "difficulty": cv.get("difficulty") or "Intro",
        "prerequisites": cv.get("prerequisites") or [],
        "nextCourses": cv.get("nextCourses") or [],
        "tags": cv.get("tags") or [],
        "students": cv.get("students") or [],
    }


def _community_to_api(c: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": c["id"],
        "name": c.get("name") or "",
        "description": c.get("introduction") or c.get("description") or "",
        "icon": c.get("icon") or "",
        "banner": c.get("banner"),
        "color": c.get("color") or "",
        "members": int(c.get("members") or 0),
        "posts": int(c.get("posts") or 0),
        "tags": c.get("tags") or [],
        "isJoined": bool(c.get("isJoined")) if "isJoined" in c else False,
        "university": c.get("university"),
    }


def _post_to_api(p: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": p["id"],
        "authorId": p.get("authorId"),
        "communityId": p.get("communityId"),
        "title": p.get("title") or "",
        "content": p.get("content") or "",
        "timestamp": p.get("createdAt"),
        "likes": int(p.get("likes") or 0),
        "isLiked": False,
        "myReaction": None,
        "tags": p.get("tags") or [],
        "replies": [],
    }


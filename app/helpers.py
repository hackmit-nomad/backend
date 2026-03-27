from datetime import datetime
from typing import Any, Dict, Optional

from .db import supabase
from .schemas import ConnectionStatus, Course, Post, User


def now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def map_profile_to_user(profile: Dict[str, Any], connected: bool = False) -> User:
    return User(
        id=profile["id"],
        name=profile.get("displayName") or profile.get("name") or "",
        avatar=profile.get("avatarUrl") or "",
        university=profile.get("university") or "",
        major=profile.get("major") or "",
        minor=profile.get("minor"),
        year=profile.get("year") or "",
        bio=profile.get("bio") or "",
        headline=profile.get("headline"),
        interests=profile.get("interests") or [],
        courses=profile.get("courses") or [],
        communities=profile.get("communities") or [],
        isConnected=connected,
        isOnline=profile.get("isOnline") or False,
        profileViews=profile.get("profileViews") or 0,
    )


def current_user_id(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    token = authorization.replace("Bearer ", "").strip()
    if not token:
        return None
    try:
        auth_user = supabase.auth.get_user(token)
        return auth_user.user.id if auth_user and auth_user.user else None
    except Exception:
        return None


def get_connection_status(me: Optional[str], other: str) -> ConnectionStatus:
    if not me:
        return "none"
    if me == other:
        return "connected"
    rs = (
        supabase.table("friendships")
        .select("*")
        .or_(f"and(userId.eq.{me},friendId.eq.{other}),and(userId.eq.{other},friendId.eq.{me})")
        .limit(1)
        .execute()
    )
    row = (rs.data or [None])[0]
    if not row:
        return "none"
    status = row.get("status")
    if status == "accepted":
        return "connected"
    if status == "pending":
        return "pending" if row.get("userId") == me else "incoming"
    return "none"


def map_course_row(row: Dict[str, Any]) -> Course:
    credits = row.get("creditsDefault")
    credits_val = int(credits) if isinstance(credits, (int, float)) else 0
    return Course(
        id=row["id"],
        code=row.get("canonicalCode") or row.get("code") or "",
        title=row.get("canonicalName") or row.get("title") or "",
        credits=credits_val,
        description=row.get("description") or "",
        department=row.get("subjectCode") or row.get("department") or "",
        difficulty=row.get("difficulty") or "Intro",
        prerequisites=row.get("prerequisites") or [],
        nextCourses=row.get("nextCourses") or [],
        tags=row.get("tags") or [],
        rating=float(row.get("rating") or 0.0),
        students=row.get("students") or [],
    )


def map_post_row(row: Dict[str, Any]) -> Post:
    return Post(
        id=row["id"],
        authorId=row["authorId"],
        communityId=row.get("communityId") or "",
        title=row.get("title") or "",
        content=row.get("content") or "",
        timestamp=row.get("createdAt") or now_iso(),
        likes=int(row.get("likes") or 0),
        isLiked=bool(row.get("isLiked") or False),
        myReaction=row.get("myReaction"),
        tags=row.get("tags") or [],
        replies=[],
    )

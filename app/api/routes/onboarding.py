from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import get_current_user_id
from app.db.supabase import supabase

router = APIRouter(prefix="/onboarding", tags=["Onboarding"])


@router.get("/options")
def onboarding_options() -> dict[str, Any]:
    schools = (supabase.table("schools").select("name").execute().data) or []
    universities = sorted({s["name"] for s in schools if s.get("name")})

    programs = (supabase.table("programs").select("name").execute().data) or []
    majors = sorted({p["name"] for p in programs if p.get("name")})

    # Interests are product-level; keep a small static catalog for MVP.
    interests = [
        "AI",
        "Systems",
        "Product",
        "Design",
        "Robotics",
        "Security",
        "Entrepreneurship",
        "Music",
        "Sports",
    ]
    return {"universities": universities, "majors": majors, "interests": interests}


class OnboardingCompleteRequest(BaseModel):
    university: str
    fullName: str
    majors: list[str]
    minors: list[str] | None = None
    interests: list[str] | None = None


@router.post("/complete")
def onboarding_complete(body: OnboardingCompleteRequest, user_id: str = Depends(get_current_user_id)) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "university": body.university,
        "displayName": body.fullName,
        "major": body.majors[0] if body.majors else None,
        "minor": body.minors[0] if body.minors else None,
        "interests": body.interests or [],
    }
    resp = supabase.table("profiles").update(payload).eq("id", user_id).execute()
    if resp.data:
        p = resp.data[0]
    else:
        p = (supabase.table("profiles").select("*").eq("id", user_id).single().execute().data) or {"id": user_id}
    return {
        "id": p.get("id"),
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


from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api.deps import get_current_user_id
from app.db.supabase import supabase

router = APIRouter(prefix="/courses", tags=["Courses"])


@router.get("")
def list_courses(
    q: str | None = Query(default=None),
    department: str | None = Query(default=None),
    difficulty: str | None = Query(default=None),
) -> dict[str, Any]:
    # MVP: Use course_versions as the "Course" projection for the UI.
    query = supabase.table("course_versions").select("*")
    if q:
        query = query.or_(f"code.ilike.%{q}%,title.ilike.%{q}%,description.ilike.%{q}%")
    if department:
        query = query.eq("department", department)
    if difficulty:
        query = query.eq("difficulty", difficulty)
    resp = query.execute()
    items = resp.data or []
    return {"items": [_cv_to_course(c) for c in items], "total": len(items)}


@router.get("/{courseId}")
def get_course_details(courseId: str, user_id: str = Depends(get_current_user_id)) -> dict[str, Any]:
    cv = supabase.table("course_versions").select("*").eq("id", courseId).single().execute().data
    if not cv:
        raise HTTPException(status_code=404, detail="Course not found")

    # prerequisites/nextCourses from edges
    prereq_edges = (
        supabase.table("course_prerequisite_edges")
        .select("prerequisiteCourseVersionId")
        .eq("courseVersionId", courseId)
        .execute()
    ).data or []
    prerequisites = [e["prerequisiteCourseVersionId"] for e in prereq_edges]

    next_edges = (
        supabase.table("course_prerequisite_edges")
        .select("courseVersionId")
        .eq("prerequisiteCourseVersionId", courseId)
        .execute()
    ).data or []
    next_courses = [e["courseVersionId"] for e in next_edges]

    details = _cv_to_course(cv)
    details["prerequisites"] = prerequisites
    details["nextCourses"] = next_courses

    # classmates buckets
    known, suggested = _course_connections(courseId, user_id)
    details["knownClassmates"] = known
    details["suggestedClassmates"] = suggested
    return details


@router.get("/{courseId}/students")
def course_students(
    courseId: str,
    connected: bool | None = Query(default=None),
    user_id: str = Depends(get_current_user_id),
) -> dict[str, Any]:
    # Students derived from user_courses -> profiles
    uc = (
        supabase.table("user_courses")
        .select("userId, profiles!inner(*)")
        .eq("courseVersionId", courseId)
        .execute()
    ).data or []
    items = [row["profiles"] for row in uc if row.get("profiles")]

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

    return {"courseId": courseId, "items": [_profile_to_user(p) for p in items], "total": len(items)}


@router.get("/{courseId}/connections")
def course_connections(courseId: str, user_id: str = Depends(get_current_user_id)) -> dict[str, Any]:
    known, suggested = _course_connections(courseId, user_id)
    return {"known": known, "suggested": suggested}


def _course_connections(course_id: str, user_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    uc = (
        supabase.table("user_courses")
        .select("userId, profiles!inner(*)")
        .eq("courseVersionId", course_id)
        .execute()
    ).data or []
    classmates = [row["profiles"] for row in uc if row.get("profiles") and row.get("profiles")["id"] != user_id]

    rel = (
        supabase.table("friendships")
        .select("friendId,status")
        .eq("userId", user_id)
        .execute()
    ).data or []
    connected_ids = {r["friendId"] for r in rel if r.get("status") == "connected"}

    known = [_profile_to_user(p) for p in classmates if p["id"] in connected_ids]
    suggested = [_profile_to_user(p) for p in classmates if p["id"] not in connected_ids]
    return known, suggested


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
        "rating": float(cv.get("rating") or 0.0),
        "students": cv.get("students") or [],
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


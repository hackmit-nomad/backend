from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api.deps import get_current_user_id
from app.db.supabase import supabase

router = APIRouter(prefix="/courses", tags=["Courses"])


class CreateCourseRequest(BaseModel):
    code: str | None = None
    title: str | None = None
    credits: int | None = None
    description: str | None = None
    prerequisites: list[str] | None = None
    nextCourses: list[str] | None = None
    department: str | None = None
    difficulty: str | None = None
    tags: list[str] | None = None


class UpdateCourseRequest(CreateCourseRequest):
    pass


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


@router.post("", status_code=201)
def create_course(body: CreateCourseRequest) -> dict[str, Any]:
    payload = {
        "code": body.code or "",
        "title": body.title or "",
        "credits": body.credits or 0,
        "description": body.description or "",
        "department": body.department or "",
        "difficulty": body.difficulty or "Intro",
        "tags": body.tags or [],
    }
    resp = supabase.table("course_versions").insert(payload).execute()
    if not resp.data:
        raise HTTPException(status_code=500, detail="Failed to create course")
    row = resp.data[0]
    cid = row["id"]

    for pid in body.prerequisites or []:
        supabase.table("course_prerequisite_edges").insert(
            {"courseVersionId": cid, "prerequisiteCourseVersionId": pid, "relationType": "required"}
        ).execute()
    for nid in body.nextCourses or []:
        supabase.table("course_prerequisite_edges").insert(
            {"courseVersionId": nid, "prerequisiteCourseVersionId": cid, "relationType": "required"}
        ).execute()
    return _cv_to_course(row)


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


@router.patch("/{courseId}")
def update_course(courseId: str, body: UpdateCourseRequest) -> dict[str, Any]:
    payload = {k: v for k, v in body.model_dump().items() if v is not None and k not in ("prerequisites", "nextCourses")}
    if payload:
        resp = supabase.table("course_versions").update(payload).eq("id", courseId).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail="Course not found")
    row = supabase.table("course_versions").select("*").eq("id", courseId).single().execute().data
    if not row:
        raise HTTPException(status_code=404, detail="Course not found")
    return _cv_to_course(row)


@router.delete("/{courseId}", status_code=204)
def delete_course(courseId: str) -> None:
    row = supabase.table("course_versions").select("id").eq("id", courseId).single().execute().data
    if not row:
        raise HTTPException(status_code=404, detail="Course not found")
    supabase.table("course_versions").delete().eq("id", courseId).execute()
    return None


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


@router.get("/{courseId}/connections/graph")
def course_connections_graph(courseId: str, user_id: str = Depends(get_current_user_id)) -> dict[str, Any]:
    classmates = _classmates_for_course(courseId, user_id)
    me_profile = supabase.table("profiles").select("*").eq("id", user_id).single().execute().data
    if not me_profile:
        raise HTTPException(status_code=404, detail="User not found")

    participant_ids = [user_id, *[p["id"] for p in classmates]]
    if not participant_ids:
        return {"nodes": [], "edges": []}

    connected_rows = (
        supabase.table("friendships")
        .select("userId,friendId,status")
        .eq("status", "connected")
        .in_("userId", participant_ids)
        .execute()
    ).data or []

    participant_set = set(participant_ids)
    unique_edges: set[tuple[str, str]] = set()
    for row in connected_rows:
        src = row.get("userId")
        dst = row.get("friendId")
        if not src or not dst or src == dst:
            continue
        if src not in participant_set or dst not in participant_set:
            continue
        a, b = sorted((src, dst))
        unique_edges.add((a, b))

    me_connected_ids = {b if a == user_id else a for a, b in unique_edges if user_id in (a, b)}
    classmate_ids = {p["id"] for p in classmates}
    nodes = [
        {
            **_profile_to_user(me_profile),
            "isMe": True,
            "isClassmate": False,
            "isConnected": False,
        }
    ]
    for profile in classmates:
        pid = profile["id"]
        nodes.append(
            {
                **_profile_to_user(profile),
                "isMe": False,
                "isClassmate": pid in classmate_ids,
                "isConnected": pid in me_connected_ids,
            }
        )

    edges = [{"source": a, "target": b} for a, b in sorted(unique_edges)]
    return {"nodes": nodes, "edges": edges}


def _course_connections(course_id: str, user_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    classmates = _classmates_for_course(course_id, user_id)

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


def _classmates_for_course(course_id: str, user_id: str) -> list[dict[str, Any]]:
    uc = (
        supabase.table("user_courses")
        .select("userId, profiles!inner(*)")
        .eq("courseVersionId", course_id)
        .execute()
    ).data or []
    return [row["profiles"] for row in uc if row.get("profiles") and row.get("profiles")["id"] != user_id]


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


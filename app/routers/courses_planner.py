from typing import List, Optional

from fastapi import APIRouter, Header, HTTPException

from ..db import supabase
from ..helpers import current_user_id, get_connection_status, map_course_row, map_profile_to_user
from ..schemas import CourseDetails, Difficulty, PlannerState, UpdatePlannerRequest, User

router = APIRouter()


@router.get("/courses")
def list_courses(
    q: Optional[str] = None,
    department: Optional[str] = None,
    difficulty: Optional[Difficulty] = None,
):
    query = supabase.table("courses").select("*")
    if q:
        query = query.or_(f"canonicalName.ilike.%{q}%,canonicalCode.ilike.%{q}%")
    if department:
        query = query.eq("subjectCode", department)
    rows = query.execute().data or []
    items = [
        map_course_row(r)
        for r in rows
        if difficulty is None or (r.get("difficulty") or "Intro") == difficulty
    ]
    return {"items": items, "total": len(items)}


@router.get("/courses/{courseId}", response_model=CourseDetails)
def get_course(courseId: str):
    row = supabase.table("courses").select("*").eq("id", courseId).single().execute().data
    if not row:
        raise HTTPException(status_code=404, detail="Course not found")
    base = map_course_row(row)
    return CourseDetails(**base.model_dump(), knownClassmates=[], suggestedClassmates=[])


@router.get("/courses/{courseId}/students")
def get_course_students(
    courseId: str,
    connected: Optional[bool] = None,
    authorization: Optional[str] = Header(default=None),
):
    me = current_user_id(authorization)
    rows = (
        supabase.table("user_courses")
        .select("userId, profiles!inner(*)")
        .eq("courseId", courseId)
        .execute()
        .data
        or []
    )
    items: List[User] = []
    for row in rows:
        profile = row.get("profiles")
        if not profile:
            continue
        status = get_connection_status(me, profile["id"])
        u = map_profile_to_user(profile, connected=(status == "connected"))
        if connected is None or u.isConnected == connected:
            items.append(u)
    return {"courseId": courseId, "items": items, "total": len(items)}


@router.get("/courses/{courseId}/connections")
def get_course_connections(courseId: str, authorization: Optional[str] = Header(default=None)):
    me = current_user_id(authorization)
    if not me:
        raise HTTPException(status_code=401, detail="Unauthorized")
    rows = (
        supabase.table("user_courses")
        .select("userId, profiles!inner(*)")
        .eq("courseId", courseId)
        .execute()
        .data
        or []
    )
    known: List[User] = []
    suggested: List[User] = []
    for row in rows:
        profile = row.get("profiles")
        if not profile or profile["id"] == me:
            continue
        status = get_connection_status(me, profile["id"])
        user = map_profile_to_user(profile, connected=(status == "connected"))
        if status == "connected":
            known.append(user)
        else:
            suggested.append(user)
    return {"known": known, "suggested": suggested}


@router.get("/planner/courses", response_model=PlannerState)
def get_planner_courses(authorization: Optional[str] = Header(default=None)):
    uid = current_user_id(authorization)
    if not uid:
        raise HTTPException(status_code=401, detail="Unauthorized")
    rows = (
        supabase.table("user_courses")
        .select("courseId")
        .eq("userId", uid)
        .eq("status", "planned")
        .execute()
        .data
        or []
    )
    return PlannerState(courseIds=[r["courseId"] for r in rows])


@router.put("/planner/courses", response_model=PlannerState)
def put_planner_courses(body: UpdatePlannerRequest, authorization: Optional[str] = Header(default=None)):
    uid = current_user_id(authorization)
    if not uid:
        raise HTTPException(status_code=401, detail="Unauthorized")
    supabase.table("user_courses").delete().eq("userId", uid).eq("status", "planned").execute()
    for cid in body.courseIds:
        supabase.table("user_courses").insert(
            {"userId": uid, "courseId": cid, "status": "planned"}
        ).execute()
    return PlannerState(courseIds=body.courseIds)

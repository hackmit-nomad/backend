from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import get_current_user_id
from app.db.supabase import supabase

router = APIRouter(prefix="/planner", tags=["Planner"])


@router.get("/courses")
def get_planner_state(user_id: str = Depends(get_current_user_id)) -> dict[str, Any]:
    rows = (
        supabase.table("user_courses")
        .select("courseVersionId")
        .eq("userId", user_id)
        .eq("status", "planned")
        .execute()
        .data
    ) or []
    course_ids = [r.get("courseVersionId") for r in rows if r.get("courseVersionId")]
    return {"courseIds": course_ids}


class UpdatePlannerRequest(BaseModel):
    courseIds: list[str]


@router.put("/courses")
def replace_planned_courses(body: UpdatePlannerRequest, user_id: str = Depends(get_current_user_id)) -> dict[str, Any]:
    existing = (
        supabase.table("user_courses")
        .select("id,courseVersionId")
        .eq("userId", user_id)
        .eq("status", "planned")
        .execute()
        .data
    ) or []
    existing_ids = {r.get("courseVersionId") for r in existing}
    new_ids = set(body.courseIds)

    # remove
    to_remove = [r for r in existing if r.get("courseVersionId") not in new_ids]
    for r in to_remove:
        supabase.table("user_courses").delete().eq("id", r["id"]).execute()

    # add
    for cid in new_ids - existing_ids:
        supabase.table("user_courses").insert({"userId": user_id, "courseVersionId": cid, "status": "planned"}).execute()

    return {"courseIds": list(new_ids)}


from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

# Allow running as: python scripts/seed_course_graph_demo.py
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db.supabase import supabase
from supabase_auth.errors import AuthApiError


@dataclass(frozen=True)
class DemoProfile:
    key: str
    display_name: str
    major: str
    year: str
    interests: list[str]
    bio: str
    avatar_url: str


DEMO_PROFILES: list[DemoProfile] = [
    DemoProfile(
        key="alice",
        display_name="Alice Kim",
        major="Computer Science",
        year="Junior",
        interests=["Algorithms", "ML", "Startups"],
        bio="Loves graph theory and coffee chats.",
        avatar_url="https://api.dicebear.com/7.x/avataaars/svg?seed=alice-demo",
    ),
    DemoProfile(
        key="brandon",
        display_name="Brandon Patel",
        major="Data Science",
        year="Senior",
        interests=["Databases", "Systems", "Hackathons"],
        bio="Backend builder and distributed systems fan.",
        avatar_url="https://api.dicebear.com/7.x/avataaars/svg?seed=brandon-demo",
    ),
    DemoProfile(
        key="chloe",
        display_name="Chloe Rivera",
        major="Mathematics",
        year="Sophomore",
        interests=["Optimization", "AI", "Research"],
        bio="Enjoys proofs, planning, and people.",
        avatar_url="https://api.dicebear.com/7.x/avataaars/svg?seed=chloe-demo",
    ),
    DemoProfile(
        key="diego",
        display_name="Diego Santos",
        major="Electrical Engineering",
        year="Junior",
        interests=["Signals", "Robotics", "Networks"],
        bio="Builds hardware and full-stack side projects.",
        avatar_url="https://api.dicebear.com/7.x/avataaars/svg?seed=diego-demo",
    ),
]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _list_auth_users() -> list[Any]:
    all_users: list[Any] = []
    page = 1
    per_page = 500
    while True:
        users = supabase.auth.admin.list_users(page=page, per_page=per_page) or []
        if not users:
            break
        all_users.extend(users)
        if len(users) < per_page:
            break
        page += 1
    return all_users


def _get_auth_user_id_by_email(email: str) -> str | None:
    for user in _list_auth_users():
        if getattr(user, "email", None) == email:
            user_id = getattr(user, "id", None)
            if user_id:
                return str(user_id)
    return None


def _ensure_auth_user(profile: DemoProfile) -> str:
    email = f"{profile.key}.demo@nomad.local"
    existing_id = _get_auth_user_id_by_email(email)
    if existing_id:
        return existing_id

    try:
        created = supabase.auth.admin.create_user(
            {
                "email": email,
                "password": "NomadDemo123!",
                "email_confirm": True,
                "user_metadata": {"displayName": profile.display_name},
            }
        )
        user = getattr(created, "user", None)
        user_id = getattr(user, "id", None)
        if user_id:
            return str(user_id)
    except AuthApiError as exc:
        # Race-safe fallback when user already exists.
        if "already been registered" not in str(exc):
            raise

    existing_id = _get_auth_user_id_by_email(email)
    if existing_id:
        return existing_id
    raise RuntimeError(f"Failed creating or finding auth user for {email}")


def _ensure_profile(profile: DemoProfile) -> str:
    profile_id = _ensure_auth_user(profile)
    existing = (
        supabase.table("profiles")
        .select("id")
        .eq("id", profile_id)
        .limit(1)
        .execute()
        .data
    ) or []
    payload: dict[str, Any] = {
        "id": profile_id,
        "displayName": profile.display_name,
        "avatarUrl": profile.avatar_url,
        "email": f"{profile.key}.demo@nomad.local",
        "university": "Demo University",
        "major": profile.major,
        "year": profile.year,
        "bio": profile.bio,
        "headline": "Demo account for course graph testing",
        "interests": profile.interests,
        "courses": [],
        "communities": [],
        "profileViews": 0,
        "isOnline": True,
    }
    if existing:
        supabase.table("profiles").update(payload).eq("id", profile_id).execute()
    else:
        supabase.table("profiles").insert(payload).execute()
    return profile_id


def _upsert_friend_edge(user_id: str, friend_id: str, status: str) -> None:
    existing = (
        supabase.table("friendships")
        .select("id")
        .eq("userId", user_id)
        .eq("friendId", friend_id)
        .limit(1)
        .execute()
        .data
    ) or []
    payload = {
        "userId": user_id,
        "friendId": friend_id,
        "status": status,
        "requestedBy": user_id,
        "requestedAt": _now_iso(),
        "acceptedAt": _now_iso() if status == "connected" else None,
    }
    if existing:
        supabase.table("friendships").update(payload).eq("id", existing[0]["id"]).execute()
    else:
        supabase.table("friendships").insert(payload).execute()


def _upsert_user_course(user_id: str, course_version_id: str, status: str) -> None:
    existing = (
        supabase.table("user_courses")
        .select("id")
        .eq("userId", user_id)
        .eq("courseVersionId", course_version_id)
        .limit(1)
        .execute()
        .data
    ) or []
    payload = {
        "userId": user_id,
        "courseVersionId": course_version_id,
        "status": status,
        "source": "demo_seed",
    }
    if existing:
        supabase.table("user_courses").update(payload).eq("id", existing[0]["id"]).execute()
    else:
        supabase.table("user_courses").insert(payload).execute()


def _pick_demo_course_versions(limit: int = 4) -> list[str]:
    rows = (
        supabase.table("course_versions")
        .select("id,code,title")
        .order("updatedAt", desc=True)
        .limit(limit)
        .execute()
        .data
    ) or []
    course_ids = [row["id"] for row in rows if row.get("id")]
    if len(course_ids) < 3:
        course_ids = _ensure_demo_courses()
        rows = (
            supabase.table("course_versions")
            .select("id,code,title")
            .in_("id", course_ids)
            .execute()
            .data
        ) or []
    print("Using course_versions:", ", ".join(row.get("code") or row["id"] for row in rows))
    return course_ids


def _stable_id(name: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"nomad-seed:{name}"))


def _ensure_demo_courses() -> list[str]:
    school_rows = supabase.table("schools").select("id").limit(1).execute().data or []
    if school_rows:
        school_id = school_rows[0]["id"]
    else:
        school_id = _stable_id("school:demo-university")
        existing_school = supabase.table("schools").select("id").eq("id", school_id).limit(1).execute().data or []
        if not existing_school:
            supabase.table("schools").insert(
                {
                    "id": school_id,
                    "name": "Demo University",
                    "country": "US",
                    "website": "https://demo.university.example",
                    "timezone": "UTC",
                    "meta": {"seed": "demo-course-graph"},
                }
            ).execute()

    defs = [
        ("DEMO-CG101", "Graph Foundations", "Intro", 0),
        ("DEMO-CG201", "Network Algorithms", "Intermediate", 1),
        ("DEMO-CG301", "Social Graph Systems", "Advanced", 2),
    ]
    version_ids: list[str] = []
    for code, title, difficulty, order in defs:
        course_id = _stable_id(f"course:{code}")
        version_id = _stable_id(f"course-version:{code}")
        version_ids.append(version_id)

        existing_course = supabase.table("courses").select("id").eq("id", course_id).limit(1).execute().data or []
        if not existing_course:
            supabase.table("courses").insert(
                {
                    "id": course_id,
                    "schoolId": school_id,
                    "canonicalCode": code,
                    "canonicalName": title,
                    "normalizedCode": code.lower(),
                    "normalizedName": title.lower(),
                    "subjectCode": "DEMO",
                    "courseNumber": str(100 + (order * 100)),
                    "creditsDefault": 3,
                }
            ).execute()

        existing_version = (
            supabase.table("course_versions").select("id").eq("id", version_id).limit(1).execute().data or []
        )
        payload = {
            "id": version_id,
            "courseId": course_id,
            "code": code,
            "title": title,
            "description": f"{title} demo course for planner graph testing.",
            "credits": 3,
            "department": "DEMO",
            "difficulty": difficulty,
            "tags": ["demo", "graph"],
        }
        if existing_version:
            supabase.table("course_versions").update(payload).eq("id", version_id).execute()
        else:
            supabase.table("course_versions").insert(payload).execute()

    # Prereqs: 201 requires 101, 301 requires 201.
    edges = [
        (_stable_id("edge:201-101"), _stable_id("course-version:DEMO-CG201"), _stable_id("course-version:DEMO-CG101")),
        (_stable_id("edge:301-201"), _stable_id("course-version:DEMO-CG301"), _stable_id("course-version:DEMO-CG201")),
    ]
    for edge_id, course_version_id, prereq_id in edges:
        existing_edge = (
            supabase.table("course_prerequisite_edges").select("id").eq("id", edge_id).limit(1).execute().data or []
        )
        edge_payload = {
            "id": edge_id,
            "courseVersionId": course_version_id,
            "prerequisiteCourseVersionId": prereq_id,
            "relationType": "required",
        }
        if existing_edge:
            supabase.table("course_prerequisite_edges").update(edge_payload).eq("id", edge_id).execute()
        else:
            supabase.table("course_prerequisite_edges").insert(edge_payload).execute()

    return version_ids


def clear_demo_data(current_user_id: str | None) -> None:
    demo_emails = {f"{p.key}.demo@nomad.local" for p in DEMO_PROFILES}
    demo_ids = [
        str(getattr(user, "id"))
        for user in _list_auth_users()
        if getattr(user, "email", None) in demo_emails and getattr(user, "id", None)
    ]
    participants = [*demo_ids, *( [current_user_id] if current_user_id else [] )]

    if participants:
        (
            supabase.table("friendships")
            .delete()
            .in_("userId", participants)
            .in_("friendId", participants)
            .execute()
        )
        supabase.table("user_courses").delete().in_("userId", participants).eq("source", "demo_seed").execute()

    supabase.table("profiles").delete().in_("id", demo_ids).execute()
    print(f"Cleared demo profiles={len(demo_ids)} and related seeded edges/courses.")


def seed_demo_data(current_user_id: str | None) -> None:
    demo_ids = {profile.key: _ensure_profile(profile) for profile in DEMO_PROFILES}
    course_ids = _pick_demo_course_versions(limit=5)

    alice = demo_ids["alice"]
    brandon = demo_ids["brandon"]
    chloe = demo_ids["chloe"]
    diego = demo_ids["diego"]

    # Connected graph among demo users:
    # Alice <-> Brandon <-> Chloe and Brandon <-> Diego
    connected_pairs = [(alice, brandon), (brandon, chloe), (brandon, diego)]
    for a, b in connected_pairs:
        _upsert_friend_edge(a, b, "connected")
        _upsert_friend_edge(b, a, "connected")

    # Optional connections from your current user to create meaningful "mutuals" in UI.
    if current_user_id:
        _upsert_friend_edge(current_user_id, brandon, "connected")
        _upsert_friend_edge(brandon, current_user_id, "connected")
        _upsert_friend_edge(current_user_id, alice, "connected")
        _upsert_friend_edge(alice, current_user_id, "connected")

    # Enroll demo users into overlapping courses to exercise course graph + connections.
    # course_ids[0] acts as a shared anchor course with many classmates.
    base = course_ids[0]
    second = course_ids[1] if len(course_ids) > 1 else base
    third = course_ids[2] if len(course_ids) > 2 else second
    fourth = course_ids[3] if len(course_ids) > 3 else third

    _upsert_user_course(alice, base, "planned")
    _upsert_user_course(alice, second, "planned")
    _upsert_user_course(brandon, base, "planned")
    _upsert_user_course(brandon, third, "planned")
    _upsert_user_course(chloe, base, "planned")
    _upsert_user_course(chloe, fourth, "planned")
    _upsert_user_course(diego, second, "planned")
    _upsert_user_course(diego, third, "planned")

    if current_user_id:
        _upsert_user_course(current_user_id, base, "planned")
        _upsert_user_course(current_user_id, second, "planned")

    print("Seed complete.")
    print(f"Demo profile IDs: {demo_ids}")
    if current_user_id:
        print(f"Connected current user: {current_user_id}")
    print("Now open /app/planner and /app/my-courses to verify graph + mutuals.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Supabase demo data for course connection graph.")
    parser.add_argument(
        "--user-id",
        dest="user_id",
        default=None,
        help="Optional current user id to connect to demo users and enroll in demo courses.",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear previously seeded demo data instead of seeding.",
    )
    args = parser.parse_args()

    if args.clear:
        clear_demo_data(args.user_id)
        return

    seed_demo_data(args.user_id)


if __name__ == "__main__":
    main()


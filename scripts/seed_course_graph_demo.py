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


@dataclass(frozen=True)
class DemoCommunity:
    key: str
    name: str
    description: str
    icon: str
    color: str
    tags: list[str]


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
    DemoProfile(
        key="emma",
        display_name="Emma Zhou",
        major="Computer Engineering",
        year="Sophomore",
        interests=["Compilers", "Embedded", "Security"],
        bio="Enjoys low-level systems and teaching peers.",
        avatar_url="https://api.dicebear.com/7.x/avataaars/svg?seed=emma-demo",
    ),
    DemoProfile(
        key="farah",
        display_name="Farah Noor",
        major="Information Science",
        year="Senior",
        interests=["HCI", "Product", "Data Viz"],
        bio="Turns user problems into pragmatic product ideas.",
        avatar_url="https://api.dicebear.com/7.x/avataaars/svg?seed=farah-demo",
    ),
]


DEMO_COMMUNITIES: list[DemoCommunity] = [
    DemoCommunity(
        key="graph-theory",
        name="Graph Theory Guild",
        description="Proofs, problem sets, and elegant graph constructions.",
        icon="Network",
        color="#4F46E5",
        tags=["graphs", "math", "algorithms"],
    ),
    DemoCommunity(
        key="ml-systems",
        name="ML Systems Lab",
        description="Model serving, feature pipelines, and practical ML infra.",
        icon="Brain",
        color="#0EA5E9",
        tags=["ml", "systems", "infra"],
    ),
    DemoCommunity(
        key="backend-builders",
        name="Backend Builders",
        description="APIs, databases, and architecture tradeoffs.",
        icon="Server",
        color="#10B981",
        tags=["backend", "databases", "architecture"],
    ),
    DemoCommunity(
        key="startup-studio",
        name="Startup Studio",
        description="Build, ship, and iterate on student startup ideas.",
        icon="Rocket",
        color="#F59E0B",
        tags=["startups", "product", "growth"],
    ),
    DemoCommunity(
        key="study-sprint",
        name="Study Sprint",
        description="Co-working accountability, focus sessions, and peer support.",
        icon="BookOpen",
        color="#EF4444",
        tags=["study", "accountability", "community"],
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


def _resolve_current_user_id(user_id: str | None, user_email: str | None) -> str | None:
    if user_id:
        return user_id
    if not user_email:
        return None
    resolved = _get_auth_user_id_by_email(user_email)
    if resolved:
        return resolved
    raise RuntimeError(f"Could not find auth user for email: {user_email}")


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


def _upsert_community(defn: DemoCommunity) -> str:
    community_id = _stable_id(f"community:{defn.key}")
    existing = (
        supabase.table("communities")
        .select("id")
        .eq("id", community_id)
        .limit(1)
        .execute()
        .data
    ) or []
    payload = {
        "id": community_id,
        "slug": defn.key,
        "name": defn.name,
        "introduction": defn.description,
        "description": defn.description,
        "icon": defn.icon,
        "color": defn.color,
        "tags": defn.tags,
        "university": "Demo University",
    }
    if existing:
        supabase.table("communities").update(payload).eq("id", community_id).execute()
    else:
        supabase.table("communities").insert(payload).execute()
    return community_id


def _upsert_community_member(community_id: str, user_id: str) -> None:
    supabase.table("community_members").upsert({"communityId": community_id, "userId": user_id}).execute()


def _upsert_post(
    *,
    post_id: str,
    author_id: str,
    community_id: str,
    title: str,
    content: str,
    tags: list[str],
) -> None:
    existing = (
        supabase.table("posts")
        .select("id")
        .eq("id", post_id)
        .limit(1)
        .execute()
        .data
    ) or []
    now = _now_iso()
    payload = {
        "id": post_id,
        "authorId": author_id,
        "communityId": community_id,
        "title": title,
        "content": content,
        "tags": tags,
        "createdAt": now,
        "updatedAt": now,
    }
    if existing:
        supabase.table("posts").update(payload).eq("id", post_id).execute()
    else:
        supabase.table("posts").insert(payload).execute()


def _upsert_comment(*, comment_id: str, post_id: str, author_id: str, content: str) -> None:
    existing = (
        supabase.table("comments")
        .select("id")
        .eq("id", comment_id)
        .limit(1)
        .execute()
        .data
    ) or []
    now = _now_iso()
    payload = {
        "id": comment_id,
        "postId": post_id,
        "authorId": author_id,
        "content": content,
        "createdAt": now,
        "updatedAt": now,
    }
    if existing:
        supabase.table("comments").update(payload).eq("id", comment_id).execute()
    else:
        supabase.table("comments").insert(payload).execute()


def _upsert_post_reaction(post_id: str, user_id: str, reaction: str = "like") -> None:
    existing = (
        supabase.table("post_reactions")
        .select("postId,userId,reaction")
        .eq("postId", post_id)
        .eq("userId", user_id)
        .limit(1)
        .execute()
        .data
    ) or []
    if existing:
        (
            supabase.table("post_reactions")
            .update({"reaction": reaction})
            .eq("postId", post_id)
            .eq("userId", user_id)
            .execute()
        )
    else:
        supabase.table("post_reactions").insert({"postId": post_id, "userId": user_id, "reaction": reaction}).execute()


def _pick_demo_course_versions(limit: int = 7) -> list[str]:
    rows = (
        supabase.table("course_versions")
        .select("id,code,title")
        .order("updatedAt", desc=True)
        .limit(limit)
        .execute()
        .data
    ) or []
    course_ids = [row["id"] for row in rows if row.get("id")]
    if len(course_ids) < 6:
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
        ("DEMO-CG101", "Graph Foundations", "Intro", 101),
        ("DEMO-CG121", "Data Wrangling for Networks", "Intro", 121),
        ("DEMO-CG151", "Discrete Structures for Graphs", "Intro", 151),
        ("DEMO-CG201", "Network Algorithms", "Intermediate", 201),
        ("DEMO-CG231", "Graph Databases", "Intermediate", 231),
        ("DEMO-CG251", "Scalable Data Pipelines", "Intermediate", 251),
        ("DEMO-CG301", "Social Graph Systems", "Advanced", 301),
        ("DEMO-CG333", "Trust & Safety Graph Signals", "Advanced", 333),
        ("DEMO-CG351", "Graph ML in Production", "Advanced", 351),
        ("DEMO-CG401", "Distributed Graph Infrastructure", "Graduate", 401),
    ]
    version_ids: list[str] = []
    for code, title, difficulty, course_number in defs:
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
                    "courseNumber": str(course_number),
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
            "description": f"{title} demo course for planner and prerequisite graph testing.",
            "credits": 3,
            "department": "DEMO",
            "difficulty": difficulty,
            "tags": ["demo", "graph"],
        }
        if existing_version:
            supabase.table("course_versions").update(payload).eq("id", version_id).execute()
        else:
            supabase.table("course_versions").insert(payload).execute()

    # Irregular DAG for demos (asymmetric branches and merges, still acyclic):
    # 101 -> {121,151,201}
    # 121 -> {231,251}
    # 151 -> {251,301}
    # 201 -> 301
    # 231 -> {301,333}
    # 251 -> 333
    # 301 -> {351,401}
    # 333 -> 351
    # 351 -> 401
    edge_pairs = [
        ("DEMO-CG121", "DEMO-CG101"),
        ("DEMO-CG151", "DEMO-CG101"),
        ("DEMO-CG201", "DEMO-CG101"),
        ("DEMO-CG231", "DEMO-CG121"),
        ("DEMO-CG251", "DEMO-CG121"),
        ("DEMO-CG251", "DEMO-CG151"),
        ("DEMO-CG301", "DEMO-CG151"),
        ("DEMO-CG301", "DEMO-CG201"),
        ("DEMO-CG301", "DEMO-CG231"),
        ("DEMO-CG333", "DEMO-CG231"),
        ("DEMO-CG333", "DEMO-CG251"),
        ("DEMO-CG351", "DEMO-CG251"),
        ("DEMO-CG351", "DEMO-CG301"),
        ("DEMO-CG351", "DEMO-CG333"),
        ("DEMO-CG401", "DEMO-CG301"),
        ("DEMO-CG401", "DEMO-CG351"),
    ]
    edges = [
        (
            _stable_id(f"edge:{course_code}-{prereq_code}"),
            _stable_id(f"course-version:{course_code}"),
            _stable_id(f"course-version:{prereq_code}"),
        )
        for course_code, prereq_code in edge_pairs
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

    # Remove stale edges among the demo course versions so reruns keep a stable DAG.
    expected_edge_ids = {edge_id for edge_id, _, _ in edges}
    existing_from_demo = (
        supabase.table("course_prerequisite_edges")
        .select("id")
        .in_("courseVersionId", version_ids)
        .execute()
        .data
    ) or []
    existing_to_demo = (
        supabase.table("course_prerequisite_edges")
        .select("id")
        .in_("prerequisiteCourseVersionId", version_ids)
        .execute()
        .data
    ) or []
    candidate_ids = {row["id"] for row in [*existing_from_demo, *existing_to_demo] if row.get("id")}
    stale_ids = [edge_id for edge_id in candidate_ids if edge_id not in expected_edge_ids]
    for stale_id in stale_ids:
        supabase.table("course_prerequisite_edges").delete().eq("id", stale_id).execute()

    return version_ids


def clear_demo_data(current_user_id: str | None) -> None:
    demo_emails = {f"{p.key}.demo@nomad.local" for p in DEMO_PROFILES}
    demo_ids = [
        str(getattr(user, "id"))
        for user in _list_auth_users()
        if getattr(user, "email", None) in demo_emails and getattr(user, "id", None)
    ]
    participants = [*demo_ids, *( [current_user_id] if current_user_id else [] )]

    seeded_community_ids = [_stable_id(f"community:{community.key}") for community in DEMO_COMMUNITIES]
    seeded_post_ids = [_stable_id(f"post:{index}") for index in range(50)]
    seeded_comment_ids = [_stable_id(f"comment:{index}") for index in range(20)]

    if participants:
        (
            supabase.table("friendships")
            .delete()
            .in_("userId", participants)
            .in_("friendId", participants)
            .execute()
        )
        supabase.table("user_courses").delete().in_("userId", participants).eq("source", "demo_seed").execute()

    if seeded_post_ids:
        (
            supabase.table("post_reactions")
            .delete()
            .in_("postId", seeded_post_ids)
            .execute()
        )
        supabase.table("comments").delete().in_("id", seeded_comment_ids).execute()
        supabase.table("posts").delete().in_("id", seeded_post_ids).execute()
    if seeded_community_ids:
        supabase.table("community_members").delete().in_("communityId", seeded_community_ids).execute()
        supabase.table("communities").delete().in_("id", seeded_community_ids).execute()

    supabase.table("profiles").delete().in_("id", demo_ids).execute()
    print(
        f"Cleared demo profiles={len(demo_ids)}, communities={len(seeded_community_ids)}, "
        f"posts={len(seeded_post_ids)}, and related seeded edges/courses."
    )


def _seed_demo_communities_and_posts(user_ids: list[str]) -> None:
    if not user_ids:
        return

    community_ids = [_upsert_community(community) for community in DEMO_COMMUNITIES]
    for index, user_id in enumerate(user_ids):
        # Each user joins multiple communities to enrich feed and member discovery.
        for offset in range(3):
            community_id = community_ids[(index + offset) % len(community_ids)]
            _upsert_community_member(community_id, user_id)

    topics = [
        "study strategy",
        "project update",
        "exam prep",
        "networking tip",
        "course review",
        "hackathon planning",
        "internship prep",
        "design feedback",
        "database optimization",
        "graph modeling",
    ]
    hashtags = [
        "algorithms",
        "systems",
        "ml",
        "product",
        "career",
        "backend",
        "startups",
        "study",
        "research",
        "networking",
    ]
    calls_to_action = [
        "Anyone want to pair on this?",
        "Would love feedback from folks who tried this.",
        "Drop your approach below.",
        "Sharing notes in case this helps someone.",
        "Curious what worked for others.",
    ]

    for index in range(50):
        post_id = _stable_id(f"post:{index}")
        author_id = user_ids[index % len(user_ids)]
        community_id = community_ids[index % len(community_ids)]
        topic = topics[index % len(topics)]
        tag1 = hashtags[index % len(hashtags)]
        tag2 = hashtags[(index + 3) % len(hashtags)]
        title = f"Demo Post #{index + 1}: {topic.title()}"
        content = (
            f"Week {index % 8 + 1} update on {topic}. "
            f"Key takeaway: break large goals into focused sprints and review outcomes weekly. "
            f"{calls_to_action[index % len(calls_to_action)]} "
            f"#{tag1} #{tag2}"
        )
        _upsert_post(
            post_id=post_id,
            author_id=author_id,
            community_id=community_id,
            title=title,
            content=content,
            tags=["demo_seed", tag1, tag2, topic.replace(" ", "-")],
        )

        # Add realistic engagement: first 20 posts get one seeded comment.
        if index < 20:
            comment_id = _stable_id(f"comment:{index}")
            commenter = user_ids[(index + 1) % len(user_ids)]
            _upsert_comment(
                comment_id=comment_id,
                post_id=post_id,
                author_id=commenter,
                content=f"Helpful point on {topic}. I tested a similar workflow and it improved consistency.",
            )

        # Seed likes on a subset for "top" feed demos.
        if index % 2 == 0:
            liker_a = user_ids[(index + 2) % len(user_ids)]
            _upsert_post_reaction(post_id, liker_a, "like")
        if index % 3 == 0:
            liker_b = user_ids[(index + 3) % len(user_ids)]
            _upsert_post_reaction(post_id, liker_b, "like")


def seed_demo_data(current_user_id: str | None) -> None:
    demo_ids = {profile.key: _ensure_profile(profile) for profile in DEMO_PROFILES}
    course_ids = _ensure_demo_courses()

    alice = demo_ids["alice"]
    brandon = demo_ids["brandon"]
    chloe = demo_ids["chloe"]
    diego = demo_ids["diego"]
    emma = demo_ids["emma"]
    farah = demo_ids["farah"]

    # Connected graph among demo users for richer mutuals and graph density.
    connected_pairs = [
        (alice, brandon),
        (brandon, chloe),
        (brandon, diego),
        (chloe, emma),
        (emma, farah),
        (diego, farah),
    ]
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
    fifth = course_ids[4] if len(course_ids) > 4 else fourth
    sixth = course_ids[5] if len(course_ids) > 5 else fifth
    seventh = course_ids[6] if len(course_ids) > 6 else sixth

    _upsert_user_course(alice, base, "planned")
    _upsert_user_course(alice, second, "planned")
    _upsert_user_course(alice, third, "planned")
    _upsert_user_course(brandon, base, "planned")
    _upsert_user_course(brandon, third, "planned")
    _upsert_user_course(brandon, fourth, "planned")
    _upsert_user_course(chloe, base, "planned")
    _upsert_user_course(chloe, fourth, "planned")
    _upsert_user_course(chloe, fifth, "planned")
    _upsert_user_course(diego, second, "planned")
    _upsert_user_course(diego, third, "planned")
    _upsert_user_course(diego, sixth, "planned")
    _upsert_user_course(emma, third, "planned")
    _upsert_user_course(emma, fifth, "planned")
    _upsert_user_course(emma, sixth, "planned")
    _upsert_user_course(farah, fourth, "planned")
    _upsert_user_course(farah, sixth, "planned")
    _upsert_user_course(farah, seventh, "planned")

    if current_user_id:
        _upsert_user_course(current_user_id, base, "planned")
        _upsert_user_course(current_user_id, second, "planned")
        _upsert_user_course(current_user_id, third, "planned")
        _upsert_user_course(current_user_id, fourth, "planned")

    audience = [alice, brandon, chloe, diego, emma, farah]
    if current_user_id and current_user_id not in audience:
        audience.append(current_user_id)
    _seed_demo_communities_and_posts(audience)

    print("Seed complete.")
    print(f"Demo profile IDs: {demo_ids}")
    if current_user_id:
        print(f"Connected current user: {current_user_id}")
    print("Now open /app/planner and /app/my-courses to verify graph + mutuals.")


def seed_demo_dag_only() -> None:
    course_ids = _ensure_demo_courses()
    print(f"DAG-only seed complete. Demo course_versions upserted: {len(course_ids)}")
    print("Now open /app/planner to verify the prerequisite graph.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Supabase demo data for course connection graph.")
    parser.add_argument(
        "--user-id",
        dest="user_id",
        default=None,
        help="Optional current user id to connect to demo users and enroll in demo courses.",
    )
    parser.add_argument(
        "--user-email",
        dest="user_email",
        default=None,
        help="Optional current user email; resolves auth user id automatically for demo linking.",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear previously seeded demo data instead of seeding.",
    )
    parser.add_argument(
        "--dag-only",
        action="store_true",
        help="Seed only demo course DAG (no profiles, friendships, communities, or posts).",
    )
    args = parser.parse_args()

    if args.clear:
        current_user_id = _resolve_current_user_id(args.user_id, args.user_email)
        clear_demo_data(current_user_id)
        return

    if args.dag_only:
        seed_demo_dag_only()
        return

    current_user_id = _resolve_current_user_id(args.user_id, args.user_email)
    seed_demo_data(current_user_id)


if __name__ == "__main__":
    main()


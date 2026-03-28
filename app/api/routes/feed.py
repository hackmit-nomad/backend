from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import math
from typing import Literal
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from postgrest.exceptions import APIError

from app.api.deps import get_current_user_id
from app.db.supabase import supabase

router = APIRouter(tags=["Feed"])

Reaction = Literal["like", "celebrate", "insightful", "curious", "support"]


class CreatePostRequest(BaseModel):
    communityId: str | None = None
    title: str
    content: str
    tags: list[str] | None = None


class CreateReplyRequest(BaseModel):
    content: str
    parentCommentId: str | None = None


class UpdatePostRequest(BaseModel):
    title: str | None = None
    content: str | None = None
    tags: list[str] | None = None


class PostReactionRequest(BaseModel):
    reaction: Reaction


class CommentReactionResponse(BaseModel):
    commentId: str
    likes: int
    isLiked: bool


HASHTAG_PATTERN = re.compile(r"(^|[\s.,!?;:()\[\]{}])#([A-Za-z0-9][A-Za-z0-9_-]{0,31})")


def _extract_hashtags(text: str | None) -> list[str]:
    if not text:
        return []
    return [match.group(2) for match in HASHTAG_PATTERN.finditer(text)]


def _merge_tags(*tag_groups: list[str] | None) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for group in tag_groups:
        if not group:
            continue
        for raw in group:
            tag = raw.strip().lstrip("#")
            if not tag:
                continue
            key = tag.lower()
            if key in seen:
                continue
            seen.add(key)
            merged.append(tag[:32])
            if len(merged) >= 10:
                return merged
    return merged


def _normalize_tokens(values: list[str] | None) -> list[str]:
    if not values:
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        token = value.strip().lstrip("#").lower()
        if not token or token in seen:
            continue
        seen.add(token)
        cleaned.append(token)
    return cleaned


def _parse_csv_tokens(raw: str | None) -> list[str]:
    if not raw:
        return []
    return _normalize_tokens([part for part in raw.split(",") if part.strip()])


def _cosine_similarity(query_tokens: list[str], post_tokens: list[str]) -> float:
    if not query_tokens or not post_tokens:
        return 0.0
    query_counter = Counter(query_tokens)
    post_counter = Counter(post_tokens)
    shared = set(query_counter) & set(post_counter)
    if not shared:
        return 0.0
    dot_product = sum(query_counter[token] * post_counter[token] for token in shared)
    query_norm = math.sqrt(sum(v * v for v in query_counter.values()))
    post_norm = math.sqrt(sum(v * v for v in post_counter.values()))
    if query_norm == 0 or post_norm == 0:
        return 0.0
    return dot_product / (query_norm * post_norm)


def _list_comment_reactions(comment_ids: list[str]) -> list[dict]:
    if not comment_ids:
        return []
    try:
        return (
            supabase.table("comment_reactions")
            .select("commentId,userId,reaction")
            .in_("commentId", comment_ids)
            .execute()
            .data
        ) or []
    except Exception:
        # Keep feed listing resilient even if comment reactions are not provisioned yet.
        return []


@router.get("/posts")
def list_feed_posts(
    tab: str | None = Query(default="all"),
    communityId: str | None = Query(default=None),
    interests: str | None = Query(default=None),
    tags: str | None = Query(default=None),
    user_id: str = Depends(get_current_user_id),
) -> dict:
    query = (
        supabase.table("posts")
        .select("*, profiles!posts_authorId_fkey(id, displayName, avatarUrl)")
        .is_("deletedAt", "null")
    )
    if communityId:
        query = query.eq("communityId", communityId)
    posts = (query.order("createdAt", desc=True).execute().data) or []

    try:
        user_profile = (
            supabase.table("profiles")
            .select("interests,tags")
            .eq("id", user_id)
            .limit(1)
            .execute()
            .data
        ) or []
    except APIError as exc:
        # Backward-compatible path for databases that don't have profiles.tags yet.
        if "tags" in str(exc):
            user_profile = (
                supabase.table("profiles")
                .select("interests")
                .eq("id", user_id)
                .limit(1)
                .execute()
                .data
            ) or []
        else:
            raise
    profile = user_profile[0] if user_profile else {}
    profile_tokens = _normalize_tokens((profile.get("interests") or []) + (profile.get("tags") or []))
    interest_tokens = _parse_csv_tokens(interests)
    tag_tokens = _parse_csv_tokens(tags)
    query_tokens = _normalize_tokens(profile_tokens + interest_tokens + tag_tokens)

    scored_posts: list[tuple[float, dict]] = []
    for post in posts:
        post_tokens = _normalize_tokens((post.get("tags") or []) + _extract_hashtags(post.get("title")) + _extract_hashtags(post.get("content")))
        similarity = _cosine_similarity(query_tokens, post_tokens)
        if (interest_tokens or tag_tokens) and similarity <= 0:
            continue
        scored_posts.append((similarity, post))

    if query_tokens:
        scored_posts.sort(key=lambda row: row[0], reverse=True)

    items = [_post_to_api(post, user_id) for _, post in scored_posts]
    if tab == "top":
        items.sort(key=lambda item: item.get("likes", 0), reverse=True)
    return {"items": items, "total": len(items)}


@router.get("/posts/tags/trending")
def list_trending_tags(
    days: int = Query(default=3, ge=1, le=14),
    limit: int = Query(default=8, ge=1, le=50),
    communityId: str | None = Query(default=None),
) -> dict:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    query = (
        supabase.table("posts")
        .select("tags,createdAt")
        .is_("deletedAt", "null")
        .gte("createdAt", since)
    )
    if communityId:
        query = query.eq("communityId", communityId)
    rows = query.execute().data or []

    counts: Counter[str] = Counter()
    for row in rows:
        for tag in _normalize_tokens(row.get("tags") or []):
            counts[tag] += 1

    items = [{"tag": tag, "count": count} for tag, count in counts.most_common(limit)]
    return {"items": items, "total": len(items)}


@router.post("/posts", status_code=201)
def create_post(body: CreatePostRequest, user_id: str = Depends(get_current_user_id)) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    tags = _merge_tags(body.tags, _extract_hashtags(body.content), _extract_hashtags(body.title))
    data = {
        "authorId": user_id,
        "title": body.title,
        "content": body.content,
        "tags": tags,
        "createdAt": now,
        "updatedAt": now,
    }
    if body.communityId:
        data["communityId"] = body.communityId
    resp = supabase.table("posts").insert(data).execute()
    if not resp.data:
        raise HTTPException(status_code=500, detail="Failed to create post")
    return _post_to_api(resp.data[0], user_id)


@router.patch("/posts/{postId}")
def update_post(postId: str, body: UpdatePostRequest, user_id: str = Depends(get_current_user_id)) -> dict:
    payload = {k: v for k, v in body.model_dump().items() if v is not None}
    if {"title", "content", "tags"} & payload.keys():
        existing = supabase.table("posts").select("title,content,tags").eq("id", postId).single().execute().data
        if not existing:
            raise HTTPException(status_code=404, detail="Post not found")
        title = payload.get("title", existing.get("title"))
        content = payload.get("content", existing.get("content"))
        provided_tags = payload.get("tags", existing.get("tags"))
        payload["tags"] = _merge_tags(provided_tags, _extract_hashtags(content), _extract_hashtags(title))
    resp = supabase.table("posts").update(payload).eq("id", postId).eq("authorId", user_id).execute()
    if not resp.data:
        raise HTTPException(status_code=404, detail="Post not found")
    return _post_to_api(resp.data[0], user_id)


@router.delete("/posts/{postId}", status_code=204)
def delete_post(postId: str, user_id: str = Depends(get_current_user_id)) -> None:
    row = supabase.table("posts").select("id").eq("id", postId).eq("authorId", user_id).single().execute().data
    if not row:
        raise HTTPException(status_code=404, detail="Post not found")
    supabase.table("posts").delete().eq("id", postId).eq("authorId", user_id).execute()
    return None


@router.post("/posts/{postId}/reactions")
def react_to_post(
    postId: str,
    body: PostReactionRequest,
    user_id: str = Depends(get_current_user_id),
) -> dict:
    post = supabase.table("posts").select("*").eq("id", postId).single().execute().data
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    existing_rows = (
        supabase.table("post_reactions")
        .select("id,reaction")
        .eq("postId", postId)
        .eq("userId", user_id)
        .limit(1)
        .execute()
        .data
    ) or []
    existing = existing_rows[0] if existing_rows else None
    if existing and existing.get("reaction") == body.reaction:
        supabase.table("post_reactions").delete().eq("id", existing["id"]).execute()
    elif existing:
        supabase.table("post_reactions").update({"reaction": body.reaction}).eq("id", existing["id"]).execute()
    else:
        supabase.table("post_reactions").insert({"postId": postId, "userId": user_id, "reaction": body.reaction}).execute()
    return _post_to_api(post, user_id)


@router.post("/comments/{commentId}/reactions")
def react_to_comment(
    commentId: str,
    body: PostReactionRequest,
    user_id: str = Depends(get_current_user_id),
) -> CommentReactionResponse:
    comment = supabase.table("comments").select("id").eq("id", commentId).is_("deletedAt", "null").single().execute().data
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    try:
        existing_rows = (
            supabase.table("comment_reactions")
            .select("id,reaction")
            .eq("commentId", commentId)
            .eq("userId", user_id)
            .limit(1)
            .execute()
            .data
        ) or []
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Comment reactions are not available: {exc}") from exc
    existing = existing_rows[0] if existing_rows else None
    if existing and existing.get("reaction") == body.reaction:
        supabase.table("comment_reactions").delete().eq("id", existing["id"]).execute()
    elif existing:
        supabase.table("comment_reactions").update({"reaction": body.reaction}).eq("id", existing["id"]).execute()
    else:
        supabase.table("comment_reactions").insert({"commentId": commentId, "userId": user_id, "reaction": body.reaction}).execute()
    reactions = (supabase.table("comment_reactions").select("reaction,userId").eq("commentId", commentId).execute().data) or []
    likes = sum(1 for r in reactions if r.get("reaction") == "like")
    is_liked = any(r.get("userId") == user_id and r.get("reaction") == "like" for r in reactions)
    return CommentReactionResponse(commentId=commentId, likes=likes, isLiked=is_liked)


@router.post("/posts/{postId}/replies", status_code=201)
def reply_to_post(postId: str, body: CreateReplyRequest, user_id: str = Depends(get_current_user_id)) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    resp = (
        supabase.table("comments")
        .insert(
            {
                "postId": postId,
                "authorId": user_id,
                "content": body.content,
                "parentCommentId": body.parentCommentId or None,
                "createdAt": now,
                "updatedAt": now,
            }
        )
        .execute()
    )

    if not resp.data:
        raise HTTPException(status_code=500, detail="Failed to create reply")
    row = resp.data[0]
    reply = _reply_to_api(row)
    if not reply.get("timestamp"):
        reply["timestamp"] = now
    return reply


def _reply_to_api(r: dict, likes: int = 0, is_liked: bool = False, replies: list[dict] | None = None) -> dict:
    return {
        "id": r["id"],
        "authorId": r["authorId"],
        "content": r["content"],
        "timestamp": r.get("createdAt"),
        "likes": likes,
        "isLiked": is_liked,
        "childReplies": replies or [],
    }

def _post_to_api(p: dict, user_id: str) -> dict:
    reactions = (supabase.table("post_reactions").select("reaction,userId").eq("postId", p["id"]).execute().data) or []
    likes = sum(1 for r in reactions if r.get("reaction") == "like")
    my = next((r for r in reactions if r.get("userId") == user_id), None)

    comments_rows = (
        supabase.table("comments")
        .select("*")
        .eq("postId", p["id"])
        .is_("deletedAt", "null")
        .order("createdAt", desc=False)
        .execute()
        .data
    ) or []

    comment_ids = [r["id"] for r in comments_rows]
    comment_reactions = _list_comment_reactions(comment_ids)
    reactions_by_comment: dict[str, list[dict]] = {}
    for reaction in comment_reactions or []:
        cid = reaction.get("commentId")
        if not cid:
            continue
        reactions_by_comment.setdefault(cid, []).append(reaction)

    comment_by_id: dict[str, dict] = {}
    replies: list[dict] = []
    for r in comments_rows:
        row_reactions = reactions_by_comment.get(r["id"], [])
        comment_likes = sum(1 for reaction in row_reactions if reaction.get("reaction") == "like")
        comment_is_liked = any(
            reaction.get("userId") == user_id and reaction.get("reaction") == "like"
            for reaction in row_reactions
        )
        comment_by_id[r["id"]] = _reply_to_api(r, likes=comment_likes, is_liked=comment_is_liked, replies=[])

    for r in comments_rows:
        current = comment_by_id[r["id"]]
        parent_id = r.get("parentCommentId")
        if parent_id and parent_id in comment_by_id:
            comment_by_id[parent_id]["childReplies"].append(current)
        else:
            replies.append(current)

    profile = p.get("profiles")
    if isinstance(profile, list):
        profile = profile[0] if profile else {}
    if not isinstance(profile, dict):
        profile = {}

    return {
        "id": p["id"],
        "authorId": p.get("authorId"),
        "communityId": p.get("communityId"),
        "title": p.get("title") or "",
        "content": p.get("content") or "",
        "timestamp": p.get("createdAt"),
        "likes": likes,
        "author": {
            "id": p.get("authorId"),
            "name": profile.get("displayName"),
            "avatar": profile.get("avatarUrl"),
        },
        "isLiked": bool(my and my.get("reaction") == "like"),
        "tags": p.get("tags") or [],
        "replies": replies,
    }


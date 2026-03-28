from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

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


@router.get("/posts")
def list_feed_posts(
    tab: str | None = Query(default="all"),
    communityId: str | None = Query(default=None),
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
    items = [_post_to_api(p, user_id) for p in posts]
    return {"items": items, "total": len(items)}


@router.post("/posts", status_code=201)
def create_post(body: CreatePostRequest, user_id: str = Depends(get_current_user_id)) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    data = {
        "authorId": user_id,
        "title": body.title,
        "content": body.content,
        "tags": body.tags or [],
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
    supabase.table("post_reactions").upsert({"postId": postId, "userId": user_id, "reaction": body.reaction}).execute()
    post = supabase.table("posts").select("*").eq("id", postId).single().execute().data
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    return _post_to_api(post, user_id)


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


def _reply_to_api(r: dict, replies: list[dict] | None = None) -> dict:
    return {
        "id": r["id"],
        "authorId": r["authorId"],
        "content": r["content"],
        "timestamp": r.get("createdAt"),
        "likes": 0,
        "isLiked": False,
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

    print(comments_rows)
    comment_by_id: dict[str, dict] = {}
    replies: list[dict] = []
    for r in comments_rows:
        comment_by_id[r["id"]] = _reply_to_api(r, replies=[])

    for r in comments_rows:
        current = comment_by_id[r["id"]]
        parent_id = r.get("parentCommentId")
        if parent_id and parent_id in comment_by_id:
            comment_by_id[parent_id]["childReplies"].append(current)
        else:
            replies.append(current)


    print("REPLIES", replies)

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


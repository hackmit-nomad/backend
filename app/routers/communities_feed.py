from typing import Dict, List, Literal, Optional

from fastapi import APIRouter, Header, HTTPException

from ..db import supabase
from ..helpers import current_user_id, map_post_row, now_iso
from ..schemas import CreatePostRequest, CreateReplyRequest, Community, Post, PostReaction, Reply

router = APIRouter()


@router.get("/communities")
def list_communities(
    q: Optional[str] = None,
    joined: Optional[bool] = None,
    authorization: Optional[str] = Header(default=None),
):
    uid = current_user_id(authorization)
    rows = supabase.table("communities").select("*").execute().data or []
    items: List[Community] = []
    for row in rows:
        if q and q.lower() not in (row.get("name") or "").lower():
            continue
        is_joined = False
        if uid:
            is_joined = False
        if joined is None or is_joined == joined:
            items.append(
                Community(
                    id=row["id"],
                    name=row.get("name") or "",
                    description=row.get("introduction") or "",
                    icon=row.get("icon") or "",
                    color=row.get("color") or "#000000",
                    isJoined=is_joined,
                )
            )
    return {"items": items}


@router.get("/communities/{communityId}", response_model=Community)
def get_community(communityId: str):
    row = supabase.table("communities").select("*").eq("id", communityId).single().execute().data
    if not row:
        raise HTTPException(status_code=404, detail="Community not found")
    return Community(
        id=row["id"],
        name=row.get("name") or "",
        description=row.get("introduction") or "",
        icon=row.get("icon") or "",
        color=row.get("color") or "#000000",
    )


@router.post("/communities/{communityId}/join")
def join_community(communityId: str):
    _ = communityId
    return {"isJoined": True}


@router.delete("/communities/{communityId}/join")
def leave_community(communityId: str):
    _ = communityId
    return {"isJoined": False}


@router.get("/posts")
def list_posts(tab: Optional[Literal["all", "following", "top"]] = "all", communityId: Optional[str] = None):
    query = supabase.table("posts").select("*")
    if communityId:
        query = query.eq("communityId", communityId)
    rows = query.order("createdAt", desc=True).execute().data or []
    items = [map_post_row(r) for r in rows]
    if tab == "top":
        items.sort(key=lambda p: p.likes, reverse=True)
    return {"items": items, "total": len(items)}


@router.post("/posts", response_model=Post, status_code=201)
def create_post(body: CreatePostRequest, authorization: Optional[str] = Header(default=None)):
    uid = current_user_id(authorization)
    if not uid:
        raise HTTPException(status_code=401, detail="Unauthorized")
    rs = (
        supabase.table("posts")
        .insert(
            {
                "authorId": uid,
                "communityId": body.communityId,
                "title": body.title,
                "content": body.content,
                "tags": body.tags,
                "likes": 0,
            }
        )
        .execute()
    )
    if not rs.data:
        raise HTTPException(status_code=400, detail="Unable to create post")
    return map_post_row(rs.data[0])


@router.post("/posts/{postId}/reactions", response_model=Post)
def react_post(postId: str, body: Dict[str, PostReaction]):
    reaction = body.get("reaction")
    if not reaction:
        raise HTTPException(status_code=400, detail="reaction is required")
    row = supabase.table("posts").select("*").eq("id", postId).single().execute().data
    if not row:
        raise HTTPException(status_code=404, detail="Post not found")
    likes = int(row.get("likes") or 0) + 1
    updated = (
        supabase.table("posts")
        .update({"likes": likes, "myReaction": reaction, "isLiked": True})
        .eq("id", postId)
        .execute()
        .data
    )
    return map_post_row(updated[0]) if updated else map_post_row(row)


@router.post("/posts/{postId}/replies", response_model=Reply, status_code=201)
def reply_post(postId: str, body: CreateReplyRequest, authorization: Optional[str] = Header(default=None)):
    uid = current_user_id(authorization)
    if not uid:
        raise HTTPException(status_code=401, detail="Unauthorized")
    post = supabase.table("posts").select("id").eq("id", postId).single().execute().data
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    rs = (
        supabase.table("comments")
        .insert({"postId": postId, "authorId": uid, "content": body.content})
        .execute()
    )
    row = (rs.data or [None])[0]
    if not row:
        raise HTTPException(status_code=400, detail="Unable to create reply")
    return Reply(
        id=row["id"],
        authorId=row["authorId"],
        content=row["content"],
        timestamp=row.get("createdAt") or now_iso(),
        likes=0,
        isLiked=False,
    )

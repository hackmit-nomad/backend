import os
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client, Client


SUPABASE_URL: str = "https://hcvisecwcgupinlqghgr.supabase.co"
SUPABASE_KEY: str = os.environ.get("SUPABASE_KEY", "")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set in environment variables")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

app = FastAPI(title="Course Selection Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class Post(BaseModel):
    id: str
    authorId: str
    communityId: Optional[str] = None
    content: str
    attachments: Optional[Dict[str, Any]] = None
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None
    deletedAt: Optional[str] = None


class Comment(BaseModel):
    id: str
    postId: str
    authorId: str
    parentCommentId: Optional[str] = None
    content: str
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None
    deletedAt: Optional[str] = None


class Message(BaseModel):
    id: str
    chatId: str
    senderId: str
    content: str
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None
    deletedAt: Optional[str] = None


class Course(BaseModel):
    id: str
    schoolId: Optional[str] = None
    canonicalCode: Optional[str] = None
    canonicalName: Optional[str] = None
    creditsDefault: Optional[float] = None


class User(BaseModel):
    id: str
    email: Optional[str] = None
    displayName: Optional[str] = None
    avatarUrl: Optional[str] = None


class UserStats(BaseModel):
    postsCount: int = 0
    commentsCount: int = 0
    friendsCount: int = 0


@app.get("/")
async def root():
    return {"message": "nomad v0.0.1 beta"}


# ----- Posts & Comments -----


class CreatePostBody(BaseModel):
    authorId: str
    content: str
    communityId: Optional[str] = None


@app.post("/posts", response_model=Post)
def create_post(body: CreatePostBody):
    data = {
        "authorId": body.authorId,
        "content": body.content,
        "communityId": body.communityId,
    }
    resp = supabase.table("posts").insert(data).execute()
    if not resp.data:
        raise HTTPException(status_code=500, detail="Failed to create post")
    row = resp.data[0]
    return Post(
        id=row["id"],
        authorId=row["authorId"],
        communityId=row.get("communityId"),
        content=row["content"],
        attachments=row.get("attachments"),
        createdAt=row.get("createdAt"),
        updatedAt=row.get("updatedAt"),
        deletedAt=row.get("deletedAt"),
    )


@app.get("/posts/{post_id}")
def get_post(post_id: str):
    post_resp = supabase.table("posts").select("*").eq("id", post_id).single().execute()
    if not post_resp.data:
        raise HTTPException(status_code=404, detail="Post not found")

    comments_resp = (
        supabase.table("comments")
        .select("*")
        .eq("postId", post_id)
        .order("createdAt", desc=False)
        .execute()
    )
    comments = comments_resp.data or []
    return {
        "post": post_resp.data,
        "comments": comments,
    }


class UpdatePostBody(BaseModel):
    content: str


@app.put("/posts/{post_id}", response_model=Post)
def update_post(post_id: str, body: UpdatePostBody):
    resp = (
        supabase.table("posts")
        .update({"content": body.content})
        .eq("id", post_id)
        .execute()
    )
    if not resp.data:
        raise HTTPException(status_code=404, detail="Post not found")
    row = resp.data[0]
    return Post(
        id=row["id"],
        authorId=row["authorId"],
        communityId=row.get("communityId"),
        content=row["content"],
        attachments=row.get("attachments"),
        createdAt=row.get("createdAt"),
        updatedAt=row.get("updatedAt"),
        deletedAt=row.get("deletedAt"),
    )


@app.delete("/posts/{post_id}")
def delete_post(post_id: str):
    # Soft delete: set deletedAt instead of removing row
    resp = (
        supabase.table("posts")
        .update({"deletedAt": "now()"})
        .eq("id", post_id)
        .execute()
    )
    if not resp.data:
        raise HTTPException(status_code=404, detail="Post not found")
    return {"success": True}


class CreateCommentBody(BaseModel):
    authorId: str
    content: str
    parentCommentId: Optional[str] = None


@app.post("/posts/{post_id}/comments", response_model=Comment)
def create_comment(post_id: str, body: CreateCommentBody):
    # Ensure post exists
    post_resp = supabase.table("posts").select("id").eq("id", post_id).single().execute()
    if not post_resp.data:
        raise HTTPException(status_code=404, detail="Post not found")

    data = {
        "postId": post_id,
        "authorId": body.authorId,
        "content": body.content,
        "parentCommentId": body.parentCommentId,
    }
    resp = supabase.table("comments").insert(data).execute()
    if not resp.data:
        raise HTTPException(status_code=500, detail="Failed to create comment")
    row = resp.data[0]
    return Comment(
        id=row["id"],
        postId=row["postId"],
        authorId=row["authorId"],
        parentCommentId=row.get("parentCommentId"),
        content=row["content"],
        createdAt=row.get("createdAt"),
        updatedAt=row.get("updatedAt"),
        deletedAt=row.get("deletedAt"),
    )


@app.get("/posts/{post_id}/comments", response_model=List[Comment])
def list_comments(post_id: str):
    resp = (
        supabase.table("comments")
        .select("*")
        .eq("postId", post_id)
        .order("createdAt", desc=False)
        .execute()
    )
    return resp.data or []


class UpdateCommentBody(BaseModel):
    content: str


@app.put("/comments/{comment_id}", response_model=Comment)
def update_comment(comment_id: str, body: UpdateCommentBody):
    resp = (
        supabase.table("comments")
        .update({"content": body.content})
        .eq("id", comment_id)
        .execute()
    )
    if not resp.data:
        raise HTTPException(status_code=404, detail="Comment not found")
    row = resp.data[0]
    return Comment(
        id=row["id"],
        postId=row["postId"],
        authorId=row["authorId"],
        parentCommentId=row.get("parentCommentId"),
        content=row["content"],
        createdAt=row.get("createdAt"),
        updatedAt=row.get("updatedAt"),
        deletedAt=row.get("deletedAt"),
    )


# ----- Courses -----


@app.get("/course-list")
def get_course_list(userId: str):
    # All courses
    courses_resp = supabase.table("courses").select("*").execute()
    all_courses = courses_resp.data or []

    # User selected courses
    user_courses_resp = (
        supabase.table("user_courses")
        .select("*, courses(*)")
        .eq("userId", userId)
        .execute()
    )
    selected_courses = []
    if user_courses_resp.data:
        for row in user_courses_resp.data:
            course = row.get("courses")
            if course:
                selected_courses.append(course)

    # Placeholder for dependency validation
    invalid_dependency_courses: List[Dict[str, Any]] = []

    return {
        "selectedCourses": selected_courses,
        "invalidDependencyCourses": invalid_dependency_courses,
        "allCourses": all_courses,
    }


class UpdateCourseStateBody(BaseModel):
    userId: str
    courseId: str
    status: str


@app.post("/course-list")
def update_course_state(body: UpdateCourseStateBody):
    # Upsert into user_courses based on (userId, courseId)
    existing = (
        supabase.table("user_courses")
        .select("id")
        .eq("userId", body.userId)
        .eq("courseId", body.courseId)
        .execute()
    )

    if existing.data:
        supabase.table("user_courses").update(
            {"status": body.status}
        ).eq("id", existing.data[0]["id"]).execute()
    else:
        supabase.table("user_courses").insert(
            {
                "userId": body.userId,
                "courseId": body.courseId,
                "status": body.status,
            }
        ).execute()

    # Reuse getter
    return get_course_list(userId=body.userId)


@app.get("/courses/{course_id}")
def get_course_detail(course_id: str):
    course_resp = supabase.table("courses").select("*").eq("id", course_id).single().execute()
    if not course_resp.data:
        raise HTTPException(status_code=404, detail="Course not found")

    # Students: all users who have this course in user_courses
    user_courses_resp = (
        supabase.table("user_courses")
        .select("userId, profiles!inner(*)")
        .eq("courseId", course_id)
        .execute()
    )
    students = []
    if user_courses_resp.data:
        for row in user_courses_resp.data:
            profile = row.get("profiles")
            if profile:
                students.append(profile)

    return {
        "course": course_resp.data,
        "students": students,
    }


# ----- Auth (simplified, using Supabase auth) -----


class RegisterBody(BaseModel):
    name: str
    email: str
    password: str


@app.post("/auth/register")
def auth_register(body: RegisterBody):
    # Create auth user
    auth_resp = supabase.auth.sign_up(
        {"email": body.email, "password": body.password}
    )
    user = auth_resp.user
    if not user:
        raise HTTPException(status_code=400, detail="Failed to register user")

    # Create profile row
    supabase.table("profiles").insert(
        {
            "id": user.id,
            "email": body.email,
            "displayName": body.name,
        }
    ).execute()

    return {
        "user": {
            "id": user.id,
            "email": user.email,
            "displayName": body.name,
        },
        "token": auth_resp.session.access_token if auth_resp.session else None,
    }


class LoginBody(BaseModel):
    email: str
    password: str


@app.post("/auth/login")
def auth_login(body: LoginBody):
    auth_resp = supabase.auth.sign_in_with_password(
        {"email": body.email, "password": body.password}
    )
    session = auth_resp.session
    if not session or not session.user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    profile_resp = (
        supabase.table("profiles")
        .select("*")
        .eq("id", session.user.id)
        .single()
        .execute()
    )

    return {
        "user": profile_resp.data
        if profile_resp.data
        else {
            "id": session.user.id,
            "email": session.user.email,
        },
        "token": session.access_token,
    }


class AuthCheckBody(BaseModel):
    token: str


@app.post("/auth-check")
def auth_check(body: AuthCheckBody):
    try:
        session = supabase.auth.get_user(body.token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = session.user if hasattr(session, "user") else None
    if not user:
        return {"valid": False, "user": None}

    profile_resp = (
        supabase.table("profiles")
        .select("*")
        .eq("id", user.id)
        .single()
        .execute()
    )
    return {
        "valid": True,
        "user": profile_resp.data
        if profile_resp.data
        else {
            "id": user.id,
            "email": user.email,
        },
    }


# ----- Users & Social -----


@app.get("/users/{user_id}")
def get_user_profile(user_id: str):
    profile_resp = (
        supabase.table("profiles").select("*").eq("id", user_id).single().execute()
    )
    if not profile_resp.data:
        raise HTTPException(status_code=404, detail="User not found")

    # Basic stats
    posts_count = (
        supabase.table("posts").select("id", count="exact").eq("authorId", user_id).execute()
    ).count or 0
    comments_count = (
        supabase.table("comments")
        .select("id", count="exact")
        .eq("authorId", user_id)
        .execute()
    ).count or 0
    friends_count = (
        supabase.table("friendships")
        .select("id", count="exact")
        .eq("userId", user_id)
        .execute()
    ).count or 0

    stats = {
        "postsCount": posts_count,
        "commentsCount": comments_count,
        "friendsCount": friends_count,
    }

    # Placeholder tags & interests
    tags: List[str] = []
    interests: List[str] = []

    return {
        "user": profile_resp.data,
        "profilePictureUrl": profile_resp.data.get("avatarUrl"),
        "stats": stats,
        "tags": tags,
        "interests": interests,
    }


@app.get("/connect")
def connect(id: str):
    # Check if NFC tag or invite exists
    tag_resp = supabase.table("nfc_tags").select("*").eq("tagUid", id).single().execute()
    exists = bool(tag_resp.data)
    next_route = "/connect" if exists else "/register"
    return {"id": id, "exists": exists, "nextRoute": next_route}


@app.get("/register")
def register_flow(id: str):
    # For now, validInvite == NFC tag exists but not claimed
    tag_resp = supabase.table("nfc_tags").select("*").eq("tagUid", id).single().execute()
    valid_invite = bool(tag_resp.data and not tag_resp.data.get("claimedByUserId"))
    next_route = "/register" if valid_invite else "/connect"
    return {"id": id, "validInvite": valid_invite, "nextRoute": next_route}


@app.get("/nfc")
def nfc_route(id: str):
    tag_resp = supabase.table("nfc_tags").select("*").eq("tagUid", id).single().execute()
    registered = bool(tag_resp.data and tag_resp.data.get("claimedByUserId"))
    next_route = "/connect" if registered else "/register"
    return {"id": id, "registered": registered, "nextRoute": next_route}


# ----- Chats & Messages -----


class CreateMessageBody(BaseModel):
    senderId: str
    content: str


@app.post("/chats/{chat_id}/messages", response_model=Message)
def create_message(chat_id: str, body: CreateMessageBody):
    # Ensure chat exists
    chat_resp = supabase.table("chats").select("id").eq("id", chat_id).single().execute()
    if not chat_resp.data:
        raise HTTPException(status_code=404, detail="Chat not found")

    data = {
        "chatId": chat_id,
        "senderId": body.senderId,
        "content": body.content,
    }
    resp = supabase.table("messages").insert(data).execute()
    if not resp.data:
        raise HTTPException(status_code=500, detail="Failed to create message")
    row = resp.data[0]

    # Socket emitter placeholder: integrate with WebSocket / pub-sub layer if needed

    return Message(
        id=row["id"],
        chatId=row["chatId"],
        senderId=row["senderId"],
        content=row["content"],
        createdAt=row.get("createdAt"),
        updatedAt=row.get("updatedAt"),
        deletedAt=row.get("deletedAt"),
    )


@app.get("/chats/{chat_id}/messages", response_model=List[Message])
def list_messages(chat_id: str):
    resp = (
        supabase.table("messages")
        .select("*")
        .eq("chatId", chat_id)
        .order("createdAt", desc=False)
        .execute()
    )
    messages: List[Message] = []
    for row in resp.data or []:
        messages.append(
            Message(
                id=row["id"],
                chatId=row["chatId"],
                senderId=row["senderId"],
                content=row["content"],
                createdAt=row.get("createdAt"),
                updatedAt=row.get("updatedAt"),
                deletedAt=row.get("deletedAt"),
            )
        )
    return messages


class UpdateMessageBody(BaseModel):
    content: str


@app.put("/messages/{message_id}", response_model=Message)
def update_message(message_id: str, body: UpdateMessageBody):
    resp = (
        supabase.table("messages")
        .update({"content": body.content})
        .eq("id", message_id)
        .execute()
    )
    if not resp.data:
        raise HTTPException(status_code=404, detail="Message not found")
    row = resp.data[0]
    return Message(
        id=row["id"],
        chatId=row["chatId"],
        senderId=row["senderId"],
        content=row["content"],
        createdAt=row.get("createdAt"),
        updatedAt=row.get("updatedAt"),
        deletedAt=row.get("deletedAt"),
    )


@app.delete("/messages/{message_id}")
def delete_message(message_id: str):
    resp = (
        supabase.table("messages")
        .update({"deletedAt": "now()"})
        .eq("id", message_id)
        .execute()
    )
    if not resp.data:
        raise HTTPException(status_code=404, detail="Message not found")
    return {"success": True}


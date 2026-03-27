from typing import List, Literal, Optional

from pydantic import BaseModel, EmailStr, Field

Difficulty = Literal["Intro", "Intermediate", "Advanced", "Graduate"]
PostReaction = Literal["like", "celebrate", "insightful", "curious", "support"]
ConnectionStatus = Literal["none", "pending", "incoming", "connected"]
EventType = Literal["class", "study", "social", "deadline", "custom"]
NotificationType = Literal[
    "connection_request",
    "endorsement",
    "post_reaction",
    "mention",
    "profile_view",
]


class SignupRequest(BaseModel):
    name: str
    email: EmailStr
    password: str = Field(min_length=8)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UpdateUserRequest(BaseModel):
    name: Optional[str] = None
    bio: Optional[str] = None
    headline: Optional[str] = None
    major: Optional[str] = None
    minor: Optional[str] = None
    year: Optional[str] = None
    interests: Optional[List[str]] = None


class User(BaseModel):
    id: str
    name: str
    avatar: str = ""
    university: str = ""
    major: str = ""
    minor: Optional[str] = None
    year: str = ""
    bio: str = ""
    headline: Optional[str] = None
    interests: List[str] = []
    courses: List[str] = []
    communities: List[str] = []
    isConnected: bool = False
    isOnline: bool = False
    profileViews: int = 0


class AuthResponse(BaseModel):
    accessToken: str
    refreshToken: Optional[str] = None
    user: User


class Skill(BaseModel):
    name: str
    endorsements: int = 0
    endorsedBy: List[str] = []


class Experience(BaseModel):
    title: str
    company: str
    period: str
    description: str
    type: Literal["internship", "research", "club", "project"]


class UserProfile(User):
    skills: List[Skill] = []
    experience: List[Experience] = []


class Course(BaseModel):
    id: str
    code: str
    title: str
    credits: int
    description: str = ""
    department: str = ""
    difficulty: Difficulty = "Intro"
    prerequisites: List[str] = []
    nextCourses: List[str] = []
    tags: List[str] = []
    rating: float = 0.0
    students: List[str] = []


class CourseDetails(Course):
    knownClassmates: List[User] = []
    suggestedClassmates: List[User] = []


class PlannerState(BaseModel):
    courseIds: List[str] = []


class UpdatePlannerRequest(BaseModel):
    courseIds: List[str]


class Community(BaseModel):
    id: str
    name: str
    description: str = ""
    icon: str = ""
    banner: Optional[str] = None
    color: str = "#000000"
    members: int = 0
    posts: int = 0
    tags: List[str] = []
    isJoined: bool = False
    university: Optional[str] = None


class Reply(BaseModel):
    id: str
    authorId: str
    content: str
    timestamp: str
    likes: int = 0
    isLiked: bool = False


class Post(BaseModel):
    id: str
    authorId: str
    communityId: str
    title: str
    content: str
    timestamp: str
    likes: int = 0
    isLiked: bool = False
    myReaction: Optional[PostReaction] = None
    tags: List[str] = []
    replies: List[Reply] = []


class CreatePostRequest(BaseModel):
    communityId: str
    title: str
    content: str
    tags: List[str] = []


class CreateReplyRequest(BaseModel):
    content: str


class ConnectionStatusResponse(BaseModel):
    userId: str
    status: ConnectionStatus


class Conversation(BaseModel):
    id: str
    participants: List[str] = []
    isGroup: bool = False
    groupName: Optional[str] = None
    lastMessage: str = ""
    lastTimestamp: Optional[str] = None
    unread: int = 0


class CreateConversationRequest(BaseModel):
    participants: List[str]
    isGroup: bool = False
    groupName: Optional[str] = None


class Message(BaseModel):
    id: str
    senderId: str
    content: str
    timestamp: str


class CreateMessageRequest(BaseModel):
    content: str


class CalendarEvent(BaseModel):
    id: str
    title: str
    date: str
    startTime: str
    endTime: str
    location: Optional[str] = None
    type: EventType
    color: str = "#4f46e5"


class CreateCalendarEventRequest(BaseModel):
    title: str
    date: str
    startTime: str
    endTime: str
    location: Optional[str] = None
    type: EventType


class UpdateCalendarEventRequest(BaseModel):
    title: Optional[str] = None
    date: Optional[str] = None
    startTime: Optional[str] = None
    endTime: Optional[str] = None
    location: Optional[str] = None
    type: Optional[EventType] = None


class Notification(BaseModel):
    id: str
    type: NotificationType
    fromId: str
    content: str
    timestamp: str
    read: bool = False


class OnboardingCompleteRequest(BaseModel):
    university: str
    fullName: str
    majors: List[str]
    minors: List[str] = []
    interests: List[str] = []


class SearchResponse(BaseModel):
    users: List[User] = []
    courses: List[Course] = []
    communities: List[Community] = []
    posts: List[Post] = []

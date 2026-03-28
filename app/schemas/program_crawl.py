"""
Pydantic models for POST /api/ingest/program-crawl (strict schema, extra=forbid).
"""

from __future__ import annotations

import re
from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

# --- Regex / constrained types ---

_DATE_STR = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_STR = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_NORMALIZED_CODE = re.compile(r"^[A-Z0-9]+$")


def _parse_date_strict(v: Any) -> date | None:
    if v is None:
        return None
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, str):
        if not _DATE_STR.match(v):
            raise ValueError("Date must be YYYY-MM-DD or null")
        y, m, d = (int(x) for x in v.split("-"))
        return date(y, m, d)
    raise ValueError("Invalid date")


def _validate_time_str(v: Any) -> str | None:
    if v is None:
        return None
    if not isinstance(v, str):
        raise ValueError("Time must be string HH:mm or null")
    if not _TIME_STR.match(v):
        raise ValueError("Time must be HH:mm (24h) or null")
    return v


class ConfidenceLevel(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


class ProgramVersionSourceType(str, Enum):
    catalog = "catalog"
    pdf = "pdf"
    html = "html"
    manual = "manual"
    other = "other"


class ProgramVersionStatus(str, Enum):
    draft = "draft"
    pending = "pending"
    processed = "processed"
    failed = "failed"


class DeliveryMode(str, Enum):
    in_person = "In Person"
    online = "Online"
    hybrid = "Hybrid"
    async_ = "Async"


class SectionSourceType(str, Enum):
    official_schedule = "official_schedule"
    third_party = "third_party"
    inferred = "inferred"


class MetaConfidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    program: ConfidenceLevel
    catalog: ConfidenceLevel
    schedule: ConfidenceLevel


class Meta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    programUrl: HttpUrl | None = None
    catalogUrl: HttpUrl | None = None
    scheduleUrl: HttpUrl | None = None
    retrievedAt: datetime | None = None
    confidence: MetaConfidence
    warnings: list[str] | None = None


class School(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    country: str
    website: HttpUrl | None = None
    timezone: str


class Program(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    degreeLevel: str
    departmentName: str | None = None


class ProgramVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    catalogYear: int | None = None
    versionLabel: str | None = None
    sourceType: ProgramVersionSourceType
    sourceUrl: HttpUrl | None = None
    sourceFilePath: str | None = None
    sourceHash: str | None = None
    status: ProgramVersionStatus


class Category(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    categoryType: str
    parentName: str | None = None
    minCourses: int | None = None
    minCredits: float | None = None
    maxCourses: int | None = None
    note: str | None = None
    sortOrder: int | None = None


class CourseIngest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    canonicalCode: str | None = None
    canonicalName: str
    normalizedCode: str
    normalizedName: str | None = None
    subjectCode: str | None = None
    courseNumber: str | None = None
    creditsDefault: float | None = None

    @field_validator("normalizedCode")
    @classmethod
    def normalized_code_format(cls, v: str) -> str:
        if not _NORMALIZED_CODE.match(v):
            raise ValueError(
                "normalizedCode must be uppercase letters/digits only, no spaces or hyphens (e.g. CS101)"
            )
        return v


class CourseVersionIngest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    catalogYear: int | None = None
    code: str
    title: str
    description: str | None = None
    credits: float | None = None
    hours: str | None = None
    language: str | None = None
    grading: str | None = None
    rawText: str | None = None
    department: str | None = None
    difficulty: str | None = None
    tags: list[str] | None = None


class PrerequisiteRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rawText: str | None = None
    parsedJson: dict[str, Any] | None = None


class CourseCatalogEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    categoryName: str
    requirementType: str
    termRecommendation: str | None = None
    creditsCounted: float | None = None
    note: str | None = None
    course: CourseIngest
    courseVersion: CourseVersionIngest
    prerequisiteRule: PrerequisiteRule | None = None


class CourseLookup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    normalizedCode: str

    @field_validator("normalizedCode")
    @classmethod
    def nk(cls, v: str) -> str:
        if not _NORMALIZED_CODE.match(v):
            raise ValueError("courseLookup.normalizedCode must match normalized code rules (uppercase, no spaces)")
        return v


class SectionIngest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    termCode: str
    sectionCode: str
    instructor: str | None = None
    capacity: int | None = None
    campus: str | None = None
    deliveryMode: DeliveryMode
    uniqueKey: str | None = None


class Meeting(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dayOfWeek: int | None = Field(default=None, ge=1, le=7)
    startTime: str | None = None
    endTime: str | None = None
    timezone: str | None = None
    startDate: date | None = None
    endDate: date | None = None
    location: str | None = None
    locationExtra: dict[str, Any] | None = None
    recurrence: str | None = None
    weeks: str | None = None

    @field_validator("startTime", "endTime", mode="before")
    @classmethod
    def time_fmt(cls, v: Any) -> str | None:
        return _validate_time_str(v)

    @field_validator("startDate", "endDate", mode="before")
    @classmethod
    def date_fmt(cls, v: Any) -> date | None:
        return _parse_date_strict(v)


class SectionOffering(BaseModel):
    model_config = ConfigDict(extra="forbid")

    courseLookup: CourseLookup
    section: SectionIngest
    meetings: list[Meeting]
    sourceUrl: HttpUrl | None = None
    sourceType: SectionSourceType


class ProgramCrawlIngestPayload(BaseModel):
    """Top-level ingestion document."""

    model_config = ConfigDict(extra="forbid")

    meta: Meta
    school: School
    program: Program
    programVersion: ProgramVersion
    categories: list[Category]
    courseCatalogEntries: list[CourseCatalogEntry]
    sectionOfferings: list[SectionOffering]

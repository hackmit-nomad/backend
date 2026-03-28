"""Business rules on top of Pydantic-validated ProgramCrawlIngestPayload."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from app.schemas.program_crawl import Meeting, ProgramCrawlIngestPayload

_CANONICAL_LIKE = re.compile(r"^[A-Za-z]{2,10}\s*\d{2,4}[A-Za-z]?$")


def _time_to_minutes(t: str) -> int:
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def validate_program_crawl_business(payload: ProgramCrawlIngestPayload) -> tuple[list[str], list[str]]:
    """
    Returns (errors, warnings). Errors block ingestion; warnings are returned on success.
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not payload.courseCatalogEntries and not payload.sectionOfferings:
        errors.append(
            "At least one of courseCatalogEntries or sectionOfferings must be non-empty "
            "(catalog data or schedule data required)."
        )

    pv = payload.programVersion
    if pv.catalogYear is not None:
        if pv.catalogYear < 2000 or pv.catalogYear > 2100:
            errors.append(f"programVersion.catalogYear must be between 2000 and 2100, got {pv.catalogYear}.")

    # uniqueKey uniqueness
    keys: list[str] = []
    for i, so in enumerate(payload.sectionOfferings):
        uk = so.section.uniqueKey
        if uk:
            if uk in keys:
                errors.append(f"sectionOfferings[{i}].section.uniqueKey duplicates value '{uk}'.")
            keys.append(uk)

    # course catalog entries
    for i, entry in enumerate(payload.courseCatalogEntries):
        c = entry.course
        if c.canonicalCode is not None and c.normalizedCode:
            if not _looks_consistent_canonical_normalized(c.canonicalCode, c.normalizedCode):
                errors.append(
                    f"courseCatalogEntries[{i}].course: normalizedCode '{c.normalizedCode}' "
                    f"does not match expected pattern for canonicalCode '{c.canonicalCode}'."
                )

    # section offerings meetings
    for si, so in enumerate(payload.sectionOfferings):
        if not isinstance(so.meetings, list):
            errors.append(f"sectionOfferings[{si}].meetings must be an array.")
            continue
        for mi, m in enumerate(so.meetings):
            _meeting_rules(si, mi, m, errors, warnings)

    return errors, warnings


def _looks_consistent_canonical_normalized(canonical: str, normalized: str) -> bool:
    """Heuristic: normalized should be alnum compact form of canonical (e.g. CS 101 -> CS101)."""
    compact = re.sub(r"[^A-Za-z0-9]", "", canonical).upper()
    if compact == normalized:
        return True
    if _CANONICAL_LIKE.match(canonical.strip()) and len(normalized) >= 2:
        return normalized in compact or compact.startswith(normalized)
    return len(normalized) >= 2


def _meeting_rules(si: int, mi: int, m: Meeting, errors: list[str], warnings: list[str]) -> None:
    prefix = f"sectionOfferings[{si}].meetings[{mi}]"

    if m.startTime is not None and m.endTime is not None:
        if _time_to_minutes(m.startTime) >= _time_to_minutes(m.endTime):
            errors.append(f"{prefix}: startTime must be strictly before endTime when both are set.")

    if m.startDate is not None and m.endDate is not None:
        if m.startDate > m.endDate:
            errors.append(f"{prefix}: startDate must be <= endDate when both are set.")

    if m.timezone is None or (isinstance(m.timezone, str) and not m.timezone.strip()):
        warnings.append(f"{prefix}: timezone is empty; recommended for schedule data.")

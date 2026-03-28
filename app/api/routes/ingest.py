"""Service-to-service program crawl ingestion (Dify / AI JSON)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.core.config import INGEST_API_TOKEN
from app.ingest.program_crawl_validate import validate_program_crawl_business
from app.schemas.program_crawl import ProgramCrawlIngestPayload

router = APIRouter(prefix="/api/ingest", tags=["Ingest"])


def _format_pydantic_errors(exc: ValidationError) -> list[str]:
    out: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(x) for x in err.get("loc", ()) if x != "body")
        msg = err.get("msg", "invalid")
        typ = err.get("type", "")
        if loc:
            out.append(f"{loc}: {msg} ({typ})")
        else:
            out.append(f"{msg} ({typ})")
    return out


def _auth_error_response(request: Request) -> JSONResponse | None:
    if not INGEST_API_TOKEN:
        return JSONResponse(
            status_code=503,
            content={
                "success": False,
                "message": "Ingest API not configured",
                "errors": ["Set INGEST_API_TOKEN environment variable on the server"],
            },
        )
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if not auth or not auth.lower().startswith("bearer "):
        return JSONResponse(
            status_code=401,
            content={
                "success": False,
                "message": "Unauthorized",
                "errors": ["Authorization header must be: Bearer <token>"],
            },
        )
    token = auth.split(" ", 1)[1].strip()
    if token != INGEST_API_TOKEN:
        return JSONResponse(
            status_code=401,
            content={
                "success": False,
                "message": "Unauthorized",
                "errors": ["Invalid ingest token"],
            },
        )
    return None


@router.post("/program-crawl")
def post_program_crawl(request: Request, body: dict[str, Any] = Body(...)) -> Any:
    auth_err = _auth_error_response(request)
    if auth_err is not None:
        return auth_err

    try:
        payload = ProgramCrawlIngestPayload.model_validate(body)
    except ValidationError as e:
        return JSONResponse(
            status_code=422,
            content={
                "success": False,
                "message": "Schema validation failed",
                "errors": _format_pydantic_errors(e),
            },
        )

    biz_errors, warnings = validate_program_crawl_business(payload)
    if biz_errors:
        return JSONResponse(
            status_code=422,
            content={
                "success": False,
                "message": "Business validation failed",
                "errors": biz_errors,
            },
        )

    validated = payload.model_dump(mode="json")
    return {
        "success": True,
        "message": "Payload validated successfully",
        "summary": {
            "schoolName": payload.school.name,
            "programName": payload.program.name,
            "catalogYear": payload.programVersion.catalogYear,
            "categoriesCount": len(payload.categories),
            "courseCatalogEntriesCount": len(payload.courseCatalogEntries),
            "sectionOfferingsCount": len(payload.sectionOfferings),
            "warnings": warnings,
        },
        "validatedPayload": validated,
    }

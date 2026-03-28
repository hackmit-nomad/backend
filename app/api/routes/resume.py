from __future__ import annotations

import json
import re
from io import BytesIO
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File

from app.api.deps import get_current_user_id
from app.core.config import DIFY_API_KEY

router = APIRouter(tags=["Resume"])

DIFY_BASE_URL = "https://api.dify.ai/v1"

# Supported MIME types for resume upload
ALLOWED_TYPES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB


def _extract_text(data: bytes, content_type: str) -> str:
    """Extract plain text from uploaded file bytes."""
    if content_type == "text/plain":
        return data.decode("utf-8", errors="replace")

    if content_type == "application/pdf":
        try:
            from PyPDF2 import PdfReader
            reader = PdfReader(BytesIO(data))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception:
            raise HTTPException(status_code=400, detail="Could not extract text from PDF")

    if content_type in (
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ):
        try:
            import docx
            doc = docx.Document(BytesIO(data))
            return "\n".join(p.text for p in doc.paragraphs)
        except Exception:
            raise HTTPException(status_code=400, detail="Could not extract text from DOCX")

    raise HTTPException(status_code=400, detail=f"Unsupported file type: {content_type}")


async def _call_dify(resume_text: str, user_id: str) -> list[str]:
    """Call the Dify 'Resume tag extractor' workflow to extract tags."""
    if not DIFY_API_KEY:
        raise HTTPException(status_code=503, detail="Dify API key not configured")

    url = f"{DIFY_BASE_URL}/workflows/run"

    payload = {
        "inputs": {"resume_text": resume_text},
        "response_mode": "blocking",
        "user": user_id,
    }

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {DIFY_API_KEY}"},
        )
        if resp.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail=f"Dify API error: {resp.status_code} - {resp.text[:300]}",
            )

    result = resp.json()

    # Dify workflow response: data.outputs.tags contains the LLM output
    outputs = result.get("data", {}).get("outputs", {})
    raw_tags = outputs.get("tags", "")

    # The LLM returns a JSON array string — parse it
    if isinstance(raw_tags, list):
        return [str(t).strip() for t in raw_tags if isinstance(t, str) and t.strip()]

    cleaned = str(raw_tags).strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        tags = json.loads(cleaned)
        if isinstance(tags, list):
            return [str(t).strip() for t in tags if isinstance(t, str) and t.strip()]
    except json.JSONDecodeError:
        pass

    # Fallback: find a JSON array anywhere in the text
    match = re.search(r"\[.*?\]", cleaned, re.DOTALL)
    if match:
        try:
            tags = json.loads(match.group())
            if isinstance(tags, list):
                return [str(t).strip() for t in tags if isinstance(t, str) and t.strip()]
        except json.JSONDecodeError:
            pass

    raise HTTPException(status_code=502, detail="Failed to parse tags from Dify response")


@router.post("/api/parse-resume")
async def parse_resume(
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user_id),
) -> dict[str, Any]:
    """Upload a CV/resume file, extract text, and send to Dify workflow for tag extraction."""
    if file.content_type and file.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {file.content_type}")

    data = await file.read()
    if len(data) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File too large (max 5MB)")
    if len(data) == 0:
        raise HTTPException(status_code=400, detail="Empty file")

    content_type = file.content_type or "application/octet-stream"
    text = _extract_text(data, content_type)

    if not text.strip():
        raise HTTPException(status_code=400, detail="No readable text found in file")

    tags = await _call_dify(text, user_id)
    return {"tags": tags}

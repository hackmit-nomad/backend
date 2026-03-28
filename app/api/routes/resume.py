from __future__ import annotations

import json
import re
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File

from app.api.deps import get_current_user_id
from app.core.config import OPENAI_API_KEY
from app.utils.text_extraction import extract_text, ExtractionError

router = APIRouter(tags=["Resume"])

ALLOWED_TYPES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB

OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"


async def _call_openai(resume_text: str) -> list[str]:
    """Send extracted resume text to OpenAI and get back skill tags."""
    if not OPENAI_API_KEY:
        raise HTTPException(status_code=503, detail="OpenAI API key not configured")

    system_prompt = (
        "You are an expert resume analyzer. Extract professional skills, technical competencies, "
        "and expertise tags from the resume text provided. "
        "Return ONLY a JSON array of short tag strings (1-4 words each, lowercase). "
        "Focus on: programming languages, frameworks, tools, methodologies, soft skills, "
        "domain expertise, and certifications. Return 10-25 tags. "
        'Example: ["python", "machine learning", "react.js", "agile methodology"]. '
        "Return ONLY the JSON array, no other text."
    )

    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": resume_text},
        ],
        "temperature": 0.2,
        "max_tokens": 512,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            OPENAI_API_URL,
            json=payload,
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
        )
        if resp.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail=f"OpenAI API error: {resp.status_code} - {resp.text[:300]}",
            )

    raw_text = resp.json()["choices"][0]["message"]["content"].strip()

    cleaned = raw_text
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        tags = json.loads(cleaned)
        if isinstance(tags, list):
            return [str(t).strip() for t in tags if isinstance(t, str) and t.strip()]
    except json.JSONDecodeError:
        pass

    match = re.search(r"\[.*?\]", cleaned, re.DOTALL)
    if match:
        try:
            tags = json.loads(match.group())
            if isinstance(tags, list):
                return [str(t).strip() for t in tags if isinstance(t, str) and t.strip()]
        except json.JSONDecodeError:
            pass

    raise HTTPException(status_code=502, detail="Failed to parse tags from OpenAI response")


@router.post("/api/parse-resume")
async def parse_resume(
    file: UploadFile = File(...),
    _user_id: str = Depends(get_current_user_id),
) -> dict[str, Any]:
    """Upload a CV/resume, extract text, and return skill tags via OpenAI."""
    if file.content_type and file.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {file.content_type}")

    data = await file.read()
    if len(data) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File too large (max 5MB)")
    if len(data) == 0:
        raise HTTPException(status_code=400, detail="Empty file")

    content_type = file.content_type or "application/octet-stream"
    try:
        text = extract_text(data, content_type)
    except ExtractionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    tags = await _call_openai(text)
    return {"tags": tags}

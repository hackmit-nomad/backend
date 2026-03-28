"""Standalone text extraction utilities for PDF, DOCX, and plain-text files.

No FastAPI or database imports — safe to test in isolation.
"""

from __future__ import annotations

from io import BytesIO


class ExtractionError(Exception):
    """Raised when text cannot be extracted from a file."""


def extract_text(data: bytes, content_type: str) -> str:
    """Extract plain text from file bytes based on MIME type.

    Raises:
        ExtractionError: if the file cannot be read or contains no text.
    """
    if content_type == "text/plain":
        return data.decode("utf-8", errors="replace")

    if content_type == "application/pdf":
        try:
            from PyPDF2 import PdfReader
            reader = PdfReader(BytesIO(data))
            text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
            if not text:
                raise ExtractionError(
                    "PDF appears to be scanned or image-based — no extractable text found"
                )
            return text
        except ExtractionError:
            raise
        except Exception as e:
            raise ExtractionError(f"Could not read PDF: {e}") from e

    if content_type in (
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ):
        try:
            import docx
            doc = docx.Document(BytesIO(data))
            text = "\n".join(p.text for p in doc.paragraphs).strip()
            if not text:
                raise ExtractionError("DOCX file contains no readable text")
            return text
        except ExtractionError:
            raise
        except Exception as e:
            raise ExtractionError(f"Could not read DOCX: {e}") from e

    raise ExtractionError(f"Unsupported file type: {content_type}")

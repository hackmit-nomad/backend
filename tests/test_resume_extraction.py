"""Tests for PDF and DOCX text extraction in the resume parsing route."""

from __future__ import annotations

from io import BytesIO

import pytest

from app.utils.text_extraction import extract_text, ExtractionError


# ---------------------------------------------------------------------------
# Helpers to build minimal real PDF / DOCX in memory
# ---------------------------------------------------------------------------

def _make_pdf(text: str) -> bytes:
    """Create a minimal valid PDF containing the given text."""
    from reportlab.pdfgen import canvas
    buf = BytesIO()
    c = canvas.Canvas(buf)
    # Write text line by line so long strings don't overflow
    y = 750
    for line in text.splitlines():
        c.drawString(50, y, line[:100])
        y -= 15
        if y < 50:
            c.showPage()
            y = 750
    c.save()
    return buf.getvalue()


def _make_docx(text: str) -> bytes:
    """Create a minimal DOCX containing the given text."""
    import docx
    doc = docx.Document()
    for line in text.splitlines():
        doc.add_paragraph(line)
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Plain-text extraction
# ---------------------------------------------------------------------------

class TestPlainTextExtraction:
    def test_basic(self):
        content = "Python developer with 5 years experience"
        data = content.encode("utf-8")
        result = extract_text(data, "text/plain")
        assert result == content

    def test_unicode(self):
        content = "Résumé: développeur Python"
        data = content.encode("utf-8")
        result = extract_text(data, "text/plain")
        assert "Python" in result

    def test_multiline(self):
        content = "Skills:\n- Python\n- FastAPI\n- PostgreSQL"
        result = extract_text(content.encode("utf-8"), "text/plain")
        assert "Python" in result
        assert "FastAPI" in result


# ---------------------------------------------------------------------------
# PDF extraction
# ---------------------------------------------------------------------------

class TestPDFExtraction:
    def test_extracts_text(self):
        pdf_bytes = _make_pdf("Python developer\nFastAPI React PostgreSQL")
        result = extract_text(pdf_bytes, "application/pdf")
        assert "Python" in result

    def test_multipage(self):
        # Build a text long enough to span two pages
        long_text = "\n".join(f"Skill {i}: programming" for i in range(80))
        pdf_bytes = _make_pdf(long_text)
        result = extract_text(pdf_bytes, "application/pdf")
        assert "Skill 0" in result
        assert len(result) > 100

    def test_invalid_pdf_raises(self):
        with pytest.raises(ExtractionError):
            extract_text(b"not a pdf at all", "application/pdf")

    def test_returns_string(self):
        pdf_bytes = _make_pdf("Software Engineer")
        result = extract_text(pdf_bytes, "application/pdf")
        assert isinstance(result, str)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# DOCX extraction
# ---------------------------------------------------------------------------

class TestDOCXExtraction:
    MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    def test_extracts_text(self):
        docx_bytes = _make_docx("Machine learning engineer\nPython TensorFlow Keras")
        result = extract_text(docx_bytes, self.MIME)
        assert "Python" in result
        assert "TensorFlow" in result

    def test_multiline(self):
        lines = ["React developer", "TypeScript", "Node.js", "AWS"]
        docx_bytes = _make_docx("\n".join(lines))
        result = extract_text(docx_bytes, self.MIME)
        for skill in lines:
            assert skill in result

    def test_invalid_docx_raises(self):
        with pytest.raises(ExtractionError):
            extract_text(b"this is not a docx", self.MIME)

    def test_returns_string(self):
        docx_bytes = _make_docx("Data scientist")
        result = extract_text(docx_bytes, self.MIME)
        assert isinstance(result, str)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# Unsupported type
# ---------------------------------------------------------------------------

class TestUnsupportedType:
    def test_raises(self):
        with pytest.raises(ExtractionError):
            extract_text(b"some bytes", "image/png")

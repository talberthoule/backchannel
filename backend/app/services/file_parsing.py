"""Shared file-to-text parsing helpers for transcript and knowledge imports."""

import io
import re


def parse_text(content: str) -> list[str]:
    """Split text into meaningful segments (paragraphs or lines)."""
    # Split by double newlines (paragraphs) first
    paragraphs = re.split(r'\n\s*\n', content.strip())
    segments = []
    for p in paragraphs:
        text = p.strip()
        if text and len(text) > 1:
            # If a paragraph is very long, split by sentences
            if len(text) > 500:
                sentences = re.split(r'(?<=[.!?])\s+', text)
                for s in sentences:
                    s = s.strip()
                    if s and len(s) > 1:
                        segments.append(s)
            else:
                segments.append(text)
    return segments


def parse_markdown(content: str) -> list[str]:
    """Strip markdown formatting and split into segments."""
    # Remove markdown headers
    content = re.sub(r'^#{1,6}\s+', '', content, flags=re.MULTILINE)
    # Remove bold/italic markers
    content = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', content)
    content = re.sub(r'_{1,3}([^_]+)_{1,3}', r'\1', content)
    # Remove links [text](url) -> text
    content = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', content)
    # Remove bullet points
    content = re.sub(r'^[\s]*[-*+]\s+', '', content, flags=re.MULTILINE)
    return parse_text(content)


def parse_docx(file_bytes: bytes) -> list[str]:
    """Extract text from a Word document."""
    import docx
    doc = docx.Document(io.BytesIO(file_bytes))
    segments = []
    current = []
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            # Empty paragraph = paragraph break, flush current
            if current:
                segments.append(' '.join(current))
                current = []
        else:
            current.append(text)
    if current:
        segments.append(' '.join(current))
    return [s for s in segments if len(s) > 1]

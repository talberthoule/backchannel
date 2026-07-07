import logging
import tempfile
import os

from google import genai

from app.config import settings
from app.services.privacy import LocalOnlyModeError, is_local_only
from app.services.secrets import resolve_provider_key

logger = logging.getLogger(__name__)


async def upload_and_summarize(content: bytes, filename: str, mime_type: str) -> str:
    """Upload a file to Gemini Files API and return the file URI."""
    if await is_local_only():
        raise LocalOnlyModeError("document upload to the Gemini Files API")
    client = genai.Client(api_key=await resolve_provider_key("google"))

    # Write to temp file for upload
    suffix = os.path.splitext(filename)[1] if filename else ""
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        uploaded = await client.aio.files.upload(file=tmp_path, config={"mime_type": mime_type})
        logger.info(f"Uploaded file {filename} -> {uploaded.uri}")
        return uploaded.uri
    finally:
        os.unlink(tmp_path)


async def summarize_document(file_uri: str) -> str:
    """Use Gemini to summarize an uploaded document for context injection."""
    if await is_local_only():
        raise LocalOnlyModeError("document summarization via Gemini")
    client = genai.Client(api_key=await resolve_provider_key("google"))

    response = await client.aio.models.generate_content(
        model=settings.REFINEMENT_MODEL,
        contents=[
            {
                "parts": [
                    {"file_data": {"file_uri": file_uri}},
                    {"text": "Summarize this document concisely. Focus on key concepts, capabilities, metrics, decisions, risks, talking points, and follow-up context that may be relevant to the session. Keep it under 500 words."},
                ]
            }
        ],
    )
    return response.text

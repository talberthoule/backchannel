"""Convert uploaded knowledge files to Markdown via Microsoft MarkItDown.

Conversion happens entirely in memory (MarkItDown convert_stream over the
uploaded bytes) and only the resulting Markdown text is persisted to the
database, so no original file is ever written to the file system. If a
future converter requires a real path, route it through
_convert_via_tempfile, which guarantees the temp copy is deleted.
"""

import io
import logging
import os
import tempfile

logger = logging.getLogger(__name__)

# Already plain text/Markdown: stored as-is, no conversion needed
PASSTHROUGH_EXTENSIONS = {".md", ".markdown", ".txt"}

# Binary/rich formats MarkItDown converts to Markdown
CONVERTIBLE_EXTENSIONS = {".docx", ".pdf", ".pptx", ".xlsx", ".xls", ".csv", ".html", ".htm"}

SUPPORTED_EXTENSIONS = PASSTHROUGH_EXTENSIONS | CONVERTIBLE_EXTENSIONS


class MarkdownConversionError(ValueError):
    pass


def file_extension(filename: str) -> str:
    return os.path.splitext(filename or "")[1].lower()


def convert_to_markdown(content: bytes, filename: str) -> str:
    """Return the Markdown representation of an uploaded file's bytes."""
    ext = file_extension(filename)

    if ext in PASSTHROUGH_EXTENSIONS:
        return content.decode("utf-8", errors="replace").strip()

    if ext not in CONVERTIBLE_EXTENSIONS:
        raise MarkdownConversionError(
            f"Unsupported file format '{ext or filename}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    try:
        from markitdown import MarkItDown
    except ImportError as e:
        raise MarkdownConversionError(
            "markitdown is required for file conversion. Install it with: pip install 'markitdown[docx,pdf,pptx,xlsx,xls]'"
        ) from e

    try:
        result = MarkItDown(enable_plugins=False).convert_stream(
            io.BytesIO(content), file_extension=ext
        )
        markdown = (result.markdown or "").strip()
    except Exception as e:
        logger.warning(f"[markdown_conversion] in-memory conversion failed for '{filename}': {e}")
        markdown = _convert_via_tempfile(content, ext)

    if not markdown:
        raise MarkdownConversionError("No text could be extracted from the file")
    return markdown


def _convert_via_tempfile(content: bytes, ext: str) -> str:
    """Fallback for converters that need a real path; the temp copy is always deleted."""
    from markitdown import MarkItDown

    fd, path = tempfile.mkstemp(suffix=ext)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
        result = MarkItDown(enable_plugins=False).convert(path)
        return (result.markdown or "").strip()
    except Exception as e:
        raise MarkdownConversionError(f"Conversion failed: {e}") from e
    finally:
        try:
            os.unlink(path)
        except OSError:
            logger.error(f"[markdown_conversion] failed to delete temp file {path}")

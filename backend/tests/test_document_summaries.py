"""ALP-181: persisted document summaries and the Privacy First excerpt path."""

import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.models import Document
from app.routers.documents import (
    LOCAL_EXTRACT_CHARS,
    local_extract_summary,
    upload_document,
)
from app.services import session_manager
from app.services.privacy import LocalOnlyModeError


def _doc(**overrides) -> Document:
    fields = {
        "session_id": uuid.uuid4(),
        "filename": "brief.pdf",
        "mime_type": "application/pdf",
        "gemini_file_uri": "files/abc",
        "summary": "",
        "summary_source": "",
    }
    fields.update(overrides)
    return Document(**fields)


def _db_returning(docs):
    result = MagicMock()
    result.scalars.return_value.all.return_value = docs
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    return db


class GetDocumentSummariesTests(unittest.IsolatedAsyncioTestCase):
    async def test_summary_computed_once_then_served_from_storage(self):
        doc = _doc()
        db = _db_returning([doc])
        summarize = AsyncMock(return_value="Key points.")

        with patch.object(session_manager, "summarize_document", summarize):
            first = await session_manager.get_document_summaries(doc.session_id, db)
            second = await session_manager.get_document_summaries(doc.session_id, db)

        self.assertIn("### brief.pdf\nKey points.", first)
        self.assertEqual(first, second)
        self.assertEqual(1, summarize.await_count)
        self.assertEqual("Key points.", doc.summary)
        self.assertEqual("gemini", doc.summary_source)
        self.assertEqual(1, db.commit.await_count)

    async def test_failures_reported_but_not_persisted(self):
        doc = _doc()
        db = _db_returning([doc])
        summarize = AsyncMock(side_effect=RuntimeError("api down"))

        with patch.object(session_manager, "summarize_document", summarize):
            text = await session_manager.get_document_summaries(doc.session_id, db)

        self.assertIn("(Summary unavailable)", text)
        self.assertEqual("", doc.summary)
        self.assertEqual("", doc.summary_source)
        db.commit.assert_not_awaited()

    async def test_stored_summaries_readable_under_privacy_first(self):
        doc = _doc(summary="Stored earlier.", summary_source="gemini")
        db = _db_returning([doc])
        summarize = AsyncMock(side_effect=LocalOnlyModeError("document summarization"))

        with patch.object(session_manager, "summarize_document", summarize):
            text = await session_manager.get_document_summaries(doc.session_id, db)

        self.assertIn("### brief.pdf\nStored earlier.", text)
        summarize.assert_not_awaited()
        db.commit.assert_not_awaited()

    async def test_local_extract_docs_join_without_a_file_uri(self):
        doc = _doc(
            filename="notes.txt",
            gemini_file_uri="",
            summary="Local excerpt.",
            summary_source="local_extract",
        )
        db = _db_returning([doc])
        summarize = AsyncMock()

        with patch.object(session_manager, "summarize_document", summarize):
            text = await session_manager.get_document_summaries(doc.session_id, db)

        self.assertIn("### notes.txt\nLocal excerpt.", text)
        summarize.assert_not_awaited()

    async def test_doc_with_no_summary_and_no_uri_is_skipped(self):
        doc = _doc(gemini_file_uri="")
        db = _db_returning([doc])

        with patch.object(session_manager, "summarize_document", AsyncMock()) as summarize:
            text = await session_manager.get_document_summaries(doc.session_id, db)

        self.assertEqual("", text)
        summarize.assert_not_awaited()


class LocalExtractSummaryTests(unittest.TestCase):
    def test_txt_paragraphs_become_the_excerpt(self):
        excerpt = local_extract_summary(b"First point.\n\nSecond point.", "notes.txt")
        self.assertEqual("First point.\n\nSecond point.", excerpt)

    def test_markdown_formatting_is_stripped(self):
        excerpt = local_extract_summary(b"# Agenda\n\nDiscuss rollout.", "agenda.md")
        self.assertIn("Agenda", excerpt)
        self.assertIn("Discuss rollout.", excerpt)
        self.assertNotIn("#", excerpt)

    def test_excerpt_is_bounded_and_paragraph_aligned(self):
        big = ("word " * 900).strip()
        excerpt = local_extract_summary(
            f"lead paragraph\n\n{big}".encode(), "big.txt"
        )
        self.assertEqual("lead paragraph", excerpt)

        single = "x" * (LOCAL_EXTRACT_CHARS * 2)
        self.assertEqual(
            LOCAL_EXTRACT_CHARS,
            len(local_extract_summary(single.encode(), "single.txt")),
        )

    def test_docx_routes_through_the_docx_parser(self):
        with patch(
            "app.routers.documents.parse_docx",
            return_value=["From the deck."],
        ) as parser:
            excerpt = local_extract_summary(b"pk-bytes", "deck.docx")
        parser.assert_called_once()
        self.assertEqual("From the deck.", excerpt)

    def test_non_text_formats_are_rejected_with_guidance(self):
        with self.assertRaises(HTTPException) as ctx:
            local_extract_summary(b"%PDF-1.7", "brief.pdf")
        self.assertEqual(400, ctx.exception.status_code)
        self.assertIn("Privacy First", ctx.exception.detail)
        self.assertIn(".docx", ctx.exception.detail)


class UploadDocumentRouteTests(unittest.IsolatedAsyncioTestCase):
    def _file(self, name="notes.txt", content=b"hello world", mime="text/plain"):
        file = MagicMock()
        file.read = AsyncMock(return_value=content)
        file.filename = name
        file.content_type = mime
        return file

    def _db(self):
        db = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        return db

    async def test_privacy_first_upload_stores_a_local_excerpt(self):
        db = self._db()
        upload = AsyncMock()
        with (
            patch("app.routers.documents.is_local_only", AsyncMock(return_value=True)),
            patch("app.routers.documents.upload_and_summarize", upload),
        ):
            await upload_document(uuid.uuid4(), self._file(), db)

        upload.assert_not_awaited()
        doc = db.add.call_args.args[0]
        self.assertEqual("hello world", doc.summary)
        self.assertEqual("local_extract", doc.summary_source)
        self.assertEqual("", doc.gemini_file_uri)

    async def test_privacy_first_upload_rejects_non_text_formats(self):
        db = self._db()
        with (
            patch("app.routers.documents.is_local_only", AsyncMock(return_value=True)),
            patch("app.routers.documents.upload_and_summarize", AsyncMock()),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await upload_document(
                    uuid.uuid4(),
                    self._file("brief.pdf", b"%PDF-1.7", "application/pdf"),
                    db,
                )

        self.assertEqual(400, ctx.exception.status_code)
        db.add.assert_not_called()

    async def test_cloud_upload_path_is_unchanged(self):
        db = self._db()
        upload = AsyncMock(return_value="files/xyz")
        with (
            patch("app.routers.documents.is_local_only", AsyncMock(return_value=False)),
            patch("app.routers.documents.upload_and_summarize", upload),
        ):
            await upload_document(uuid.uuid4(), self._file(), db)

        upload.assert_awaited_once()
        doc = db.add.call_args.args[0]
        self.assertEqual("files/xyz", doc.gemini_file_uri)
        self.assertFalse(doc.summary)


class SchemaWiringTests(unittest.TestCase):
    """Source-level checks; no sqlite driver in requirements for a live patch test."""

    def test_migration_revisions_match_the_fleet_sequencing(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "alembic" / "versions" / "022_add_document_summaries.py"
        ).read_text()
        self.assertIn('revision = "022_document_summaries"', source)
        self.assertIn('down_revision = "021_signal_history"', source)

    def test_startup_patch_covers_both_columns(self):
        source = (
            Path(__file__).resolve().parents[1] / "app" / "main.py"
        ).read_text()
        self.assertIn(
            "ALTER TABLE documents ADD COLUMN summary TEXT NOT NULL DEFAULT ''", source
        )
        self.assertIn(
            "ALTER TABLE documents ADD COLUMN summary_source VARCHAR(20) NOT NULL DEFAULT ''",
            source,
        )


if __name__ == "__main__":
    unittest.main()

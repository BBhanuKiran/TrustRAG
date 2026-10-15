import re
import io
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from rag_engine import EvidenceIndex, chunk_page_text


VOCABULARY = (
    "phishing",
    "suspicious",
    "links",
    "password",
    "account",
    "strong",
)


def fake_encoder(texts):
    vectors = []
    for text in texts:
        words = set(re.findall(r"\b[a-z]+\b", text.lower()))
        vector = np.array(
            [float(word in words) for word in VOCABULARY],
            dtype=np.float32,
        )
        norm = np.linalg.norm(vector)
        vectors.append(vector / norm if norm else vector)
    return np.stack(vectors)


class FakePage:
    def __init__(self, text):
        self.text = text

    def extract_text(self):
        return self.text


class FakePdfReader:
    is_encrypted = False

    def __init__(self, _):
        self.pages = [
            FakePage(""),
            FakePage("Phishing emails contain suspicious links."),
            FakePage("Use strong account password protection."),
        ]


class TestChunkPageText(unittest.TestCase):
    def test_chunks_overlap_and_keep_page_citation(self):
        chunks = chunk_page_text(
            "guide.pdf",
            4,
            "one two three four five six seven eight",
            chunk_size=4,
            overlap=1,
        )

        self.assertEqual(
            [chunk["text"] for chunk in chunks],
            ["one two three four", "four five six seven", "seven eight"],
        )
        self.assertTrue(all(chunk["source"] == "guide.pdf" for chunk in chunks))
        self.assertTrue(all(chunk["page"] == 4 for chunk in chunks))

    def test_rejects_invalid_chunk_overlap(self):
        with self.assertRaises(ValueError):
            chunk_page_text("guide.pdf", 1, "text", chunk_size=4, overlap=4)


class TestEvidenceIndex(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "index.sqlite3"
        self.index = EvidenceIndex(self.database_path, encoder=fake_encoder)

    def tearDown(self):
        self.temp_dir.cleanup()

    @patch("rag_engine.PdfReader", FakePdfReader)
    def test_pdf_is_indexed_with_page_cited_semantic_results(self):
        document = self.index.add_pdf("guide.pdf", b"%PDF test content")

        self.assertEqual(document["page_count"], 3)
        self.assertEqual(document["chunk_count"], 2)

        results = self.index.search("suspicious phishing links")

        self.assertEqual(results[0]["source"], "guide.pdf")
        self.assertEqual(results[0]["page"], 2)
        self.assertGreater(results[0]["score"], 0.9)

    @patch("rag_engine.PdfReader", FakePdfReader)
    def test_top_k_preserves_document_order_when_scores_tie(self):
        self.index.add_pdf("guide.pdf", b"%PDF test content")

        results = self.index.search("no matching vocabulary", top_k=1)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["page"], 2)

    @patch("rag_engine.PdfReader", FakePdfReader)
    def test_documents_and_retrieval_are_scoped_to_their_owner(self):
        document = self.index.add_pdf(
            "private-guide.pdf",
            b"%PDF test content",
            user_id="owner-a",
        )

        self.assertEqual(len(self.index.list_documents("owner-a")), 1)
        self.assertEqual(self.index.list_documents("owner-b"), [])
        self.assertEqual(self.index.search("phishing", user_id="owner-b"), [])
        self.assertFalse(self.index.delete_document(document["id"], "owner-b"))
        self.assertTrue(self.index.delete_document(document["id"], "owner-a"))

    @patch("rag_engine.PdfReader", FakePdfReader)
    def test_index_survives_restart_and_document_can_be_deleted(self):
        document = self.index.add_pdf("guide.pdf", b"%PDF test content")
        restarted_index = EvidenceIndex(
            self.database_path,
            encoder=fake_encoder,
        )

        self.assertEqual(len(restarted_index.list_documents()), 1)
        self.assertTrue(restarted_index.delete_document(document["id"]))
        self.assertEqual(restarted_index.list_documents(), [])
        self.assertEqual(restarted_index.search("phishing"), [])

    def test_text_sources_are_searchable_without_fake_page_citations(self):
        document = self.index.add_text(
            "research-notes.txt",
            "Phishing emails contain suspicious links.",
            user_id="owner-a",
            source_type="link",
            source_url="https://example.com/security",
        )

        result = self.index.search("phishing suspicious links", user_id="owner-a")[0]
        stored = self.index.list_documents("owner-a")[0]

        self.assertEqual(document["source_type"], "link")
        self.assertIsNone(result["page"])
        self.assertEqual(result["url"], "https://example.com/security")
        self.assertEqual(stored["source_url"], "https://example.com/security")
        self.assertEqual(self.index.search("phishing", user_id="owner-b"), [])

    def test_image_source_uses_local_ocr_and_is_indexed_as_text(self):
        from PIL import Image

        image_buffer = io.BytesIO()
        Image.new("RGB", (20, 20), "white").save(image_buffer, format="PNG")
        with patch(
            "pytesseract.image_to_string",
            return_value="Phishing emails contain suspicious links.",
        ):
            document = self.index.add_image(
                "screenshot.png",
                image_buffer.getvalue(),
                user_id="owner-a",
            )

        result = self.index.search(
            "phishing suspicious links",
            user_id="owner-a",
        )[0]
        self.assertEqual(document["source_type"], "image")
        self.assertIsNone(result["page"])
        self.assertEqual(result["source"], "screenshot.png")

    def test_existing_database_schema_migrates_to_sources(self):
        legacy_database = Path(self.temp_dir.name) / "legacy.sqlite3"
        connection = sqlite3.connect(legacy_database)
        try:
            connection.executescript(
                """
                CREATE TABLE documents (
                    id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    user_id TEXT NOT NULL DEFAULT 'local',
                    uploaded_at TEXT NOT NULL,
                    page_count INTEGER NOT NULL,
                    chunk_count INTEGER NOT NULL
                );
                CREATE TABLE chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id TEXT NOT NULL REFERENCES documents(id)
                        ON DELETE CASCADE,
                    page INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    embedding BLOB NOT NULL
                );
                INSERT INTO documents VALUES (
                    'old-doc', 'old.pdf', 'owner-a', '2025-01-01T00:00:00+00:00', 1, 1
                );
                INSERT INTO chunks (document_id, page, text, embedding)
                    VALUES ('old-doc', 1, 'Phishing emails.', X'00000000');
                """
            )
        finally:
            connection.close()

        migrated_index = EvidenceIndex(
            legacy_database,
            encoder=fake_encoder,
        )
        document = migrated_index.list_documents("owner-a")[0]
        with migrated_index._connection() as connection:
            nullable_page = next(
                column["notnull"] == 0
                for column in connection.execute("PRAGMA table_info(chunks)")
                if column["name"] == "page"
            )

        self.assertEqual(document["source_type"], "pdf")
        self.assertIsNone(document["source_url"])
        self.assertTrue(nullable_page)

import io
import os
import sqlite3
import threading
from collections.abc import Callable, Generator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
from pypdf import PdfReader
from pypdf.errors import PdfReadError


DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
CHUNK_SIZE = 180
CHUNK_OVERLAP = 30
MAX_INDEXED_PAGES = 500
MAX_INDEXED_CHUNKS_PER_USER = 5000
MAX_INDEXED_DOCUMENTS_PER_USER = 100


class InvalidDocumentError(ValueError):
    pass


class DocumentLimitError(ValueError):
    pass


class EmbeddingModelError(RuntimeError):
    pass


def chunk_page_text(
    source: str,
    page: int,
    text: str,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[dict[str, Any]]:
    if chunk_size < 1 or overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be non-negative and smaller than chunk_size.")

    words = text.split()
    chunks = []
    step = chunk_size - overlap

    for start in range(0, len(words), step):
        chunk_words = words[start : start + chunk_size]
        if not chunk_words:
            continue

        chunks.append({
            "source": source,
            "page": page,
            "text": " ".join(chunk_words),
        })

    return chunks


class EvidenceIndex:
    def __init__(
        self,
        database_path: str | Path,
        encoder: Callable[[Sequence[str]], np.ndarray] | None = None,
    ) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._encoder = encoder
        self._model: Any = None
        self._model_lock = threading.Lock()
        self._initialize_database()

    @contextmanager
    def _connection(
        self,
    ) -> Generator[sqlite3.Connection, None, None]:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")

        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize_database(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    user_id TEXT NOT NULL DEFAULT 'local',
                    uploaded_at TEXT NOT NULL,
                    page_count INTEGER NOT NULL,
                    chunk_count INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id TEXT NOT NULL REFERENCES documents(id)
                        ON DELETE CASCADE,
                    page INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    embedding BLOB NOT NULL
                );
                """
            )
            document_columns = {
                column["name"]
                for column in connection.execute(
                    "PRAGMA table_info(documents)"
                ).fetchall()
            }
            if "user_id" not in document_columns:
                connection.execute(
                    "ALTER TABLE documents ADD COLUMN user_id TEXT NOT NULL DEFAULT 'local'"
                )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_documents_user_id ON documents(user_id)"
            )

    def _encode(self, texts: Sequence[str]) -> np.ndarray:
        if self._encoder is not None:
            vectors = self._encoder(texts)
        else:
            try:
                with self._model_lock:
                    if self._model is None:
                        from sentence_transformers import SentenceTransformer

                        model_name = os.getenv(
                            "TRUSTRAG_EMBEDDING_MODEL",
                            DEFAULT_EMBEDDING_MODEL,
                        )
                        try:
                            self._model = SentenceTransformer(
                                model_name,
                                device="cpu",
                                local_files_only=True,
                            )
                        except OSError:
                            try:
                                self._model = SentenceTransformer(
                                    model_name,
                                    device="cpu",
                                )
                            except Exception as error:
                                raise EmbeddingModelError(
                                    "The local embedding model is not cached and "
                                    "could not be downloaded. Check your internet "
                                    "connection and configured model name."
                                ) from error

                vectors = self._model.encode(
                    list(texts),
                    normalize_embeddings=True,
                    convert_to_numpy=True,
                    show_progress_bar=False,
                )
            except (ImportError, OSError, RuntimeError) as error:
                raise EmbeddingModelError(
                    "The local embedding model could not be loaded or run. "
                    "Check your internet connection for its first download and "
                    "verify the configured embedding model."
                ) from error

        vectors = np.asarray(vectors, dtype=np.float32)
        if vectors.ndim != 2 or vectors.shape[0] != len(texts):
            raise ValueError("The embedding model returned an invalid vector shape.")
        if not np.isfinite(vectors).all():
            raise ValueError("The embedding model returned non-finite values.")

        return vectors

    @staticmethod
    def _extract_pages(content: bytes) -> tuple[list[tuple[int, str]], int]:
        if not content:
            raise InvalidDocumentError("The uploaded PDF is empty.")

        try:
            reader = PdfReader(io.BytesIO(content))
        except PdfReadError as error:
            raise InvalidDocumentError(
                "The uploaded file is not a readable PDF."
            ) from error

        if reader.is_encrypted:
            raise InvalidDocumentError(
                "Password-protected PDFs are not supported yet."
            )

        page_count = len(reader.pages)
        pages = []
        for page_number, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if text:
                pages.append((page_number, text))

        return pages, page_count

    def add_pdf(
        self,
        filename: str,
        content: bytes,
        user_id: str = "local",
    ) -> dict[str, object]:
        pages, page_count = self._extract_pages(content)
        if page_count > MAX_INDEXED_PAGES:
            raise DocumentLimitError(
                f"PDF exceeds the {MAX_INDEXED_PAGES}-page limit."
            )
        chunks = [
            chunk
            for page_number, text in pages
            for chunk in chunk_page_text(filename, page_number, text)
        ]

        if not chunks:
            raise InvalidDocumentError(
                "No searchable text was found in this PDF. "
                "Scanned PDFs need OCR, which is not supported yet."
            )
        if len(chunks) > MAX_INDEXED_CHUNKS_PER_USER:
            raise DocumentLimitError(
                f"PDF exceeds the {MAX_INDEXED_CHUNKS_PER_USER}-passage limit."
            )

        vectors = self._encode([chunk["text"] for chunk in chunks])
        if vectors.shape[1] == 0:
            raise ValueError("The embedding model returned empty vectors.")

        document_id = uuid4().hex
        uploaded_at = datetime.now(UTC).isoformat()

        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            usage = connection.execute(
                """
                SELECT COUNT(*) AS document_count,
                    COALESCE(SUM(chunk_count), 0) AS chunk_count
                FROM documents WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
            if usage["document_count"] >= MAX_INDEXED_DOCUMENTS_PER_USER:
                raise DocumentLimitError(
                    "This account has reached the "
                    f"{MAX_INDEXED_DOCUMENTS_PER_USER}-document limit."
                )
            if usage["chunk_count"] + len(chunks) > MAX_INDEXED_CHUNKS_PER_USER:
                raise DocumentLimitError(
                    "This account has reached the "
                    f"{MAX_INDEXED_CHUNKS_PER_USER}-passage limit."
                )
            connection.execute(
                """
                INSERT INTO documents (
                    id, filename, user_id, uploaded_at, page_count, chunk_count
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    filename,
                    user_id,
                    uploaded_at,
                    page_count,
                    len(chunks),
                ),
            )
            connection.executemany(
                """
                INSERT INTO chunks (document_id, page, text, embedding)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (
                        document_id,
                        chunk["page"],
                        chunk["text"],
                        vector.tobytes(),
                    )
                    for chunk, vector in zip(chunks, vectors, strict=True)
                ],
            )

        return {
            "id": document_id,
            "filename": filename,
            "page_count": page_count,
            "chunk_count": len(chunks),
            "uploaded_at": uploaded_at,
        }

    def list_documents(self, user_id: str = "local") -> list[dict[str, object]]:
        with self._connection() as connection:
            documents = connection.execute(
                """
                SELECT id, filename, uploaded_at, page_count, chunk_count
                FROM documents WHERE user_id = ?
                ORDER BY uploaded_at DESC
                """,
                (user_id,),
            ).fetchall()

        return [dict(document) for document in documents]

    def count_documents(self, user_id: str = "local") -> int:
        with self._connection() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM documents WHERE user_id = ?",
                (user_id,),
            ).fetchone()[0]
        return int(count)

    def delete_document(self, document_id: str, user_id: str = "local") -> bool:
        with self._connection() as connection:
            cursor = connection.execute(
                "DELETE FROM documents WHERE id = ? AND user_id = ?",
                (document_id, user_id),
            )

        return cursor.rowcount > 0

    def search(
        self,
        query: str,
        top_k: int = 5,
        user_id: str = "local",
    ) -> list[dict[str, object]]:
        if top_k < 1:
            raise ValueError("top_k must be at least 1.")
        if not query.strip():
            return []

        with self._connection() as connection:
            chunks = connection.execute(
                """
                SELECT documents.filename, chunks.page, chunks.text, chunks.embedding
                FROM chunks
                JOIN documents ON documents.id = chunks.document_id
                WHERE documents.user_id = ?
                """,
                (user_id,),
            ).fetchall()

        if not chunks:
            return []

        query_vector = self._encode([query])[0]
        embeddings = [chunk["embedding"] for chunk in chunks]
        if any(len(embedding) != query_vector.nbytes for embedding in embeddings):
            raise ValueError(
                "Stored vectors do not match the current embedding model. "
                "Re-index the documents after changing models."
            )

        vectors = np.frombuffer(b"".join(embeddings), dtype=np.float32).reshape(
            len(chunks),
            query_vector.size,
        )
        scores = vectors @ query_vector
        result_count = min(top_k, len(chunks))
        cutoff = np.partition(scores, len(scores) - result_count)[
            len(scores) - result_count
        ]
        candidate_indices = np.flatnonzero(scores >= cutoff)
        top_indices = sorted(
            candidate_indices,
            key=lambda index: (-float(scores[index]), int(index)),
        )[:result_count]

        results = []
        for index in top_indices:
            chunk = chunks[index]
            results.append({
                "source": chunk["filename"],
                "page": chunk["page"],
                "text": chunk["text"],
                "score": float(scores[index]),
            })

        return results

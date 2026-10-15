import asyncio
import tempfile
import unittest
import re
from pathlib import Path
from unittest.mock import patch

import httpx
import numpy as np

from app import app
from auth import AuthStore, SESSION_COOKIE_NAME
from rag_engine import EvidenceIndex
from answering import ABSTENTION, LocalModelError


def fake_encoder(texts):
    vocabulary = ("phishing", "suspicious", "links", "password")
    vectors = []

    for text in texts:
        words = set(re.findall(r"\b[a-z]+\b", text.lower()))
        vector = np.array(
            [float(word in words) for word in vocabulary],
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
        ]


class TestTrustRagApi(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.index = EvidenceIndex(
            Path(self.temp_dir.name) / "api.sqlite3",
            encoder=fake_encoder,
        )
        self.auth = AuthStore(
            Path(self.temp_dir.name) / "api.sqlite3",
            secret_key="test-secret-key-that-is-long-enough-for-tests",
        )
        self.user = self.auth.register("researcher@example.com", "strong-test-password")
        self.session_token = self.auth.create_session(self.user["id"])
        self.transport = httpx.ASGITransport(app=app)
        self.index_patch = patch("app.get_index", return_value=self.index)
        self.index_patch.start()
        self.addCleanup(self.index_patch.stop)
        self.auth_patch = patch("app.get_auth_store", return_value=self.auth)
        self.auth_patch.start()
        self.addCleanup(self.auth_patch.stop)
        self.addCleanup(self.temp_dir.cleanup)

    async def _async_request(self, method, path, **kwargs):
        cookies = kwargs.pop(
            "cookies",
            {SESSION_COOKIE_NAME: self.session_token},
        )
        async with httpx.AsyncClient(
            transport=self.transport,
            base_url="http://testserver",
            cookies=cookies,
        ) as client:
            return await client.request(method, path, **kwargs)

    def request(self, method, path, **kwargs):
        return asyncio.run(self._async_request(method, path, **kwargs))

    def test_health_endpoint(self):
        response = self.request("GET", "/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_product_website_static_assets_and_security_headers(self):
        website = self.request("GET", "/")
        stylesheet = self.request("GET", "/assets/styles.css")
        openapi_docs = self.request("GET", "/docs")

        self.assertEqual(website.status_code, 200)
        self.assertIn("Research with", website.text)
        self.assertEqual(stylesheet.status_code, 200)
        self.assertEqual(openapi_docs.status_code, 200)
        self.assertEqual(website.headers["x-frame-options"], "DENY")
        self.assertIn(
            "Content-Security-Policy",
            website.headers,
        )

    def test_ask_abstains_when_no_documents_exist(self):
        response = self.request(
            "POST",
            "/ask",
            json={"query": "What is the policy?", "top_k": 5},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["supported"])
        self.assertEqual(response.json()["answer"], ABSTENTION)

    @patch(
        "app.answer_with_local_model",
        return_value={
            "answer": "Use suspicious-link checks. [E1]",
            "supported": True,
            "citations": [{"id": "E1", "source": "guide.pdf", "page": 2}],
            "evidence": [],
        },
    )
    def test_ask_endpoint_returns_answer_and_citations(self, _):
        response = self.request(
            "POST",
            "/ask",
            json={
                "query": "How do I check a link?",
                "model": "local-test",
                "evidence_threshold": 0.4,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["supported"])
        self.assertEqual(response.json()["citations"][0]["page"], 2)

    @patch(
        "app.answer_with_local_model",
        side_effect=LocalModelError("Start Ollama and retry."),
    )
    def test_ask_endpoint_reports_unavailable_local_model(self, _):
        response = self.request(
            "POST",
            "/ask",
            json={"query": "What does the document say?"},
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "Start Ollama and retry.")

    @patch("rag_engine.PdfReader", FakePdfReader)
    def test_upload_and_search_returns_page_cited_evidence(self):
        upload_response = self.request(
            "POST",
            "/documents",
            files={
                "file": (
                    "guide.pdf",
                    b"%PDF test content",
                    "application/pdf",
                )
            },
        )

        self.assertEqual(upload_response.status_code, 201)
        self.assertEqual(upload_response.json()["filename"], "guide.pdf")

        search_response = self.request(
            "POST",
            "/search",
            json={"query": "suspicious phishing links", "top_k": 3},
        )

        self.assertEqual(search_response.status_code, 200)
        payload = search_response.json()
        self.assertTrue(payload["has_evidence"])
        self.assertEqual(payload["evidence"][0]["source"], "guide.pdf")
        self.assertEqual(payload["evidence"][0]["page"], 2)

    def test_upload_rejects_non_pdf_files(self):
        response = self.request(
            "POST",
            "/documents",
            files={"file": ("notes.txt", b"not a PDF", "text/plain")},
        )

        self.assertEqual(response.status_code, 415)
        self.assertEqual(response.json()["detail"], "Only PDF files are supported.")

    def test_private_endpoints_require_an_account(self):
        for method, path, kwargs in (
            ("GET", "/documents", {}),
            ("POST", "/search", {"json": {"query": "policy"}}),
            ("POST", "/ask", {"json": {"query": "policy"}}),
            (
                "POST",
                "/documents",
                {"files": {"file": ("document.txt", b"data", "text/plain")}},
            ),
        ):
            with self.subTest(method=method, path=path):
                response = self.request(method, path, cookies={}, **kwargs)
                self.assertEqual(response.status_code, 401)

    @patch("rag_engine.PdfReader", FakePdfReader)
    def test_documents_search_and_answers_are_isolated_by_account(self):
        upload_response = self.request(
            "POST",
            "/documents",
            files={
                "file": ("guide.pdf", b"%PDF test content", "application/pdf")
            },
        )
        document_id = upload_response.json()["id"]
        other_user = self.auth.register(
            "other-researcher@example.com",
            "another-strong-password",
        )
        other_session = self.auth.create_session(other_user["id"])

        other_documents = self.request(
            "GET",
            "/documents",
            cookies={SESSION_COOKIE_NAME: other_session},
        )
        other_search = self.request(
            "POST",
            "/search",
            cookies={SESSION_COOKIE_NAME: other_session},
            json={"query": "phishing suspicious links"},
        )
        other_delete = self.request(
            "DELETE",
            f"/documents/{document_id}",
            cookies={SESSION_COOKIE_NAME: other_session},
        )

        self.assertEqual(other_documents.json(), [])
        self.assertFalse(other_search.json()["has_evidence"])
        self.assertEqual(other_delete.status_code, 404)
        self.assertEqual(len(self.index.list_documents(self.user["id"])), 1)

    def test_registration_login_and_logout_manage_private_session(self):
        registration = self.request(
            "POST",
            "/api/auth/register",
            cookies={},
            json={
                "email": "  New.User@example.com ",
                "password": "a-very-strong-password",
            },
        )
        self.assertEqual(registration.status_code, 201)
        self.assertEqual(registration.json()["user"]["email"], "new.user@example.com")
        self.assertIn(SESSION_COOKIE_NAME, registration.cookies)

        session_cookie = {
            SESSION_COOKIE_NAME: registration.cookies[SESSION_COOKIE_NAME]
        }
        account_response = self.request(
            "GET",
            "/api/auth/me",
            cookies=session_cookie,
        )
        logout_response = self.request(
            "POST",
            "/api/auth/logout",
            cookies=session_cookie,
        )
        expired_account = self.request(
            "GET",
            "/api/auth/me",
            cookies=session_cookie,
        )

        self.assertEqual(account_response.status_code, 200)
        self.assertEqual(logout_response.status_code, 204)
        self.assertEqual(expired_account.status_code, 401)

    @patch("rag_engine.PdfReader", FakePdfReader)
    def test_account_deletion_removes_owned_documents_and_sessions(self):
        self.request(
            "POST",
            "/documents",
            files={
                "file": ("guide.pdf", b"%PDF test content", "application/pdf")
            },
        )

        deletion = self.request("DELETE", "/api/auth/me")
        account_after_deletion = self.request("GET", "/api/auth/me")

        self.assertEqual(deletion.status_code, 204)
        self.assertEqual(account_after_deletion.status_code, 401)
        self.assertEqual(self.index.list_documents(self.user["id"]), [])
        self.assertIsNone(self.auth.get_user_from_session(self.session_token))

    def test_bad_login_does_not_reveal_account_existence(self):
        known_user = self.request(
            "POST",
            "/api/auth/login",
            cookies={},
            json={
                "email": "researcher@example.com",
                "password": "incorrect-password",
            },
        )
        unknown_user = self.request(
            "POST",
            "/api/auth/login",
            cookies={},
            json={
                "email": "nobody@example.com",
                "password": "incorrect-password",
            },
        )
        self.assertEqual(known_user.status_code, 401)
        self.assertEqual(known_user.json(), unknown_user.json())

    @patch("rag_engine.PdfReader", FakePdfReader)
    def test_documents_can_be_listed_and_deleted(self):
        upload_response = self.request(
            "POST",
            "/documents",
            files={
                "file": (
                    "guide.pdf",
                    b"%PDF test content",
                    "application/pdf",
                )
            },
        )
        document_id = upload_response.json()["id"]

        list_response = self.request("GET", "/documents")
        delete_response = self.request("DELETE", f"/documents/{document_id}")
        missing_response = self.request("DELETE", f"/documents/{document_id}")

        self.assertEqual(len(list_response.json()), 1)
        self.assertEqual(delete_response.status_code, 204)
        self.assertEqual(missing_response.status_code, 404)

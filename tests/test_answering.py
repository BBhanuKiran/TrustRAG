import json
import unittest
from unittest.mock import patch
from urllib.error import URLError

from answering import (
    ABSTENTION,
    MAX_ANSWER_TOKENS,
    OLLAMA_KEEP_ALIVE,
    LocalModelError,
    answer_with_hosted_model,
    answer_with_local_model,
    get_ollama_models,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return self.payload


class TestGroundedAnswers(unittest.TestCase):
    def setUp(self):
        self.evidence = [
            {
                "source": "security-guide.pdf",
                "page": 3,
                "text": "Do not open unexpected links.",
                "score": 0.8,
            }
        ]

    def test_weak_evidence_abstains_without_calling_model(self):
        weak_evidence = [{**self.evidence[0], "score": 0.1}]

        with patch("answering.urlopen") as mock_urlopen:
            result = answer_with_local_model(
                "Is this link suspicious?",
                weak_evidence,
                evidence_threshold=0.35,
            )

        mock_urlopen.assert_not_called()
        self.assertFalse(result["supported"])
        self.assertEqual(result["answer"], ABSTENTION)
        self.assertEqual(result["citations"], [])

    @patch(
        "answering.urlopen",
        return_value=FakeResponse({
            "message": {"content": "Avoid unexpected links [E1]."}
        }),
    )
    def test_model_answer_returns_only_resolved_source_citations(self, _):
        result = answer_with_local_model(
            "What should I do?",
            self.evidence,
        )

        self.assertTrue(result["supported"])
        self.assertEqual(
            result["citations"],
            [{"id": "E1", "source": "security-guide.pdf", "page": 3}],
        )

    @patch(
        "answering.urlopen",
        return_value=FakeResponse({
            "message": {"content": "Avoid unexpected links [E1]."}
        }),
    )
    def test_model_request_limits_output_and_keeps_model_warm(self, mock_urlopen):
        answer_with_local_model("What should I do?", self.evidence)

        request = mock_urlopen.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(payload["options"]["num_predict"], MAX_ANSWER_TOKENS)
        self.assertEqual(payload["keep_alive"], OLLAMA_KEEP_ALIVE)

    @patch(
        "answering.urlopen",
        return_value=FakeResponse({
            "message": {"content": "This is unsupported. [E9]"}
        }),
    )
    def test_unknown_citations_are_not_presented_as_supported(self, _):
        result = answer_with_local_model("Question?", self.evidence)

        self.assertFalse(result["supported"])
        self.assertEqual(result["citations"], [])

    @patch(
        "answering.urlopen",
        return_value=FakeResponse({
            "message": {
                "content": "Avoid unexpected links [E1]. "
                "The source also recommends reporting them."
            }
        }),
    )
    def test_uncited_sentence_is_removed_from_supported_response(self, _):
        result = answer_with_local_model("Question?", self.evidence)

        self.assertTrue(result["supported"])
        self.assertIn("Avoid unexpected links [E1].", result["answer"])
        self.assertNotIn("reporting them", result["answer"])
        self.assertEqual(result["citations"][0]["id"], "E1")

    @patch("answering.urlopen", side_effect=URLError("offline"))
    def test_unavailable_ollama_is_reported_clearly(self, _):
        with self.assertRaisesRegex(LocalModelError, "could not complete"):
            answer_with_local_model("Question?", self.evidence)

    @patch("answering.urlopen", side_effect=URLError("offline"))
    def test_model_status_reports_offline_service(self, _):
        with self.assertRaisesRegex(LocalModelError, "Can't reach Ollama"):
            get_ollama_models()


class TestHostedGroundedAnswers(unittest.TestCase):
    def setUp(self):
        self.evidence = [
            {
                "source": "security-guide.pdf",
                "page": 3,
                "text": "Do not open unexpected links.",
                "score": 0.8,
            }
        ]

    def test_weak_evidence_abstains_without_a_provider_key(self):
        with patch.dict("answering.os.environ", {}, clear=True):
            with patch("answering.urlopen") as mock_urlopen:
                result = answer_with_hosted_model(
                    "What does the source say?",
                    [{**self.evidence[0], "score": 0.1}],
                )

        mock_urlopen.assert_not_called()
        self.assertEqual(result["answer"], ABSTENTION)

    def test_supported_evidence_requires_a_server_provider_key(self):
        with patch.dict("answering.os.environ", {}, clear=True):
            with self.assertRaisesRegex(LocalModelError, "TRUSTRAG_LLM_API_KEY"):
                answer_with_hosted_model("What should I avoid?", self.evidence)

    @patch(
        "answering.urlopen",
        return_value=FakeResponse({
            "choices": [
                {"message": {"content": "Avoid unexpected links [E1]."}}
            ]
        }),
    )
    def test_hosted_answers_are_cited_and_api_key_stays_server_side(
        self,
        mock_urlopen,
    ):
        with patch.dict(
            "answering.os.environ",
            {
                "TRUSTRAG_LLM_API_KEY": "server-only-test-key",
                "TRUSTRAG_LLM_BASE_URL": "https://provider.example/v1",
                "TRUSTRAG_LLM_MODEL": "example-fast-model",
            },
        ):
            result = answer_with_hosted_model(
                "What should I avoid?",
                self.evidence,
            )

        request = mock_urlopen.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(
            request.full_url,
            "https://provider.example/v1/chat/completions",
        )
        self.assertEqual(
            request.get_header("Authorization"),
            "Bearer server-only-test-key",
        )
        self.assertEqual(payload["model"], "example-fast-model")
        self.assertEqual(payload["max_tokens"], MAX_ANSWER_TOKENS)
        self.assertTrue(result["supported"])
        self.assertEqual(result["citations"][0]["page"], 3)

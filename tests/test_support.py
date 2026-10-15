import unittest

from support import find_support_answer


class TestManualSupport(unittest.TestCase):
    def test_upload_question_returns_manual_based_guidance(self):
        result = find_support_answer("How do I upload my first PDF?")

        self.assertTrue(result["supported"])
        self.assertEqual(result["section"], "Quick start")
        self.assertIn("Upload PDF", result["answer"])

    def test_uncovered_question_abstains_instead_of_inventing(self):
        result = find_support_answer(
            "What is the current stock price of a company?"
        )

        self.assertFalse(result["supported"])
        self.assertIsNone(result["section"])
        self.assertIn("couldn't find a reliable answer", result["answer"])

    def test_unrelated_word_overlap_does_not_return_manual_answer(self):
        result = find_support_answer("What is the current stock price?")

        self.assertFalse(result["supported"])

    def test_answer_accuracy_question_matches_accuracy_limitations(self):
        result = find_support_answer("Does TrustRAG guarantee accurate answers?")

        self.assertTrue(result["supported"])
        self.assertEqual(result["section"], "Support")
        self.assertIn("cannot promise 100% accurate", result["answer"])

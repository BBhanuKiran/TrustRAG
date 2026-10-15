import unittest

from combined_search import search_documents, tokenize


class TestCombinedSearch(unittest.TestCase):

    def test_tokenize_lowercases_words(self):
        self.assertEqual(
            tokenize("Phishing WARNING"),
            {"phishing", "warning"},
        )

    def test_search_finds_matching_document(self):
        documents = [
            {
                "source": "security_guide.pdf",
                "page": 1,
                "text": "Phishing emails contain suspicious links.",
            },
            {
                "source": "knowledge.txt",
                "page": None,
                "text": "Use strong passwords.",
            },
        ]

        results = search_documents(
            "phishing suspicious links",
            documents,
        )

        self.assertTrue(results)
        self.assertEqual(
            results[0]["source"],
            "security_guide.pdf",
        )

    def test_search_ranks_more_relevant_document_first(self):
        documents = [
            {
                "source": "general.txt",
                "page": None,
                "text": "Phishing emails can be dangerous.",
            },
            {
                "source": "specific.txt",
                "page": None,
                "text": "Phishing emails contain suspicious links.",
            },
        ]

        results = search_documents(
            "phishing suspicious links",
            documents,
        )

        self.assertEqual(results[0]["source"], "specific.txt")
        self.assertEqual(results[0]["score"], 1.0)

    def test_search_limits_results_to_top_k(self):
        documents = [
            {"source": "one.txt", "page": None, "text": "Phishing emails."},
            {"source": "two.txt", "page": None, "text": "Phishing messages."},
            {"source": "three.txt", "page": None, "text": "Phishing scams."},
        ]

        results = search_documents("phishing", documents, top_k=2)

        self.assertEqual(len(results), 2)

    def test_empty_query_returns_no_results(self):
        self.assertEqual(
            search_documents("", [], top_k=3),
            [],
        )


if __name__ == "__main__":
    unittest.main()
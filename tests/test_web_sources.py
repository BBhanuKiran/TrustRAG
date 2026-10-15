import unittest
from unittest.mock import patch

from web_sources import (
    WebSourceError,
    _SearchResultsParser,
    _safe_url,
    html_to_text,
    search_recent_web,
)


class FakeSearchResponse:
    content = b"""
    <div class="results">
      <div class="result">
        <div class="result__title">
          <a class="result__a" href="https://example.com/current">Current report</a>
        </div>
        <a class="result__snippet">Published today with new findings.</a>
      </div>
    </div>
    """
    encoding = "utf-8"

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def iter_bytes(self):
        yield self.content

    def raise_for_status(self):
        pass


class TestWebSources(unittest.TestCase):
    def test_html_extraction_omits_scripts_and_returns_title(self):
        text, title = html_to_text(
            "<html><head><title>Policy update</title><script>secret()</script>"
            "</head><body><h1>New rules</h1><p>Read the policy.</p></body></html>"
        )

        self.assertEqual(title, "Policy update")
        self.assertIn("New rules", text)
        self.assertIn("Read the policy.", text)
        self.assertNotIn("secret", text)

    def test_search_result_parser_returns_title_snippet_and_link(self):
        parser = _SearchResultsParser()
        parser.feed(FakeSearchResponse.content.decode())

        self.assertEqual(
            parser.results,
            [{
                "title": "Current report ",
                "url": "https://example.com/current",
                "text": "Published today with new findings. ",
            }],
        )

    @patch("web_sources.httpx.Client")
    def test_recent_search_returns_linked_evidence(self, client_class):
        client = client_class.return_value.__enter__.return_value
        client.stream.return_value = FakeSearchResponse()

        result = search_recent_web("current policy", limit=1)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["source"], "Current report")
        self.assertEqual(result[0]["url"], "https://example.com/current")
        self.assertIn("Published today", result[0]["text"])
        client.stream.assert_called_once()

    def test_private_network_links_are_rejected(self):
        with self.assertRaisesRegex(WebSourceError, "private or local"):
            _safe_url("http://127.0.0.1/admin")


if __name__ == "__main__":
    unittest.main()

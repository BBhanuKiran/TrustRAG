import re


SUPPORT_ENTRIES = [
    {
        "section": "Purpose",
        "question": "What is TrustRAG and what is it for?",
        "text": (
            "TrustRAG is an evidence-first research assistant for PDFs, text, "
            "images, web pages, and current web search. It finds relevant "
            "passages, drafts an answer from that evidence, and links to sources "
            "or PDF pages so you can verify it."
        ),
        "keywords": "purpose about project research PDF evidence citations links web images text",
    },
    {
        "section": "Quick start",
        "question": "How do I get started and upload a document?",
        "text": (
            "Create an account, open My library, and select Upload PDF or choose "
            "another source: a text file or "
            "image; paste text; or add a public web link. File and link sources "
            "are limited to 20 MB. PDFs may contain up to 500 pages. Image text "
            "is extracted with local Tesseract OCR. In Workspace, fresh web "
            "search is included by default; turn it off to use only your private "
            "library. Verify answers against their cited source."
        ),
        "keywords": "how to use start signup account upload add PDF index link URL text image web",
    },
    {
        "section": "Citations",
        "question": "How do citations and evidence work?",
        "text": (
            "TrustRAG retrieves passages from your indexed sources and includes "
            "source links or PDF page references when it can support an answer. "
            "Open Inspect evidence to read the exact retrieved passage. A citation "
            "points to a source; it is not a guarantee that a claim is correct."
        ),
        "keywords": "citation source page evidence verify inspect passage",
    },
    {
        "section": "Unsupported questions",
        "question": "What if a document does not contain the answer?",
        "text": (
            "TrustRAG is designed to abstain when it cannot find sufficiently "
            "strong evidence in your private library or web results. Try adding a "
            "relevant source, enabling fresh web search, or rephrasing the question. "
            "It should not be treated as a "
            "general-purpose or infallible source of facts."
        ),
        "keywords": "unsupported not found abstain no answer missing evidence",
    },
    {
        "section": "Privacy",
        "question": "Who can access my documents and how are they processed?",
        "text": (
            "Each account's private sources and local-search results are isolated "
            "by account ownership. When enabled, web search sends your question "
            "to DuckDuckGo. TrustRAG may send retrieved excerpts to the "
            "server-configured hosted AI answer provider. Image OCR runs locally. "
            "Review provider privacy terms before adding confidential material."
        ),
        "keywords": "privacy security private other user account sharing provider",
    },
    {
        "section": "File support",
        "question": "Which files can I upload and what are the limits?",
        "text": (
            "The website accepts PDFs, TXT, Markdown, CSV, HTML, PNG, JPEG, "
            "WEBP, and TIFF files up to 20 MB; PDFs are limited to 500 pages. "
            "You can also paste text or add public web links. Each account may "
            "index up to 100 sources and 5,000 passages. Image OCR requires "
            "Tesseract and extracts readable text, not visual meaning."
        ),
        "keywords": "file type format limit upload size scanned OCR PDF image text links",
    },
    {
        "section": "Support",
        "question": (
            "Does TrustRAG guarantee accurate answers, and what should I do "
            "if an answer looks wrong?"
        ),
        "text": (
            "Inspect the cited passage and check the original source or PDF page. "
            "If evidence is missing, add a relevant source and ask a more specific question. "
            "For a technical problem, note the exact error, the action that caused "
            "it, and whether it repeats. TrustRAG cannot promise 100% accurate "
            "answers; independently verify important or consequential information."
        ),
        "keywords": (
            "wrong error help support troubleshooting accurate accuracy "
            "guarantee answers issue"
        ),
    },
    {
        "section": "Account",
        "question": "How do accounts work and how can I reset my password?",
        "text": (
            "Accounts keep each person's indexed documents separate. Use the same "
            "email address and password to sign in. Self-service password reset "
            "is not enabled in this release, so choose a strong password you can "
            "store safely."
        ),
        "keywords": "account login sign in password reset forgot password",
    },
]


def find_support_answer(query: str) -> dict[str, object]:
    tokens = set(re.findall(r"\b[a-z0-9]+\b", query.casefold()))
    stop_words = {
        "a", "an", "and", "are", "can", "do", "for", "how", "i", "in",
        "is", "it", "me", "my", "of", "on", "or", "the", "to", "what",
        "when", "where", "which", "who", "why", "with", "you", "first",
        "currently", "current",
    }
    query_tokens = tokens - stop_words
    if not query_tokens:
        return {"answer": _SUPPORT_FALLBACK, "supported": False, "section": None}

    ranked = []
    for entry in SUPPORT_ENTRIES:
        question_tokens = set(re.findall(
            r"\b[a-z0-9]+\b",
            str(entry["question"]).casefold(),
        )) - stop_words
        keyword_tokens = set(re.findall(
            r"\b[a-z0-9]+\b",
            str(entry["keywords"]).casefold(),
        )) - stop_words
        answer_tokens = set(re.findall(
            r"\b[a-z0-9]+\b",
            str(entry["text"]).casefold(),
        )) - stop_words
        score = (
            0.5 * len(query_tokens & question_tokens) / len(query_tokens)
            + 0.3 * len(query_tokens & keyword_tokens) / len(query_tokens)
            + 0.2 * len(query_tokens & answer_tokens) / len(query_tokens)
        )
        if score:
            ranked.append({
                **entry,
                "score": score,
                "matched_words": sorted(query_tokens & question_tokens),
            })
    ranked.sort(key=lambda result: result["score"], reverse=True)
    ranked = ranked[:1]
    if not ranked:
        return {"answer": _SUPPORT_FALLBACK, "supported": False, "section": None}

    match = ranked[0]
    normalized_score = float(match["score"])
    if normalized_score < 0.35:
        return {"answer": _SUPPORT_FALLBACK, "supported": False, "section": None}

    return {
        "answer": str(match["text"]),
        "supported": True,
        "section": str(match["section"]),
    }


_SUPPORT_FALLBACK = (
    "I couldn't find a reliable answer in the TrustRAG user manual. "
    "Try asking about adding files, links, text, images, fresh web search, "
    "citations, privacy, file limits, or account access. For another issue, share its exact error "
    "message with the project maintainer."
)

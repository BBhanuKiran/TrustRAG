import re


SUPPORT_ENTRIES = [
    {
        "section": "Purpose",
        "question": "What is TrustRAG and what is it for?",
        "text": (
            "TrustRAG is an evidence-first research assistant for text-based PDF "
            "documents. It finds relevant passages, drafts an answer from those "
            "passages, and shows the source document and page so you can verify it."
        ),
        "keywords": "purpose about project research PDF evidence citations",
    },
    {
        "section": "Quick start",
        "question": "How do I get started and upload a document?",
        "text": (
            "Create an account, open Documents, choose a text-based PDF up to "
            "20 MB and 500 pages, and select Upload PDF. Wait for the indexing confirmation, "
            "then open Research and ask a question about that document."
        ),
        "keywords": "how to use start signup account upload add PDF index",
    },
    {
        "section": "Citations",
        "question": "How do citations and evidence work?",
        "text": (
            "TrustRAG retrieves passages from your indexed documents and includes "
            "source citations with page numbers when it can support an answer. "
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
            "strong evidence in your indexed documents. Try adding a relevant "
            "document or rephrasing the question. It should not be treated as a "
            "general-purpose or infallible source of facts."
        ),
        "keywords": "unsupported not found abstain no answer missing evidence",
    },
    {
        "section": "Privacy",
        "question": "Who can access my documents and how are they processed?",
        "text": (
            "Each account's documents and search results are isolated by account "
            "ownership. TrustRAG sends only retrieved evidence needed to generate "
            "an answer to the server-configured hosted AI provider. Review that "
            "provider's data-retention and privacy terms before uploading "
            "confidential material. Do not upload data you are not authorized to share."
        ),
        "keywords": "privacy security private other user account sharing provider",
    },
    {
        "section": "File support",
        "question": "Which files can I upload and what are the limits?",
        "text": (
            "The current website accepts text-based PDF files up to 20 MB and "
            "500 pages each. Each account may index up to 100 documents and "
            "5,000 passages. "
            "Scanned or image-only PDFs are not searchable because OCR is not "
            "currently included. Add searchable text or OCR the file before upload."
        ),
        "keywords": "file type format limit upload size scanned OCR PDF",
    },
    {
        "section": "Support",
        "question": (
            "Does TrustRAG guarantee accurate answers, and what should I do "
            "if an answer looks wrong?"
        ),
        "text": (
            "Inspect the cited passage and check the original PDF page. If evidence "
            "is missing, upload a relevant source and ask a more specific question. "
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
    "Try asking about uploading PDFs, citations, unsupported questions, privacy, "
    "file limits, or account access. For another issue, share its exact error "
    "message with the project maintainer."
)

from pathlib import Path
import re

from pypdf import PdfReader


BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"


def tokenize(text):
    """Convert text into lowercase words."""
    return set(re.findall(r"\b[a-zA-Z0-9]+\b", text.lower()))


def load_txt_documents(file_path):
    """Load a TXT file and split it into separate sections."""
    text = Path(file_path).read_text(encoding="utf-8")

    sections = re.split(r"\n\s*\n", text.strip())

    documents = []

    for section in sections:
        section = section.strip()

        if section:
            documents.append({
                "source": Path(file_path).name,
                "page": None,
                "text": section,
            })

    return documents


def load_pdf_documents(file_path):
    """Extract text from a PDF while preserving page numbers."""
    reader = PdfReader(str(file_path))
    documents = []

    for page_number, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""

        if text.strip():
            documents.append({
                "source": Path(file_path).name,
                "page": page_number,
                "text": text.strip(),
            })

    return documents


def load_all_documents():
    """Load the supported documents from the data folder."""
    documents = []

    txt_path = DATA_DIR / "knowledge.txt"
    pdf_path = DATA_DIR / "security_guide.pdf"

    if txt_path.exists():
        documents.extend(load_txt_documents(txt_path))
    else:
        print(f"Warning: {txt_path.name} was not found.")

    if pdf_path.exists():
        documents.extend(load_pdf_documents(pdf_path))
    else:
        print(f"Warning: {pdf_path.name} was not found.")

    return documents


def search_documents(query, documents, top_k=3):
    """Rank documents by the proportion of query words they match."""
    query_words = tokenize(query)

    if not query_words:
        return []

    results = []

    for document in documents:
        document_words = tokenize(document["text"])
        matched_words = query_words & document_words

        if matched_words:
            score = len(matched_words) / len(query_words)

            results.append({
                **document,
                "score": score,
                "matched_words": sorted(matched_words),
            })

    results.sort(key=lambda item: item["score"], reverse=True)

    return results[:top_k]


def main():
    documents = load_all_documents()

    print(f"Loaded {len(documents)} document sections/pages.")

    if not documents:
        print("No documents were loaded. Check your data folder.")
        return

    while True:
        query = input("\nAsk a security question (or type 'exit'): ").strip()

        if query.lower() == "exit":
            print("TrustRAG search closed.")
            break

        results = search_documents(query, documents)

        if not results:
            print("No matching documents found.")
            continue

        for rank, result in enumerate(results, start=1):
            print(f"\nResult {rank}")
            print(f"Score: {result['score']:.2f}")
            print(f"Source: {result['source']}")

            if result["page"] is not None:
                print(f"Page: {result['page']}")

            print(f"Matched words: {', '.join(result['matched_words'])}")
            print(f"Text: {result['text'][:500]}")


if __name__ == "__main__":
    main()
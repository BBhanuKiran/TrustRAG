from pathlib import Path
import re


def load_documents(file_path):
    text = Path(file_path).read_text(encoding="utf-8")
    sections = re.split(r"\n\s*\n", text.strip())
    return [s.strip() for s in sections if s.strip()]


def tokenize(text):
    return re.findall(r"\b[a-zA-Z0-9]+\b", text.lower())


def search_documents(query, documents, top_k=3):
    query_words = set(tokenize(query))

    if not query_words:
        return []

    results = []

    for document in documents:
        document_words = set(tokenize(document))
        matched = query_words & document_words

        if matched:
            score = len(matched) / len(query_words)
            results.append({
                "text": document,
                "score": score,
                "matched_words": sorted(matched),
            })

    results.sort(
        key=lambda item: item["score"],
        reverse=True
    )
    return results[:top_k]


def main():
    data_path = Path(__file__).parent / "data" / "knowledge.txt"

    if not data_path.exists():
        print("ERROR: data/knowledge.txt was not found.")
        return

    documents = load_documents(data_path)

    print("\n=== TrustRAG Evidence Search ===")
    print(f"Loaded {len(documents)} sections.")
    print("Type 'exit' to quit.")

    while True:
        query = input("\nAsk a question: ").strip()

        if query.lower() == "exit":
            break

        results = search_documents(query, documents)

        if not results:
            print("No matching evidence found.")
            continue

        for i, result in enumerate(results, start=1):
            print(f"\nResult {i}")
            print(f"Score: {result['score']:.2f}")
            print(f"Matched: {', '.join(result['matched_words'])}")
            print(result["text"])


if __name__ == "__main__":
    main()
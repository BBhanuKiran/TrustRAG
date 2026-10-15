from pathlib import Path
from pypdf import PdfReader


def read_pdf(pdf_path):
    path = Path(pdf_path)

    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path}")

    reader = PdfReader(str(path))
    pages = []

    for page_number, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""

        if text.strip():
            pages.append({
                "source": path.name,
                "page": page_number,
                "text": text.strip(),
            })

    return pages


def main():
    pdf_path = (
        Path(__file__).parent
        / "data"
        / "security_guide.pdf"
    )

    try:
        pages = read_pdf(pdf_path)

        print("PDF:", pdf_path.name)
        print("Pages containing text:", len(pages))

        for item in pages[:2]:
            print(f"\nSource: {item['source']}")
            print(f"Page: {item['page']}")
            print(item["text"][:500])

        if not pages:
            print("No extractable text found.")

    except Exception as error:
        print("PDF reading failed:", error)


if __name__ == "__main__":
    main()
from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas


def create_sample_pdf():
    data_folder = Path(__file__).parent / "data"
    data_folder.mkdir(exist_ok=True)

    pdf_path = data_folder / "security_guide.pdf"

    pdf = canvas.Canvas(str(pdf_path), pagesize=letter)

    sections = [
        (
            "Cybersecurity Guide",
            "This document explains basic security practices."
        ),
        (
            "Phishing",
            "Phishing emails may contain suspicious links, "
            "unexpected attachments, and urgent requests. "
            "Never share passwords through email."
        ),
        (
            "Password Security",
            "Use long, unique passwords for each service. "
            "Enable multi-factor authentication whenever possible."
        ),
    ]

    y = 750

    for heading, content in sections:
        pdf.setFont("Helvetica-Bold", 16)
        pdf.drawString(72, y, heading)
        y -= 30

        pdf.setFont("Helvetica", 11)
        for line in content.split(". "):
            pdf.drawString(72, y, line)
            y -= 20

        y -= 25

    pdf.save()
    print(f"Sample PDF created: {pdf_path}")


if __name__ == "__main__":
    create_sample_pdf()
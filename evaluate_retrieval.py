import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from answering import DEFAULT_EVIDENCE_THRESHOLD
from rag_engine import EvidenceIndex


ROOT_DIR = Path(__file__).parent
CASES_PATH = ROOT_DIR / "evaluation" / "retrieval_cases.json"
SAMPLE_PDF_PATH = ROOT_DIR / "data" / "security_guide.pdf"


def load_cases() -> list[dict[str, Any]]:
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not cases:
        raise ValueError("The retrieval evaluation dataset must contain cases.")
    return cases


def evaluate() -> bool:
    cases = load_cases()
    if not SAMPLE_PDF_PATH.is_file():
        raise FileNotFoundError(f"Evaluation sample PDF not found: {SAMPLE_PDF_PATH}")

    with tempfile.TemporaryDirectory(prefix="trustrag-eval-") as temporary_dir:
        index = EvidenceIndex(Path(temporary_dir) / "evaluation.sqlite3")
        index.add_pdf(SAMPLE_PDF_PATH.name, SAMPLE_PDF_PATH.read_bytes())

        passed = 0
        reciprocal_ranks = []

        for case in cases:
            evidence = index.search(case["query"], top_k=5)
            supported = any(
                float(result["score"]) >= DEFAULT_EVIDENCE_THRESHOLD
                for result in evidence
            )
            relevant_rank = next(
                (
                    rank
                    for rank, result in enumerate(evidence, start=1)
                    if result["source"] == case["expected_source"]
                    and result["page"] == case["expected_page"]
                    and float(result["score"]) >= DEFAULT_EVIDENCE_THRESHOLD
                ),
                None,
            )
            reciprocal_ranks.append(1 / relevant_rank if relevant_rank else 0.0)
            case_passed = (
                supported == case["answerable"]
                and (
                    not case["answerable"]
                    or relevant_rank is not None
                )
            )
            passed += int(case_passed)
            status = "PASS" if case_passed else "FAIL"
            top_score = float(evidence[0]["score"]) if evidence else 0.0
            print(
                f"{status} | score={top_score:.3f} | "
                f"query={case['query']!r}"
            )

    mean_reciprocal_rank = sum(reciprocal_ranks) / len(reciprocal_ranks)
    print(
        f"\nRetrieval evaluation: {passed}/{len(cases)} passed; "
        f"mean reciprocal rank={mean_reciprocal_rank:.3f}; "
        f"evidence threshold={DEFAULT_EVIDENCE_THRESHOLD:.2f}"
    )
    return passed == len(cases)


if __name__ == "__main__":
    sys.exit(0 if evaluate() else 1)

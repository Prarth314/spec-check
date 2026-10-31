"""Repeat benchmark questions; keep retrieval and answer metrics separate."""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8001")
    parser.add_argument("--questions", type=Path, default=ROOT / "evaluation/questions.json")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--allow-evidence-only", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 10:
        parser.error("repeats must be between 1 and 10")
    cases = json.loads(args.questions.read_text(encoding="utf-8"))
    target = args.output or ROOT / "evaluation/runs" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target.mkdir(parents=True, exist_ok=True)
    with httpx.Client(base_url=args.url, timeout=90) as client:
        health = client.get("/api/health").raise_for_status().json()
        if not health["llm_configured"] and not args.allow_evidence_only:
            parser.error("No LLM configured. Configure a key/model or use --allow-evidence-only for a retrieval baseline.")
        docs = client.get("/api/documents").raise_for_status().json()
        names = {d["name"]: d["id"] for d in docs}
        missing = sorted({name for c in cases for name in c["files"]} - names.keys())
        if missing:
            parser.error("Upload these PDFs first: " + ", ".join(missing))
        runs, grades = [], []
        for case in cases:
            for repeat in range(1, args.repeats + 1):
                result = client.post("/api/ask", json={"question":case["question"], "document_ids":[names[f] for f in case["files"]]}).raise_for_status().json()
                gold = case.get("gold")
                retrieved = {(e["name"],e["page"]) for e in result["evidence"]}
                citations = {(c["name"],c["page"]) for claim in result["claims"] for c in claim["citations"]}
                expected_pages = {(p["file"],p["page"]) for p in gold.get("pages",[])} if gold else set()
                run = {"case_id":case["id"], "repeat":repeat, "category":case["category"], "gold":gold, "result":result,
                       "retrieval_page_hit": expected_pages.issubset(retrieved) if expected_pages else None,
                       "citation_page_match": (expected_pages.issubset(citations) and citations.issubset(expected_pages)) if expected_pages and result["mode"] == "llm" else None}
                runs.append(run)
                grades.append({"case_id":case["id"],"repeat":repeat,"exact_spec_correct":None,"citation_support_correct":None,
                               "abstention_correct":None,"notes":""})
                print(f"{case['id']} [{repeat}/{args.repeats}]: {result['status']}")
    (target / "responses.json").write_text(json.dumps({"model":health["model"],"corpus":docs,"runs":runs},indent=2),encoding="utf-8")
    (target / "grades.json").write_text(json.dumps(grades,indent=2),encoding="utf-8")
    print(f"Saved responses and ungraded rubric to {target}. No answer accuracy is claimed until graded.")


if __name__ == "__main__":
    main()

"""Report explicit denominators; never count missing grades as correct."""
import argparse
from collections import defaultdict
import json
from pathlib import Path


def rate(values):
    values = [v for v in values if type(v) is bool]
    return {"correct":sum(values),"graded":len(values),"percent":round(100*sum(values)/len(values),2) if values else None}


def build_report(responses, grades):
    runs = responses["runs"]
    groups = defaultdict(list)
    for r in runs:
        result = r["result"]
        signature = {"status":result["status"], "missing":result["missing"], "claims":[{"text":c["text"],"pages":sorted((s["name"],s["page"]) for s in c["citations"])} for c in result["claims"]]}
        groups[r["case_id"]].append((result, json.dumps(signature,sort_keys=True)))
    # Only generated answers/abstentions count, not deterministic evidence-only output.
    consistency = [len({signature for _,signature in group}) == 1 for group in groups.values()
                   if len(group) > 1 and all(r["mode"] == "llm" and r["status"] != "error" for r,_ in group)]
    expected_keys = {(r["case_id"],r["repeat"]) for r in runs}
    grade_keys = [(g["case_id"],g["repeat"]) for g in grades]
    if set(grade_keys) != expected_keys or len(grade_keys) != len(expected_keys):
        raise ValueError("Grades must match every response exactly once")
    return {"model":responses["model"],"questions":len(groups),"runs":len(runs),
            "provider_errors":sum(r["result"]["status"] == "error" for r in runs),
            "retrieval_page_coverage":rate(r["retrieval_page_hit"] for r in runs),
            "citation_page_match":rate(r["citation_page_match"] for r in runs),
            "exact_spec_accuracy":rate(g["exact_spec_correct"] for g in grades),
            "citation_support_accuracy":rate(g["citation_support_correct"] for g in grades),
            "negative_test_abstention_accuracy":rate(g["abstention_correct"] for g in grades),
            "exact_output_repeat_consistency":rate(consistency),
            "note":"Null percentages mean ungraded/unavailable. Exact output consistency is stricter than semantic consistency; manually inspect paraphrases. Page matches alone do not establish factual support."}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run_directory",type=Path)
    args = parser.parse_args()
    report = build_report(json.loads((args.run_directory/"responses.json").read_text(encoding="utf-8")),
                          json.loads((args.run_directory/"grades.json").read_text(encoding="utf-8")))
    output = json.dumps(report,indent=2)
    (args.run_directory/"report.json").write_text(output,encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()

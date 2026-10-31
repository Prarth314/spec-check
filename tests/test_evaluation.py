import json
import pytest
from scripts.report import build_report


def test_evidence_mode_never_counts_as_repeat_consistency():
    result = {"mode":"local","status":"evidence_only","claims":[],"missing":"Key not configured"}
    runs = [{"case_id":"Q1","repeat":i,"result":result,"retrieval_page_hit":True,"citation_page_match":None} for i in (1,2,3)]
    grades = [{"case_id":"Q1","repeat":i,"exact_spec_correct":None,"citation_support_correct":None,"abstention_correct":None} for i in (1,2,3)]
    report = build_report({"model":None,"runs":runs},grades)
    assert report["exact_output_repeat_consistency"]["graded"] == 0
    assert report["exact_spec_accuracy"]["percent"] is None
    assert report["retrieval_page_coverage"] == {"correct":3,"graded":3,"percent":100.0}
    with pytest.raises(ValueError):
        build_report({"model":None,"runs":runs},grades[:-1])


def test_benchmark_covers_required_categories_and_size():
    from pathlib import Path
    questions = json.loads((Path(__file__).resolve().parents[1]/"evaluation/questions.json").read_text())
    assert len(questions) == 24
    assert len({f for q in questions for f in q["files"]}) == 6
    assert {"absolute maximum","pinout","thermal","comparison","absent specification"}.issubset({q["category"] for q in questions})

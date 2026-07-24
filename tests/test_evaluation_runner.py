import json

from scout.evaluation.run_eval import _metrics, run_evaluation


def test_evaluation_dataset_runs_and_writes_reports(tmp_path):
    report = run_evaluation(output_dir=tmp_path)

    assert report["dataset_version"] == "scout_eval_v1"
    assert report["case_count"] >= 15
    assert "metrics" in report
    assert "quality_gates" in report
    assert "failed_cases" in report
    assert (tmp_path / "scout_eval_v1_report.json").exists()
    assert (tmp_path / "scout_eval_v1_summary.md").exists()

    machine_report = json.loads((tmp_path / "scout_eval_v1_report.json").read_text())
    assert machine_report["case_count"] == report["case_count"]
    assert "authorization_violations" in machine_report["metrics"]


def test_precision_at_3_excludes_mixed_domain_cases():
    report_items = [
        {
            "query_id": "REC-001",
            "precision_eligible": True,
            "precision_at_3": None,
            "relevant_product_ids": ["FTW-004", "FTW-008"],
            "available_relevant_product_ids": ["FTW-004", "FTW-008"],
            "returned_product_ids": ["FTW-004"],
            "budget_compliant": True,
            "inventory_accurate": None,
            "failed_checks": [],
            "grounded": True,
            "hallucination_detected": False,
            "protected_action_safe": None,
            "tool_success_rate": None,
            "memory_correct": None,
            "latency_ms": 1.0,
            "task_completed": True,
            "safe_stop_ok": True,
            "status": "completed",
        },
        {
            "query_id": "ORDER-001",
            "precision_eligible": False,
            "precision_at_3": None,
            "relevant_product_ids": ["FTW-004"],
            "available_relevant_product_ids": ["FTW-004"],
            "returned_product_ids": [],
            "budget_compliant": None,
            "inventory_accurate": None,
            "failed_checks": [],
            "grounded": True,
            "hallucination_detected": False,
            "protected_action_safe": None,
            "tool_success_rate": None,
            "memory_correct": None,
            "latency_ms": 1.0,
            "task_completed": True,
            "status": "completed",
            "errors": [],
        },
    ]

    metrics = _metrics(report_items)
    assert metrics["recommendation_case_count"] == 1
    assert metrics["relevant_products_returned_in_top_3"] == 1
    assert metrics["total_eligible_top_3_positions"] == 3
    assert metrics["precision_at_3"] == 1 / 3


def test_availability_aware_precision_uses_available_relevant_denominator():
    report_items = [
        {
            "query_id": "SUB-001",
            "precision_eligible": True,
            "precision_at_3": 1 / 3,
            "relevant_product_ids": ["FTW-002", "FTW-010"],
            "available_relevant_product_ids": ["FTW-002"],
            "returned_product_ids": ["FTW-002"],
            "budget_compliant": True,
            "inventory_accurate": True,
            "failed_checks": [],
            "grounded": True,
            "hallucination_detected": False,
            "protected_action_safe": None,
            "tool_success_rate": 1.0,
            "memory_correct": None,
            "latency_ms": 1.0,
            "task_completed": True,
            "safe_stop_ok": True,
            "status": "completed",
        },
    ]

    metrics = _metrics(report_items)
    assert metrics["precision_at_3"] == 1 / 3
    assert metrics["availability_aware_relevant_products_returned_in_top_3"] == 1
    assert metrics["availability_aware_total_eligible_positions"] == 1
    assert metrics["availability_aware_precision_at_3"] == 1.0

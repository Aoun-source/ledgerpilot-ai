"""Demo-mode recordings and the live evaluation script, run against the local fake services."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from fake_services import FakeServices

from ledgerpilot import recording
from ledgerpilot.audit import AuditLog
from ledgerpilot.config import Settings
from ledgerpilot.pipeline import Pipeline, load_case_folder
from ledgerpilot.schemas import Route

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "data" / "samples"
KIND = {"x-inv": "invoice", "x-po": "po", "x-grn": "grn"}


@pytest.fixture
def svc(monkeypatch, tmp_path):
    with FakeServices() as s:
        env = {"EVOLUS_API_BASE": f"{s.base}/api/v1", "EVOLUS_CHAT_BASE": f"{s.base}/v1",
               "VLLM_BASE_URL": f"{s.base}/v1", "VLLM_API_KEY": "vk", "EVOLUS_API_KEY": "k", "EVOLUS_APP_ID": "app",
               "EVOLUS_AGENT_ID": "agent", "EVOLUS_EXTRACTOR_INVOICE_ID": "x-inv", "EVOLUS_EXTRACTOR_PO_ID": "x-po",
               "EVOLUS_EXTRACTOR_GRN_ID": "x-grn", "EVOLUS_WORKFLOW_ID": "wf",
               "RECORDINGS_DIR": str(tmp_path / "recordings")}
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        s.current = {}
        s.extract_data = lambda eid, fn: s.current[KIND[eid]] if s.current.get(KIND[eid]) is not None else 422
        yield s


def serve(svc, case: str) -> dict:
    truth = json.loads((SAMPLES / case / "truth.json").read_text())
    svc.current = truth
    return truth


def test_recording_round_trip_keeps_everything_the_ui_shows(svc, tmp_path):
    serve(svc, "case_07")
    s = Settings()
    s.audit_db = tmp_path / "a.db"
    res = Pipeline(s, AuditLog(s.audit_db)).run(load_case_folder(SAMPLES / "case_07"), label="case_07")
    path = recording.save(s.recordings_dir, res, "case_07", "Qwen/Qwen2.5-32B-Instruct", "test")
    back, meta = recording.load(s.recordings_dir, "case_07")
    assert path.name == "case_07.json" and recording.available(s.recordings_dir) == ["case_07"]
    assert meta["case"] == "case_07" and meta["model"] == "Qwen/Qwen2.5-32B-Instruct" and meta["at"].endswith("+00:00")
    assert back.route is Route.HOLD and back.rule_route is Route.HOLD and back.money_at_risk == res.money_at_risk
    assert [d.as_row() for d in back.discrepancies] == [d.as_row() for d in res.discrepancies]
    assert back.agent.explanation == res.agent.explanation and back.agent.route is res.agent.route
    assert back.extracted == res.extracted and back.steps == res.steps and back.email_draft == res.email_draft


def test_damaged_or_missing_recording_is_skipped(tmp_path):
    (tmp_path / "case_01.json").write_text("{not json")
    assert recording.load(tmp_path, "case_01") is None
    assert recording.load(tmp_path, "case_99") is None
    assert recording.available(tmp_path / "nowhere") == []


def _load_eval():
    spec = importlib.util.spec_from_file_location("run_eval", ROOT / "eval" / "run_eval.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_eval_scores_all_cases_and_records_them(svc, tmp_path):
    cases = sorted(p.name for p in SAMPLES.glob("case_*"))
    run_eval = _load_eval()
    real_run = Pipeline.run

    def run_serving_truth(self, docs, label="", **kw):
        serve(svc, label)
        return real_run(self, docs, label=label, **kw)

    Pipeline.run = run_serving_truth
    try:
        summary = run_eval.main(["--label", "fake", "--out", str(tmp_path / "docs"),
                                 "--audit-db", str(tmp_path / "eval.db")])
    finally:
        Pipeline.run = real_run
    assert summary["cases"] == len(cases) and summary["false_approvals"] == 0
    assert summary["routing_accuracy"] == 1.0 and summary["model"] == "Qwen/Qwen2.5-32B-Instruct"
    md = (tmp_path / "docs" / "evaluation.md").read_text()
    assert "## Accuracy by case type" in md and "| False approvals | 0 of" in md
    assert recording.available(tmp_path / "recordings") == cases

"""End-to-end pipeline test with the network replaced by in-test stand-ins.

The stand-ins live only in this test file: they return the ground-truth JSON
so we can check routing, audit logging and failure handling without credits.
The real app always calls Evolus and the AMD-hosted agent.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ledgerpilot import pipeline as pl
from ledgerpilot.agent_client import parse_verdict
from ledgerpilot.audit import AuditLog
from ledgerpilot.config import Settings
from ledgerpilot.evolus_client import EvolusError, ExtractionResult
from ledgerpilot.schemas import Route

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "data" / "samples"


@pytest.fixture
def settings(tmp_path, monkeypatch):
    for k, v in {"EVOLUS_API_KEY": "k", "EVOLUS_APP_ID": "app", "EVOLUS_AGENT_ID": "agent",
                 "EVOLUS_EXTRACTOR_INVOICE_ID": "x-inv", "EVOLUS_EXTRACTOR_PO_ID": "x-po",
                 "EVOLUS_EXTRACTOR_GRN_ID": "x-grn", "EVOLUS_WORKFLOW_ID": "wf"}.items():
        monkeypatch.setenv(k, v)
    s = Settings()
    s.audit_db = tmp_path / "audit.db"
    return s


def make_pipeline(settings, case_dir: Path, agent_route: str | None = "same", agent_fails=False):
    truth = json.loads((case_dir / "truth.json").read_text())
    p = pl.Pipeline(settings, AuditLog(settings.audit_db))
    ids = {v: k for k, v in p.extractor_ids.items()}

    def fake_extract(extractor_id, filename, content):
        kind = ids[extractor_id]
        if truth.get(kind) is None:
            raise EvolusError("unreadable document", 422)
        return ExtractionResult(data={"data": truth[kind]}, execution_id=f"exec-{kind}", audit_id=None)

    def fake_review(case):
        if agent_fails:
            raise ConnectionError("vLLM endpoint unreachable")
        route = case["rule_route"] if agent_route == "same" else agent_route
        return parse_verdict(json.dumps({"route": route, "explanation": "checked", "evidence": ["vendor master"],
                                         "supplier_question": "Please confirm the price."}), "conv-1", 0.4)

    p.evolus.extract = fake_extract
    p.evolus.draft_supplier_email = lambda facts: "Dear supplier, ..."
    p.evolus.start_workflow = lambda text, params: "wf-exec-1"
    p.agent.review = fake_review
    return p, truth


@pytest.mark.parametrize("case", sorted(p.name for p in SAMPLES.glob("case_*")))
def test_pipeline_routes_all_cases(settings, case):
    p, truth = make_pipeline(settings, SAMPLES / case)
    res = p.run(pl.load_case_folder(SAMPLES / case), label=case)
    assert res.route.value == truth["expected_route"], res.error
    assert res.audit_id is not None
    if res.route in (Route.HOLD, Route.FRAUD):
        assert res.email_draft and res.workflow_execution_id == "wf-exec-1"


def test_agent_cannot_approve_a_fraud_case(settings):
    p, _ = make_pipeline(settings, SAMPLES / "case_15", agent_route="approve_for_payment")
    res = p.run(pl.load_case_folder(SAMPLES / "case_15"))
    assert res.route is Route.FRAUD


def test_agent_outage_falls_back_to_rules_and_is_logged(settings):
    p, _ = make_pipeline(settings, SAMPLES / "case_07", agent_fails=True)
    res = p.run(pl.load_case_folder(SAMPLES / "case_07"))
    assert res.route is Route.HOLD and "agent_error" in res.trace


def test_agent_outage_on_clean_invoice_hands_it_to_a_person(settings):
    p, _ = make_pipeline(settings, SAMPLES / "case_01", agent_fails=True)
    res = p.run(pl.load_case_folder(SAMPLES / "case_01"))
    assert res.rule_route is Route.APPROVE and res.route is Route.HOLD
    assert [d.code for d in res.discrepancies] == ["LOW_CONFIDENCE"]
    assert res.confidence_reasons == ["the agent's review didn't complete"]
    assert res.money_at_risk == 0


def test_unreadable_agent_reply_on_clean_invoice_is_held(settings):
    p, _ = make_pipeline(settings, SAMPLES / "case_01", agent_route="pay it")
    res = p.run(pl.load_case_folder(SAMPLES / "case_01"))
    assert res.route is Route.HOLD and "couldn't be read" in res.discrepancies[0].message


def test_stricter_agent_is_explained(settings):
    p, _ = make_pipeline(settings, SAMPLES / "case_01", agent_route="hold_for_review")
    res = p.run(pl.load_case_folder(SAMPLES / "case_01"))
    assert res.route is Route.HOLD and [d.code for d in res.discrepancies] == ["AGENT_CONCERN"]
    assert res.confidence_reasons == ["the agent and the checks disagree"]


def test_agreeing_agent_gives_high_confidence(settings):
    p, _ = make_pipeline(settings, SAMPLES / "case_07")
    res = p.run(pl.load_case_folder(SAMPLES / "case_07"))
    assert res.route is Route.HOLD and res.confidence_reasons == []


@pytest.mark.parametrize("blob,needle", [
    (b"", "is empty"),
    (b"PK\x03\x04 a zip file", "isn't a PDF, PNG or JPG"),
    (b"%PDF-1.4\n1 0 obj <<garbled", "damaged or cut off"),
])
def test_bad_files_are_stopped_before_evolus(settings, blob, needle):
    p, _ = make_pipeline(settings, SAMPLES / "case_01")
    calls, real_extract = [], p.evolus.extract
    p.evolus.extract = lambda *a: calls.append(a) or real_extract(*a)
    docs = pl.load_case_folder(SAMPLES / "case_01")
    docs["invoice"] = ("upload.pdf", blob)
    res = p.run(docs)
    assert res.route is Route.ERROR and needle in res.error and "Traceback" not in res.error
    assert len(calls) == 2  # PO and delivery note were read; the bad invoice never left the machine
    assert res.steps[-1]["ok"] is False


def test_images_pass_the_file_check():
    pl.check_document("invoice", "scan.png", b"\x89PNG\r\n\x1a\n...")
    pl.check_document("invoice", "scan.jpg", b"\xff\xd8\xff\xe0...")


def test_corrupt_sample_pdf_is_caught_locally(settings):
    p, _ = make_pipeline(settings, SAMPLES / "case_20")
    res = p.run(pl.load_case_folder(SAMPLES / "case_20"))
    assert res.route is Route.ERROR and "damaged or cut off" in res.error


def test_reprocessing_same_invoice_is_caught_as_duplicate(settings):
    p, _ = make_pipeline(settings, SAMPLES / "case_01")
    first = p.run(pl.load_case_folder(SAMPLES / "case_01"))
    second = p.run(pl.load_case_folder(SAMPLES / "case_01"))
    assert first.route is Route.APPROVE
    assert second.route is Route.FRAUD
    assert "DUPLICATE_INVOICE" in {d.code for d in second.discrepancies}


def test_unwrap_handles_common_shapes():
    assert pl.unwrap('{"a": 1}') == {"a": 1}
    assert pl.unwrap([{"result": {"a": 1}}]) == {"a": 1}
    assert pl.unwrap("not json") == {}


def test_parse_verdict_rejects_unknown_route():
    v = parse_verdict('{"route": "pay_immediately", "explanation": "x"}')
    assert v.route is None and not v.parsed

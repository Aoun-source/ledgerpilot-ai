"""Real HTTP tests: the actual clients talk to a local fake of Evolus and vLLM."""
from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest
from fake_services import FakeServices

from ledgerpilot.agent_client import ClerkAgent, vllm_health
from ledgerpilot.audit import AuditLog
from ledgerpilot.config import Settings
from ledgerpilot.evolus_client import EvolusClient, EvolusError
from ledgerpilot.pipeline import Pipeline, load_case_folder
from ledgerpilot.schemas import Route

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "data" / "samples"
KIND = {"x-inv": "invoice", "x-po": "po", "x-grn": "grn"}


@pytest.fixture
def svc():
    with FakeServices() as s:
        yield s


@pytest.fixture
def settings(svc, monkeypatch, tmp_path):
    env = {"EVOLUS_API_BASE": f"{svc.base}/api/v1", "EVOLUS_CHAT_BASE": f"{svc.base}/v1",
           "VLLM_BASE_URL": f"{svc.base}/v1", "VLLM_API_KEY": "vk",
           "EVOLUS_API_KEY": "secret-key", "EVOLUS_APP_ID": "app", "EVOLUS_AGENT_ID": "agent",
           "EVOLUS_EXTRACTOR_INVOICE_ID": "x-inv", "EVOLUS_EXTRACTOR_PO_ID": "x-po", "EVOLUS_EXTRACTOR_GRN_ID": "x-grn",
           "EVOLUS_WORKFLOW_ID": "wf", "EVOLUS_LIBRARY_ID": "lib"}
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    s = Settings()
    s.audit_db = tmp_path / "audit.db"
    return s


def fast_client(settings) -> EvolusClient:
    return EvolusClient(settings, timeout=5, max_retries=2, backoff=0)


# ---------------------------------------------------------------- Evolus REST
def test_extract_sends_auth_headers_and_correct_mime(svc, settings):
    svc.extract_data = lambda eid, fn: {"data": {"invoice_number": "INV-1"}}
    r = fast_client(settings).extract("x-inv", "scan.png", b"\x89PNG fake")
    call = svc.calls[-1]
    assert call["path"].startswith("/api/v1/agents/agent/json/x-inv/ask-file")
    assert "useWebhook=false" in call["path"]
    assert call["headers"]["x-apikey"] == "secret-key" and call["headers"]["x-application-id"] == "app"
    assert call["filename"] == "scan.png" and call["part_content_type"] == "image/png"
    assert r.data == {"data": {"invoice_number": "INV-1"}} and r.execution_id == "ex-x-inv"


def test_rate_limit_is_retried(svc, settings):
    svc.fail[r"ask-file"] = [429, 429]
    fast_client(settings).extract("x-inv", "a.pdf", b"%PDF")
    assert svc.count(r"ask-file") == 3


def test_server_error_gives_up_after_retries(svc, settings):
    svc.fail[r"ask-file"] = [503, 503, 503, 503]
    with pytest.raises(EvolusError) as e:
        fast_client(settings).extract("x-inv", "a.pdf", b"%PDF")
    assert e.value.status == 503 and svc.count(r"ask-file") == 3


@pytest.mark.parametrize("status,needle", [(402, "credits"), (409, "switched off"), (401, "API key")])
def test_clear_errors(svc, settings, status, needle):
    svc.fail[r"ask-file"] = [status]
    with pytest.raises(EvolusError, match=needle):
        fast_client(settings).extract("x-inv", "a.pdf", b"%PDF")


def test_non_json_response_is_an_error(svc, settings):
    svc.extract_data = lambda eid, fn: "NOT_JSON"
    with pytest.raises(EvolusError, match="non-JSON"):
        fast_client(settings).extract("x-inv", "a.pdf", b"%PDF")


def test_unreachable_server_raises_evolus_error_not_crash(settings):
    with socket.socket() as sock:  # find a closed port
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    settings.evolus_api_base = f"http://127.0.0.1:{port}/api/v1"
    with pytest.raises(EvolusError, match="Could not reach"):
        fast_client(settings).extract("x-inv", "a.pdf", b"%PDF")


def test_workflow_start_not_retried_on_5xx(svc, settings):
    svc.fail[r"/execute"] = [502]
    with pytest.raises(EvolusError):
        fast_client(settings).start_workflow("case", {"route": "hold_for_review"})
    assert svc.count(r"/execute") == 1  # never risk starting the workflow twice


def test_workflow_start_and_poll(svc, settings):
    c = fast_client(settings)
    exec_id = c.start_workflow("case", {"route": "hold_for_review", "codes": "PRICE_VARIANCE"})
    assert exec_id == "wf-exec-1"
    body = svc.calls[-1]["body"]
    assert b'name="parameters"' in body and b'"route": "hold_for_review"' in body
    assert c.wait_for_execution(exec_id, timeout=5, poll=0)["status"] == "Completed"


def test_email_tool_payload(svc, settings):
    out = fast_client(settings).draft_supplier_email("facts here")
    payload = svc.calls[-1]["json"]
    assert payload == {"text": "facts here", "options": {"mode": "write", "tone": "formal"}}
    assert out.startswith("Dear supplier")


def test_library_upload_uses_english(svc, settings):
    fast_client(settings).upload_library_document("vm.pdf", b"%PDF")
    assert "language=en" in svc.calls[-1]["path"] and "/memories/lib/documents" in svc.calls[-1]["path"]


# ------------------------------------------------------------- agent + vLLM
def test_agent_uses_app_agent_model_and_bearer(svc, settings):
    v = ClerkAgent(settings).review({"rule_route": "hold_for_review", "discrepancies": []})
    call = svc.calls[-1]
    assert call["json"]["model"] == "app:agent"
    assert call["headers"]["authorization"] == "Bearer secret-key"
    assert v.route is Route.HOLD and v.conversation_id == "conv-42" and v.parsed


def test_agent_reply_in_code_fence_with_prose(svc, settings):
    svc.agent_reply = lambda case: 'Sure! {draft}\n```json\n{"route": "escalate_fraud", "explanation": "Bank changed", "evidence": "VM"}\n```'
    v = ClerkAgent(settings).review({"rule_route": "escalate_fraud"})
    assert v.route is Route.FRAUD and v.evidence == ["VM"]


def test_vllm_health_ok_and_down(svc, settings):
    h = vllm_health(settings)
    assert h["ok"] and "ledgerpilot-model" in h["models"]
    settings.vllm_base_url = "http://127.0.0.1:9/v1"
    assert vllm_health(settings, timeout=1)["ok"] is False


# --------------------------------------------- full pipeline over real HTTP
def _serve_case(svc, folder: Path):
    truth = json.loads((folder / "truth.json").read_text())

    def data(extractor_id, filename):
        doc = truth[KIND[extractor_id]]
        return 422 if doc is None else {"result": doc}
    svc.extract_data = data
    return truth


@pytest.mark.parametrize("case", sorted(p.name for p in SAMPLES.glob("case_*")))
def test_full_pipeline_over_http(svc, settings, case):
    truth = _serve_case(svc, SAMPLES / case)
    pipe = Pipeline(settings, AuditLog(settings.audit_db))
    pipe.evolus = fast_client(settings)
    res = pipe.run(load_case_folder(SAMPLES / case), label=case)
    assert res.route.value == truth["expected_route"], (res.error, res.trace)
    if res.route is not Route.ERROR:
        assert svc.count(r"/v1/chat/completions") == 1          # agent consulted once
        assert res.agent and res.agent.conversation_id == "conv-42"
        assert [s["ok"] for s in res.steps].count(False) == 0
    if res.route in (Route.HOLD, Route.FRAUD):
        assert res.email_draft and res.workflow_execution_id == "wf-exec-1"
    # never leak the full bank account to the agent
    for c in svc.calls:
        if c["path"] == "/v1/chat/completions" and truth.get("invoice"):
            assert truth["invoice"]["bank_iban"].encode() not in c["body"]


def test_pipeline_survives_evolus_outage(svc, settings):
    _serve_case(svc, SAMPLES / "case_01")
    svc.fail[r"ask-file"] = [0, 0, 0, 0]  # dropped connections
    pipe = Pipeline(settings, AuditLog(settings.audit_db))
    pipe.evolus = fast_client(settings)
    res = pipe.run(load_case_folder(SAMPLES / "case_01"))
    assert res.route is Route.ERROR and "person must process" in res.error
    assert res.audit_id is not None


def test_pipeline_agent_garbage_reply_falls_back_to_rules(svc, settings):
    _serve_case(svc, SAMPLES / "case_07")
    svc.agent_reply = lambda case: "I think it is probably fine?"
    pipe = Pipeline(settings, AuditLog(settings.audit_db))
    pipe.evolus = fast_client(settings)
    res = pipe.run(load_case_folder(SAMPLES / "case_07"))
    assert res.route is Route.HOLD and res.agent and not res.agent.parsed

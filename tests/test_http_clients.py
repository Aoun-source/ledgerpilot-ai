"""Real HTTP tests: the actual clients talk to a local fake of Evolus and the AMD model endpoint."""
from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest
from fake_services import FakeServices

from ledgerpilot.agent_client import ClerkAgent, model_health, model_speed, model_usage
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
           "AMD_BASE_URL": f"{svc.base}/v1", "AMD_API_KEY": "vk",
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


def test_extractor_id_can_carry_its_own_agent(svc, settings):
    # Each extractor made in the Evolus UI is its own agent: "agentId/formatId" targets it directly.
    svc.extract_data = lambda eid, fn: {"invoice_number": "INV-1"}
    fast_client(settings).extract("ext-agent/x-inv", "a.pdf", b"%PDF")
    assert svc.calls[-1]["path"].startswith("/api/v1/agents/ext-agent/json/x-inv/ask-file")


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


# ------------------------------------------------------- agent + AMD model
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


def test_model_health_ok_and_down(svc, settings):
    h = model_health(settings)
    assert h["ok"] and "ledgerpilot-model" in h["models"]
    assert h["weights"] == "Qwen/Qwen2.5-32B-Instruct"  # vLLM's `root`, not the served alias
    assert svc.calls[-1]["headers"]["authorization"] == "Bearer vk"
    settings.amd_base_url = "http://127.0.0.1:9/v1"
    assert model_health(settings, timeout=1)["ok"] is False


def test_model_speed_measures_tokens_per_second(svc, settings):
    s = model_speed(settings)
    call = svc.calls[-1]
    assert call["path"] == "/v1/chat/completions" and call["json"]["model"] == "ledgerpilot-model"
    assert "reasoning_effort" not in call["json"]
    assert s["ok"] and s["tokens"] == 5 and s["tokens_per_s"] > 0
    assert s["limits"] == {"x-ratelimit-remaining-requests": "29"}
    settings.amd_base_url = "http://127.0.0.1:9/v1"
    assert model_speed(settings, timeout=1)["ok"] is False


@pytest.fixture
def token_factory(svc, settings, monkeypatch):
    # The fake stands in for Token Factory: the client decides by host name
    monkeypatch.setattr("ledgerpilot.config.TOKEN_FACTORY_HOST", "127.0.0.1")
    settings.amd_model = "DeepSeek-V4-Flash"
    assert settings.token_factory
    return settings


def test_token_factory_health_uses_model_name_and_checks_catalog(svc, token_factory):
    h = model_health(token_factory)
    assert h["ok"] and h["weights"] == "DeepSeek-V4-Flash"
    token_factory.amd_model = "Retired-Model"
    h = model_health(token_factory)
    assert not h["ok"] and "isn't in the Token Factory catalog" in h["detail"] and "DeepSeek-V4-Flash" in h["detail"]


def test_token_factory_needs_a_key(svc, token_factory):
    token_factory.amd_api_key = None
    before = len(svc.calls)
    for check in (model_health, model_speed, model_usage):
        r = check(token_factory)
        assert not r["ok"] and "AMD_API_KEY" in r["detail"]
    assert len(svc.calls) == before  # nothing sent without a key


def test_reasoning_effort_is_sent_when_set(svc, token_factory):
    token_factory.amd_reasoning_effort = "low"
    assert model_speed(token_factory)["ok"]
    assert svc.calls[-1]["json"]["reasoning_effort"] == "low"


def test_token_factory_usage(svc, token_factory):
    u = model_usage(token_factory)
    call = svc.calls[-1]
    assert u["ok"] and u["usage"]["remaining"] == 4.75
    assert call["path"] == "/v1/usage?include_recent=true" and call["headers"]["authorization"] == "Bearer vk"


def test_usage_only_on_token_factory(svc, settings):
    assert not model_usage(settings)["ok"] and svc.count(r"/v1/usage") == 0


def test_rate_limit_gets_a_plain_message(svc, settings):
    svc.fail[r"/v1/chat/completions"] = [429]
    s = model_speed(settings)
    assert not s["ok"] and "Rate limited (429)" in s["detail"] and "shares one key" in s["detail"]
    svc.fail[r"/v1/models"] = [401]
    assert "Key rejected (401)" in model_health(settings)["detail"]


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

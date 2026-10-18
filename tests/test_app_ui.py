"""Click through every screen of the Streamlit app with Streamlit's AppTest,
driving the real pipeline against the local fake of Evolus and vLLM."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import streamlit as st
from fake_services import FakeServices
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
APP = str(ROOT / "app.py")
SAMPLES = ROOT / "data" / "samples"
KIND = {"x-inv": "invoice", "x-po": "po", "x-grn": "grn"}
ENV_KEYS = ["EVOLUS_API_BASE", "EVOLUS_CHAT_BASE", "EVOLUS_API_KEY", "EVOLUS_APP_ID",
            "EVOLUS_AGENT_ID", "EVOLUS_EXTRACTOR_INVOICE_ID", "EVOLUS_EXTRACTOR_PO_ID", "EVOLUS_EXTRACTOR_GRN_ID",
            "EVOLUS_WORKFLOW_ID", "EVOLUS_LIBRARY_ID", "AUDIT_DB"]


def fresh_caches():
    st.cache_resource.clear()
    st.cache_data.clear()


def all_markdown(at: AppTest) -> str:
    return "\n".join(m.value for m in at.markdown)


@pytest.fixture
def svc():
    with FakeServices() as s:
        yield s


@pytest.fixture
def configured(svc, monkeypatch, tmp_path):
    env = {"EVOLUS_API_BASE": f"{svc.base}/api/v1", "EVOLUS_CHAT_BASE": f"{svc.base}/v1",
           "AMD_BASE_URL": f"{svc.base}/v1", "AMD_API_KEY": "vk", "EVOLUS_API_KEY": "k", "EVOLUS_APP_ID": "app",
           "EVOLUS_AGENT_ID": "agent", "EVOLUS_EXTRACTOR_INVOICE_ID": "x-inv", "EVOLUS_EXTRACTOR_PO_ID": "x-po",
           "EVOLUS_EXTRACTOR_GRN_ID": "x-grn", "EVOLUS_WORKFLOW_ID": "wf", "EVOLUS_LIBRARY_ID": "lib",
           "AUDIT_DB": str(tmp_path / "ui.db")}
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    fresh_caches()
    yield svc
    fresh_caches()


def serve(svc, case: str, tamper=None):
    truth = json.loads((SAMPLES / case / "truth.json").read_text())
    if tamper:
        tamper(truth)
    svc.extract_data = lambda eid, fn: 422 if truth[KIND[eid]] is None else truth[KIND[eid]]


def goto(at: AppTest, page: str) -> AppTest:
    """Open a page from the sidebar navigation."""
    at.sidebar.radio[0].set_value(page)
    return at.run()


def nav(at: AppTest) -> str:
    return " | ".join(at.sidebar.radio[0].options)


def check_case(at: AppTest, case: str) -> AppTest:
    if at.sidebar.radio[0].value != "check":
        at = goto(at, "check")
    box = at.selectbox[0]
    box.set_value(next(o for o in box.options if o.lower().startswith(case.replace("_", " "))))
    at.run()
    next(b for b in at.button if b.label == "Run invoice check").click()
    return at.run()


def test_unconfigured_app_renders_with_clear_guidance(monkeypatch, tmp_path):
    for k in ENV_KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("AUDIT_DB", str(tmp_path / "x.db"))
    monkeypatch.setattr("ledgerpilot.config.load_dotenv", lambda *a, **k: None, raising=False)
    fresh_caches()
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    warnings = " ".join(w.value for w in at.sidebar.warning)
    assert "AMD_API_KEY" in warnings and "notebooks.amd.com/tokenfactory" in warnings and "EVOLUS_API_KEY" in warnings
    assert "not set up" in all_markdown(at)
    assert at.sidebar.radio[0].options == [":material/space_dashboard: Overview", ":material/fact_check: Check an invoice",
                                           ":material/forum: Ask the agent", ":material/inbox: Review queue (0)", ":material/history: Audit log",
                                           ":material/insights: Results", ":material/tune: Settings"]
    at = goto(at, "check")
    assert len(at.selectbox[0].options) == 24
    next(b for b in at.button if b.label == "Run invoice check").click()
    at.run()
    assert not at.exception and "Can't check invoices yet" in at.error[0].value


@pytest.mark.parametrize("case,stamp", [("case_01", "Ready to pay"), ("case_07", "Needs review"),
                                        ("case_15", "Payment blocked"), ("case_20", "Needs a person")])
def test_check_each_outcome(configured, case, stamp):
    serve(configured, case)
    at = AppTest.from_file(APP, default_timeout=60).run()
    md = all_markdown(at)
    assert ">Online</em>" in md and ">Connected</em>" in md, "both connections should show as online"
    at = check_case(at, case)
    assert not at.exception
    md = all_markdown(at)
    assert f">{stamp}</span>" in md
    if case == "case_07":
        assert "200.00" in md and "Price above the agreed PO price" in md
        assert at.text_area[0].value.startswith("Dear supplier")
        assert "Start routing workflow" in md and any("AMD MI300X (vLLM) via Evolus" in c.value for c in at.caption)
    if case == "case_15":
        assert "Bank account differs from vendor records" in md
        assert "Draft alert to the finance manager" in md


def test_model_indicator_and_speed_probe(configured):
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert "Qwen/Qwen2.5-32B-Instruct served on AMD Developer Cloud" in all_markdown(at)  # sidebar connection row
    at = goto(at, "settings")
    assert "<b>Model:</b> Qwen/Qwen2.5-32B-Instruct served on AMD Developer Cloud" in all_markdown(at)
    next(b for b in at.button if b.label == "Measure model speed").click()
    at.run()
    assert not at.exception and any("tokens/s" in c.value for c in at.caption)
    # the Token Factory-only usage button stays hidden on a vLLM endpoint
    assert not any(b.label == "Check team usage" for b in at.button)


def test_token_factory_sidebar_shows_usage(configured, svc, monkeypatch):
    # A stand-in for Token Factory: the app decides by host name, so point that host at the fake
    monkeypatch.setattr("ledgerpilot.config.TOKEN_FACTORY_HOST", "127.0.0.1")
    monkeypatch.setenv("AMD_MODEL", "DeepSeek-V4-Flash")
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    assert "served on AMD Token Factory" in all_markdown(at)
    at = goto(at, "settings")
    assert any("AMD Token Factory" in c.value and "synthetic" in c.value for c in at.caption)
    next(b for b in at.button if b.label == "Check team usage").click()
    at.run()
    assert not at.exception and at.json
    assert svc.count(r"^/v1/usage") == 1
    next(b for b in at.button if b.label == "Measure model speed").click()
    at.run()
    assert any("Rate limits left" in c.value for c in at.caption)


def test_review_queue_requires_note_to_release_blocked_payment(configured):
    serve(configured, "case_15")
    at = check_case(AppTest.from_file(APP, default_timeout=60).run(), "case_15")
    serve(configured, "case_07")
    at = check_case(at, "case_07")
    assert "Review queue (2)" in nav(at)
    at = goto(at, "queue")
    release = [b for b in at.button if b.label == "Release for payment"]
    fraud_index = 1  # queue is newest first: case_07 then case_15
    release[fraud_index].click()
    at.run()
    assert any("verified" in e.value for e in at.error)
    at.text_input[fraud_index].input("Called Acme on the number in our records; change confirmed.")
    at.run()
    [b for b in at.button if b.label == "Release for payment"][fraud_index].click()
    at.run()
    assert "Review queue (1)" in nav(at)
    [b for b in at.button if b.label == "Reject invoice"][0].click()
    at.run()
    assert "Review queue (0)" in nav(at) and not at.exception


def test_audit_log_filter_and_clear_history(configured):
    serve(configured, "case_01")
    at = check_case(AppTest.from_file(APP, default_timeout=60).run(), "case_01")
    serve(configured, "case_07")
    at = check_case(at, "case_07")
    at = goto(at, "overview")
    md = all_markdown(at)
    for key, value in (("checked", "2"), ("ready", "1"), ("review", "1"), ("blocked", "0")):
        assert f'data-kpi="{key}">{value}<' in md
    assert "200.00 held from payment" in md and "Review queue (2)" in nav(at)
    at = goto(at, "audit")
    audit_df = at.dataframe[-1].value
    assert len(audit_df) == 2 and set(audit_df["Decision"]) == {"Ready to pay", "Needs review"}
    at.multiselect[0].set_value(["Needs review"])
    at.run()
    assert list(at.dataframe[-1].value["Decision"]) == ["Needs review"]
    search = next(t for t in at.text_input if t.label == "Search invoice or supplier")
    search.input("no-such-invoice").run()
    assert at.dataframe[-1].value.empty
    next(t for t in at.text_input if t.label == "Search invoice or supplier").input("").run()
    assert list(at.dataframe[-1].value["Decision"]) == ["Needs review"]
    assert "Decision mix" in all_markdown(at)
    at = goto(at, "settings")
    next(b for b in at.button if b.label == "Clear demo history").click()
    at.run()
    at = goto(at, "overview")
    assert 'data-kpi="checked">0<' in all_markdown(at) and "Review queue (0)" in nav(at)


def test_rechecking_same_invoice_is_blocked_as_duplicate(configured):
    serve(configured, "case_01")
    at = check_case(AppTest.from_file(APP, default_timeout=60).run(), "case_01")
    at = check_case(at, "case_01")
    md = all_markdown(at)
    assert ">Payment blocked</span>" in md and "Invoice number already processed" in md


def test_document_text_is_escaped(configured):
    def evil(truth):
        truth["invoice"]["invoice_number"] = '<img src=x onerror="alert(1)">'
        truth["invoice"]["supplier_name"] = "<script>steal()</script>"
    serve(configured, "case_01", evil)
    at = check_case(AppTest.from_file(APP, default_timeout=60).run(), "case_01")
    md = all_markdown(at)
    assert "<script>" not in md and "<img src=x" not in md
    assert "&lt;script&gt;" in md


def test_rehearsal_button_checks_the_case_in_one_click(configured):
    serve(configured, "case_07")
    at = goto(AppTest.from_file(APP, default_timeout=60).run(), "check")
    assert "Overcharged by $200" in all_markdown(at)
    next(b for b in at.button if b.key == "scn-case_07").click()
    at.run()
    md = all_markdown(at)
    assert not at.exception and ">Needs review</span>" in md
    assert at.selectbox[0].value.startswith("Case 07")


def test_every_decision_shows_fields_rule_code_and_reason(configured):
    serve(configured, "case_07")
    at = check_case(AppTest.from_file(APP, default_timeout=60).run(), "case_07")
    md = all_markdown(at)
    assert '<code class="lp-code">PRICE_VARIANCE</code>' in md
    assert "Rule: Three-way match: unit price vs PO → needs review" in md
    assert "High confidence" in md
    truth = json.loads((SAMPLES / "case_07" / "truth.json").read_text())["invoice"]
    fields = next(d.value for d in at.dataframe if "Field" in d.value.columns)
    inv = dict(zip(fields["Field"], fields["Invoice"], strict=True))
    assert inv["Number"] == truth["invoice_number"] and inv["Total due"] == str(truth["total"])
    shown = inv["Pay-to bank account"]
    assert shown.startswith("****") and shown.endswith(truth["bank_iban"].replace(" ", "")[-4:])  # masked
    assert truth["bank_iban"].replace(" ", "") not in md


def test_low_confidence_is_handed_to_a_person(configured):
    serve(configured, "case_01")
    configured.agent_reply = lambda case: "I think it's fine?"
    at = check_case(AppTest.from_file(APP, default_timeout=60).run(), "case_01")
    md = all_markdown(at)
    assert ">Needs review</span>" in md and "Low confidence, handed to a human reviewer" in md
    assert "LOW_CONFIDENCE" in md


def test_every_finding_code_has_a_label_and_a_rule():
    import re

    # every quoted CODE_NAME in the files that raise findings
    src = "\n".join((ROOT / "src" / "ledgerpilot" / f).read_text() for f in ("reconcile.py", "fraud.py", "rules.py"))
    codes = set(re.findall(r'"([A-Z]+(?:_[A-Z]+)+)"', src))
    app = (ROOT / "app.py").read_text()
    labelled = [c for c in sorted(codes) if f'"{c}": "' in app]  # FINDING entry
    ruled = [c for c in sorted(codes) if f'"{c}"' in app.split("RULE = {", 1)[1].split("CHECKS_RUN", 1)[0]]
    assert len(codes) >= 25, sorted(codes)
    assert labelled == sorted(codes) and ruled == sorted(codes), (set(codes) - set(labelled), set(codes) - set(ruled))


def _record(configured, case, tmp_path):
    """Run a case live (against the fakes) and save it, the way the Save button does."""
    serve(configured, case)
    at = check_case(AppTest.from_file(APP, default_timeout=60).run(), case)
    next(b for b in at.button if b.label == "Save for demo mode").click()
    at.run()
    assert any("Saved" in s.value for s in at.success)
    return at


def test_demo_mode_replays_recordings_and_labels_them(configured, monkeypatch, tmp_path):
    monkeypatch.setenv("RECORDINGS_DIR", str(tmp_path / "rec"))
    fresh_caches()
    _record(configured, "case_15", tmp_path)
    assert (tmp_path / "rec" / "case_15.json").exists()

    at = AppTest.from_file(APP, default_timeout=60).run()
    at.sidebar.toggle[0].set_value(True)
    at.run()
    assert "Results are replays of recorded live runs" in all_markdown(at)
    at = goto(at, "check")
    calls_before = len(configured.calls)
    next(b for b in at.button if b.key == "scn-case_15").click()
    at.run()
    md = all_markdown(at)
    assert ">Payment blocked</span>" in md and "<b>Recorded run</b>" in md and "not a live call" in md
    assert any(e.label == "What ran, where (when recorded)" for e in at.expander)
    assert not [c for c in configured.calls[calls_before:] if "ask-file" in c["path"] or "completions" in c["path"]]
    assert "Review queue (1)" in nav(at)  # the replay didn't add a case to the live queue

    next(b for b in at.button if b.key == "scn-case_01").click()
    at.run()
    assert "No recording for case_01 yet" in " ".join(i.value for i in at.info)
    assert "<b>Recorded run</b>" not in all_markdown(at)


def test_demo_link_opens_a_recorded_case(configured, monkeypatch, tmp_path):
    monkeypatch.setenv("RECORDINGS_DIR", str(tmp_path / "rec"))
    fresh_caches()
    _record(configured, "case_07", tmp_path)
    at = AppTest.from_file(APP, default_timeout=60)
    at.query_params["demo"] = "1"
    at.query_params["case"] = "case_07"
    at.run()
    md = all_markdown(at)
    assert at.sidebar.toggle[0].value is True and "<b>Recorded run</b>" in md and ">Needs review</span>" in md
    at.run()  # later reruns don't re-trigger the URL case
    assert not at.exception


def test_failed_live_check_offers_the_recording(configured, monkeypatch, tmp_path):
    monkeypatch.setenv("RECORDINGS_DIR", str(tmp_path / "rec"))
    fresh_caches()
    _record(configured, "case_07", tmp_path)
    configured.extract_data = lambda eid, fn: 503  # Evolus goes down mid-demo
    monkeypatch.setenv("EVOLUS_TIMEOUT", "5")
    at = check_case(AppTest.from_file(APP, default_timeout=120).run(), "case_07")
    assert ">Needs a person</span>" in all_markdown(at)
    next(b for b in at.button if b.label == "Show the recorded run of this case instead").click()
    at.run()
    md = all_markdown(at)
    assert ">Needs review</span>" in md and "<b>Recorded run</b>" in md and not at.exception


def test_results_tab_without_measurements(configured, monkeypatch):
    at = goto(AppTest.from_file(APP, default_timeout=60).run(), "results")
    if not (ROOT / "docs" / "evaluation.md").exists():
        assert "No measured results yet" in all_markdown(at)


def test_public_site_limits_live_checks_and_keeps_history_private(configured, monkeypatch):
    monkeypatch.setenv("PUBLIC_SITE", "1")
    monkeypatch.setenv("LIVE_CHECKS_PER_VISITOR", "1")
    fresh_caches()
    serve(configured, "case_01")
    at = check_case(AppTest.from_file(APP, default_timeout=60).run(), "case_01")
    assert ">Ready to pay</span>" in all_markdown(at)
    assert any("Public demo" in c.value and "0 of 1 left" in c.value for c in at.caption)
    # the second live check from the same visitor is refused without calling Evolus
    calls_before = len(configured.calls)
    serve(configured, "case_07")
    at = check_case(at, "case_07")
    assert any("used your 1 live checks" in i.value for i in at.info)
    assert not [c for c in configured.calls[calls_before:] if "ask-file" in c["path"]]
    # a new visitor has a private history: the same sample invoice is not a duplicate for them
    serve(configured, "case_01")
    other = check_case(AppTest.from_file(APP, default_timeout=60).run(), "case_01")
    assert ">Ready to pay</span>" in all_markdown(other) and "Invoice number already processed" not in all_markdown(other)


def test_ask_the_agent_chats_and_masks_accounts(configured):
    configured.agent_reply = lambda case: "Hi! I'm Detective Clerk. Your vendor account GB82ACME00001234567801 is on file."
    at = goto(AppTest.from_file(APP, default_timeout=60).run(), "chat")
    next(b for b in at.button if b.key == "starter-0").click()
    at.run()
    msgs = [m for m in at.chat_message]
    assert [m.name for m in msgs] == ["user", "assistant"] and not at.exception
    text = " ".join(md.value for m in msgs for md in m.markdown)
    assert "Detective Clerk" in text and "GB82ACME00001234567801" not in text and "7801" in text
    at.chat_input[0].set_value("What is a three-way match?").run()
    assert len(at.chat_message) == 4

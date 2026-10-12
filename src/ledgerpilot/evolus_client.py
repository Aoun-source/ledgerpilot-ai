"""Evolus REST API client.

Endpoints follow the Evolus developer docs (https://evolus.ai/en/developers):
  REST base  https://api.evolus.ai/api/v1   headers X-ApiKey + X-Application-Id
  extractor  POST /agents/{agentId}/json/{extractorId}/ask-file   (multipart "file")
  workflow   POST /workflows/{id}/execute  ->  202 {executionId}
             GET  /workflows/{id}/executions/{executionId}
  AI Tools   POST /ai-tools/{tool}/run      JSON {text, secondaryText, options}
  libraries  POST /memories/{libraryId}/documents?language=en  (multipart "file")
Check the interactive API reference inside your workspace if a field differs.
"""
from __future__ import annotations

import json
import mimetypes
import time
from dataclasses import dataclass
from typing import Any, Optional

import requests

from .config import Settings


class EvolusError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, body: str | None = None):
        super().__init__(message)
        self.status, self.body = status, body


@dataclass
class ExtractionResult:
    data: dict[str, Any]
    execution_id: Optional[str]
    audit_id: Optional[str]


class EvolusClient:
    RETRY_STATUSES = {429, 500, 502, 503, 504}

    def __init__(self, settings: Settings, timeout: float = 120.0, max_retries: int = 3, backoff: float = 1.0):
        self.s = settings
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff = backoff
        self.http = requests.Session()
        self.http.headers.update({"X-ApiKey": settings.evolus_api_key or "",
                                  "X-Application-Id": settings.evolus_app_id or ""})

    # ------------------------------------------------------------------ core
    def _request(self, method: str, path: str, retry_statuses: set[int] | None = None,
                 retry_network: bool = True, **kwargs) -> requests.Response:
        retry_on = self.RETRY_STATUSES if retry_statuses is None else retry_statuses
        url = f"{self.s.evolus_api_base.rstrip('/')}/{path.lstrip('/')}"
        resp: requests.Response | None = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = self.http.request(method, url, timeout=self.timeout, **kwargs)
            except (requests.ConnectionError, requests.Timeout) as exc:
                if retry_network and attempt < self.max_retries:
                    time.sleep(self.backoff * 2 ** attempt)
                    continue
                raise EvolusError(f"Could not reach Evolus ({type(exc).__name__}). Check the network and retry.") from exc
            except requests.RequestException as exc:
                raise EvolusError(f"Evolus request failed: {type(exc).__name__}") from exc
            if resp.status_code in retry_on and attempt < self.max_retries:
                # 60 requests/minute per workspace: back off and retry.
                time.sleep(min(_retry_after(resp, self.backoff * 2 ** attempt), 20))
                continue
            break
        assert resp is not None
        if resp.status_code in (401, 403):
            raise EvolusError("Evolus rejected the API key or application ID (check EVOLUS_API_KEY / EVOLUS_APP_ID).",
                              resp.status_code, resp.text[:500])
        if resp.status_code == 402:
            raise EvolusError("Evolus platform credits are used up (402).", 402, resp.text)
        if resp.status_code == 409:
            raise EvolusError("Workflow is switched off in Evolus (409). Turn it on and retry.", 409, resp.text)
        if resp.status_code >= 400:
            raise EvolusError(f"Evolus {method} {path} failed: {resp.status_code}", resp.status_code, resp.text[:500])
        return resp

    # ------------------------------------------------------------ extractors
    def extract(self, extractor_id: str, filename: str, content: bytes) -> ExtractionResult:
        agent = self.s.evolus_extractor_agent_id
        resp = self._request(
            "POST", f"agents/{agent}/json/{extractor_id}/ask-file",
            params={"useWebhook": "false"},
            files={"file": (filename, content, _mime(filename))},
        )
        return ExtractionResult(data=_json_body(resp),
                                execution_id=resp.headers.get("X-AskFile-Execution-Id"),
                                audit_id=resp.headers.get("X-AskFile-Audit-Id"))

    # ------------------------------------------------------------- workflows
    def start_workflow(self, input_text: str, parameters: dict[str, Any] | None = None,
                       files: list[tuple[str, bytes]] | None = None) -> str:
        # Evolus expects multipart/form-data even without files: send fields as multipart parts.
        parts: list[tuple[str, tuple]] = [("input", (None, input_text))]
        if parameters:
            parts.append(("parameters", (None, json.dumps(parameters))))  # flat JSON; never put secrets here
        parts += [("file", (name, blob, _mime(name))) for name, blob in (files or [])]
        # Not idempotent: only retry 429 (rejected before processing), never 5xx or dropped connections.
        resp = self._request("POST", f"workflows/{self.s.workflow_id}/execute", retry_statuses={429},
                             retry_network=False, files=parts)
        body = _json_body(resp)
        return body.get("executionId") or resp.headers.get("X-Workflow-Execution-Id")

    def get_execution(self, execution_id: str) -> dict[str, Any]:
        return _json_body(self._request("GET", f"workflows/{self.s.workflow_id}/executions/{execution_id}"))

    def wait_for_execution(self, execution_id: str, timeout: float = 90, poll: float = 2) -> dict[str, Any]:
        deadline = time.time() + timeout
        while True:
            run = self.get_execution(execution_id)
            if str(run.get("status")) in {"Completed", "Failed"} or time.time() > deadline:
                return run
            time.sleep(poll)

    # -------------------------------------------------------------- AI Tools
    def run_tool(self, tool: str, text: str, secondary_text: str | None = None,
                 options: dict[str, Any] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"text": text, "options": options or {}}
        if secondary_text:
            payload["secondaryText"] = secondary_text
        return _json_body(self._request("POST", f"ai-tools/{tool}/run", json=payload))

    def draft_supplier_email(self, facts: str) -> str:
        out = self.run_tool("email", facts, options={"mode": "write", "tone": "formal"})
        return str(out.get("output", "")).strip()

    # ------------------------------------------------------------- libraries
    def upload_library_document(self, filename: str, content: bytes, language: str = "en") -> dict[str, Any]:
        return _json_body(self._request("POST", f"memories/{self.s.library_id}/documents",
                                        params={"language": language},
                                        files={"file": (filename, content)}))

    def list_library_documents(self) -> Any:
        return _json_body(self._request("GET", f"memories/{self.s.library_id}/documents"))


def _mime(filename: str) -> str:
    return mimetypes.guess_type(filename)[0] or "application/octet-stream"


def _retry_after(resp: requests.Response, default: float) -> float:
    try:
        return max(float(resp.headers.get("Retry-After", default)), 0.0)
    except (TypeError, ValueError):  # HTTP-date form or garbage
        return default


def _json_body(resp: requests.Response) -> Any:
    if not resp.content:
        return {}
    try:
        return resp.json()
    except ValueError as exc:
        raise EvolusError("Evolus returned a non-JSON response", resp.status_code, resp.text[:500]) from exc

"""A local HTTP server that mimics the Evolus REST API, the Evolus OpenAI-compatible
agent endpoint and a vLLM server, for tests only.

It lets the real clients (requests + openai SDK) run end to end: real URLs,
headers, multipart uploads, status codes, retries and timeouts.
"""
from __future__ import annotations

import json
import re
import threading
from collections import defaultdict
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class FakeServices:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail: dict[str, list[int]] = defaultdict(list)  # path regex -> status codes to return first
        self.extract_data: Callable[[str, str], Any] = lambda extractor_id, filename: {"ok": True}
        self.agent_reply: Callable[[dict], str] = lambda case: json.dumps({"route": case.get("rule_route", "hold_for_review"),
                                                                          "explanation": "Checked against the vendor master.",
                                                                          "evidence": ["Vendor master: V001"],
                                                                          "supplier_question": "Please confirm."})
        self.execution_status = ["Running", "Completed"]
        handler = self._handler()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def __enter__(self) -> FakeServices:
        self.thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.server.shutdown()
        self.server.server_close()

    def count(self, pattern: str) -> int:
        return sum(1 for c in self.calls if re.search(pattern, c["path"]))

    # ------------------------------------------------------------------
    def _handler(self):
        svc = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # silence
                pass

            def _send(self, status: int, body: Any = None, headers: dict[str, str] | None = None, raw: bytes | None = None):
                data = raw if raw is not None else (json.dumps(body).encode() if body is not None else b"")
                self.send_response(status)
                self.send_header("Content-Type", "application/json" if raw is None else "text/plain")
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _handle(self, method: str):
                length = int(self.headers.get("Content-Length", 0) or 0)
                body = self.rfile.read(length) if length else b""
                call = {"method": method, "path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body}
                svc.calls.append(call)
                for pattern, codes in svc.fail.items():
                    if codes and re.search(pattern, self.path):
                        status = codes.pop(0)
                        if status == 0:  # drop the connection
                            self.close_connection = True
                            return
                        return self._send(status, {"error": f"injected {status}"}, {"Retry-After": "0"})
                path = self.path.split("?")[0]

                if m := re.fullmatch(r"/api/v1/agents/([^/]+)/json/([^/]+)/ask-file", path):
                    fname = re.search(rb'filename="([^"]+)"', body)
                    ctype = re.search(rb"Content-Type: ([^\r\n]+)", body.split(b"\r\n\r\n", 1)[0] + b"\r\n" + body)
                    call["filename"] = fname.group(1).decode() if fname else None
                    parts = re.findall(rb'filename="[^"]+"\r\nContent-Type: ([^\r\n]+)', body)
                    call["part_content_type"] = parts[0].decode() if parts else (ctype.group(1).decode() if ctype else None)
                    data = svc.extract_data(m.group(2), call["filename"])
                    if isinstance(data, int):
                        return self._send(data, {"error": "cannot read"})
                    if data == "NOT_JSON":
                        return self._send(200, raw=b"<html>oops</html>")
                    return self._send(200, data, {"X-AskFile-Execution-Id": f"ex-{m.group(2)}", "X-AskFile-Audit-Id": "au-1"})
                if m := re.fullmatch(r"/api/v1/workflows/([^/]+)/execute", path):
                    return self._send(202, {"jobId": "j1", "executionId": "wf-exec-1", "enqueuedAt": "now", "traceId": "t"},
                                      {"X-Workflow-Execution-Id": "wf-exec-1"})
                if re.fullmatch(r"/api/v1/workflows/[^/]+/executions/[^/]+", path):
                    status = svc.execution_status.pop(0) if len(svc.execution_status) > 1 else svc.execution_status[0]
                    return self._send(200, {"status": status})
                if m := re.fullmatch(r"/api/v1/ai-tools/([^/]+)/run", path):
                    payload = json.loads(body or b"{}")
                    call["json"] = payload
                    return self._send(200, {"tool": m.group(1), "output": "Dear supplier,\n\nPlease review.", "creditsConsumed": 3, "truncated": False})
                if m := re.fullmatch(r"/api/v1/memories/([^/]+)/documents", path):
                    if method == "GET":
                        return self._send(200, [{"title": "vendor_master.pdf", "status": "Indexed"}])
                    return self._send(201, {"id": "doc-1", "status": "Indexing"})
                if path == "/v1/models":
                    return self._send(200, {"object": "list", "data": [{"id": "app:agent", "object": "model", "created": 0, "owned_by": "x"},
                                                                       {"id": "ledgerpilot-model", "object": "model", "created": 0, "owned_by": "vllm"}]})
                if path == "/v1/chat/completions":
                    payload = json.loads(body)
                    call["json"] = payload
                    text = payload["messages"][-1]["content"]
                    case = json.loads(text.split("CASE:", 1)[1]) if "CASE:" in text else {}
                    content = svc.agent_reply(case)
                    return self._send(200, {
                        "id": "c1", "object": "chat.completion", "created": 0, "model": payload["model"],
                        "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}],
                        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}},
                        {"X-Conversation-Id": "conv-42"})
                return self._send(404, {"error": "not found", "path": path})

            def do_GET(self):
                self._handle("GET")

            def do_POST(self):
                self._handle("POST")

        return Handler

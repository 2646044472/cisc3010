from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs" / "llm"
TERMINAL = {"completed", "cancelled", "failed", "rejected"}
WORDS = "A distributed service routes requests across workers while scheduling tokens and managing cached context to reduce waiting time under changing load .".split()


def now():
    return time.perf_counter()


def safe_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value):
        raise ValueError("invalid request/run identifier")
    return value


def token_for(prompt, index):
    offset = int(hashlib.sha256(prompt.encode()).hexdigest()[:8], 16)
    return WORDS[(offset + index) % len(WORDS)] + " "


def simulator_input(prompt, messages=None):
    return json.dumps(messages, ensure_ascii=False, sort_keys=True) if messages else prompt


def json_http(url, data=None, timeout=5):
    payload = None if data is None else json.dumps(data).encode()
    req = urllib.request.Request(url, payload, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


class Trace:
    def __init__(self, name):
        self.name = name
        self.lock = threading.Lock()

    def write(self, run_id, event):
        if not run_id:
            return
        folder = RUNS / safe_id(run_id)
        folder.mkdir(parents=True, exist_ok=True)
        with self.lock, (folder / (self.name + ".jsonl")).open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def read_events(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def validate_request(data):
    if not isinstance(data, dict):
        raise ValueError("request must be an object")
    prompt = data.get("prompt", "")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 32000:
        raise ValueError("prompt must contain 1–32000 characters")
    maximum = data.get("max_tokens", 48)
    if isinstance(maximum, bool) or not isinstance(maximum, int) or not 1 <= maximum <= 512:
        raise ValueError("max_tokens must be an integer from 1 to 512")
    rid = safe_id(data["request_id"])
    run = data.get("run_id")
    if run:
        safe_id(run)
    messages = data.get("messages")
    if messages is not None:
        if not isinstance(messages, list) or not 1 <= len(messages) <= 32:
            raise ValueError("messages must contain 1–32 turns")
        if any(not isinstance(m, dict) or m.get("role") not in {"system", "user", "assistant"}
               or not isinstance(m.get("content"), str) for m in messages):
            raise ValueError("invalid conversation message")
        if sum(len(m["content"]) for m in messages) > 32000 or messages[-1]["role"] != "user":
            raise ValueError("conversation must end with a user message and fit the context limit")
        if messages[-1]["content"] != prompt:
            raise ValueError("prompt must match the final user message")
        messages = [{"role": m["role"], "content": m["content"]} for m in messages]
    tenant = data.get("tenant", "demo")
    if tenant not in {"demo", "client-a", "client-b", "benchmark"}:
        raise ValueError("unknown demo client")
    return {"prompt": prompt, "max_tokens": maximum, "request_id": rid, "run_id": run, "messages": messages, "tenant": tenant}


class JsonHandlerMixin:
    def log_message(self, *args):
        pass

    def body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length < 1 or length > 100000:
            raise ValueError("invalid body length")
        return json.loads(self.rfile.read(length))

    def reply(self, value, status=200, headers=None):
        body = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for name, value in (headers or {}).items():
            self.send_header(name, str(value))
        self.end_headers()
        self.wfile.write(body)

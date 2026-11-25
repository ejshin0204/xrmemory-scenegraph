"""Claude client and one logged Messages API call.

Credentials: ANTHROPIC_API_KEY in the environment wins (the SDK default). Otherwise the key is
read at runtime from `anthropic.api_key_file` in config.yaml. The key is never written anywhere.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

import anthropic

log = logging.getLogger("msg_eval")

FALLBACK_BETA = "server-side-fallback-2026-07-01"


def make_client(cfg: dict[str, Any]) -> anthropic.Anthropic:
    a = cfg["anthropic"]
    kw = {"timeout": float(a.get("timeout_s", 300)), "max_retries": int(a.get("max_retries", 4))}
    if os.environ.get("ANTHROPIC_API_KEY"):
        return anthropic.Anthropic(**kw)
    key_file = a.get("api_key_file")
    if key_file:
        p = Path(key_file).expanduser()
        if not p.exists():
            raise FileNotFoundError(f"api_key_file not found: {p}")
        return anthropic.Anthropic(api_key=p.read_text(encoding="utf-8").strip(), **kw)
    return anthropic.Anthropic(**kw)  # falls back to `ant auth login` profiles


def block_to_log(b: Any) -> dict[str, Any]:
    """Serialize a response content block for the trace (thinking text is the summary, if any)."""
    t = b.type
    if t == "text":
        return {"type": t, "text": b.text}
    if t == "thinking":
        return {"type": t, "thinking": getattr(b, "thinking", "")}
    if t == "tool_use":
        return {"type": t, "id": b.id, "name": b.name, "input": b.input}
    return {"type": t}


def usage_to_log(u: Any) -> dict[str, Any]:
    keys = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
    return {k: getattr(u, k, None) for k in keys}


def call(client: anthropic.Anthropic, cfg: dict[str, Any], *, system: str, messages: list[dict],
         tools: list[dict] | None = None, output_format: dict | None = None,
         trace: list[dict] | None = None, tag: str = "") -> Any:
    """One Messages API request. Appends a trace entry (blocks, stop reason, usage, latency)."""
    a = cfg["anthropic"]
    output_config: dict[str, Any] = {"effort": a.get("effort", "medium")}
    if output_format:
        output_config["format"] = output_format
    kwargs: dict[str, Any] = dict(
        model=a.get("model", "claude-opus-5-5"),
        max_tokens=int(a.get("max_tokens", 16000)),
        # Breakpoint on the system block: system (+ tools before it) is identical across questions,
        # so later questions read it from cache. The top-level breakpoint caches the growing
        # conversation inside one navigator loop.
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=messages,
        thinking={"type": "adaptive", "display": a.get("thinking_display", "summarized")},
        output_config=output_config,
        cache_control={"type": "ephemeral"},
    )
    if tools:
        kwargs["tools"] = tools
    t0 = time.time()
    if a.get("fallbacks", True):
        resp = client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **kwargs)
    else:
        resp = client.messages.create(**kwargs)
    dt = time.time() - t0
    if trace is not None:
        trace.append({"tag": tag, "model": resp.model, "stop_reason": resp.stop_reason,
                      "seconds": round(dt, 2), "usage": usage_to_log(resp.usage),
                      "request_id": getattr(resp, "_request_id", None),
                      "content": [block_to_log(b) for b in resp.content]})
    log.debug("%s %s stop=%s %.1fs", tag, resp.model, resp.stop_reason, dt)
    if resp.stop_reason == "refusal":
        details = getattr(resp, "stop_details", None)
        raise RuntimeError(f"refusal ({getattr(details, 'category', None)})")
    return resp


def final_text(resp: Any) -> str:
    return next((b.text for b in resp.content if b.type == "text"), "")

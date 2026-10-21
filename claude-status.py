#!/usr/bin/env python3
"""Append verified Claude turn metadata to cc-connect stream-json replies."""

import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid


def find_claude():
    configured = os.environ.get("CLAUDE_BIN")
    if configured:
        return configured
    found = shutil.which("claude")
    if found:
        return found
    fallback = Path.home() / ".local/bin/claude"
    return str(fallback)


def find_codexbar():
    configured = os.environ.get("CODEXBAR_BIN")
    if configured:
        return configured
    found = shutil.which("CodexBarCLI")
    if found:
        return found
    macos = Path("/Applications/CodexBar.app/Contents/Helpers/CodexBarCLI")
    return str(macos) if macos.exists() else ""


CLAUDE = find_claude()
CODEXBAR = find_codexbar()
STATE = Path(os.environ.get("CC_CONNECT_STATUS_DIR", Path.home() / ".cc-connect/status"))


def save(name, data):
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = STATE / name
    temp = STATE / f"{name}.{os.getpid()}.tmp"
    with temp.open("w", encoding="utf-8") as file:
        os.chmod(temp, 0o600)
        json.dump(data, file, ensure_ascii=False)
    temp.replace(target)


def read_quota():
    """Read percentages through CodexBar; never read or store account cookies."""
    cache = STATE / "claude-quota.json"
    try:
        data = json.loads(cache.read_text(encoding="utf-8"))
        if 0 <= time.time() - data["fetched_at"] < 120:
            return data
    except (OSError, ValueError, KeyError, TypeError):
        pass
    if not CODEXBAR:
        return None
    try:
        proc = subprocess.run(
            [CODEXBAR, "usage", "--provider", "claude", "--format", "json", "--no-color"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        if proc.returncode:
            return None
        rows = json.loads(proc.stdout)
        row = next(item for item in rows if item.get("provider") == "claude" and item.get("usage"))
        result = {"fetched_at": time.time(), "source": "CodexBar"}
        for field, label in (("primary", "five_hour"), ("secondary", "weekly")):
            window = row["usage"].get(field)
            used = window.get("usedPercent") if isinstance(window, dict) else None
            if isinstance(used, (int, float)) and math.isfinite(used):
                result[label] = max(0, min(100, 100 - used))
        if not any(key in result for key in ("five_hour", "weekly")):
            return None
        save("claude-quota.json", result)
        return result
    except (OSError, ValueError, StopIteration, KeyError, TypeError, subprocess.TimeoutExpired):
        return None


def arg_value(args, name):
    for index, arg in enumerate(args):
        if arg == name and index + 1 < len(args):
            return args[index + 1]
        if arg.startswith(name + "="):
            return arg.split("=", 1)[1]
    return ""


def configured_effort(args):
    effort = arg_value(args, "--effort") or os.environ.get("CLAUDE_CODE_EFFORT_LEVEL", "")
    if effort:
        return effort
    paths = (
        Path.cwd() / ".claude/settings.local.json",
        Path.cwd() / ".claude/settings.json",
        Path.home() / ".claude/settings.json",
    )
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            effort = data.get("effortLevel") or data.get("env", {}).get("CLAUDE_CODE_EFFORT_LEVEL")
            if effort:
                return str(effort)
        except (OSError, ValueError, AttributeError):
            pass
    return "default"


def friendly_model(model):
    if model.startswith("claude-"):
        parts = model.removeprefix("claude-").split("-")
        family = parts.pop(0).capitalize()
        return "Claude " + family + " " + ".".join(parts)
    return model or "未读取"


def actual_effort(session_id, message_id):
    """Find the actual effort for this exact assistant message."""
    if not session_id or not message_id or any(char not in "0123456789abcdef-" for char in session_id):
        return ""
    for path in (Path.home() / ".claude/projects").glob(f"*/{session_id}.jsonl"):
        try:
            with path.open("rb") as file:
                file.seek(0, 2)
                file.seek(max(0, file.tell() - 262144))
                lines = file.read().splitlines()
            for line in reversed(lines):
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if event.get("type") == "assistant" and event.get("message", {}).get("id") == message_id:
                    return event.get("effort", "")
        except OSError:
            continue
    return ""


def status_footer(model, effort, last_usage, result, quota):
    model_usage = result.get("modelUsage", {})
    info = model_usage.get(model, {})
    window = info.get("contextWindow") if isinstance(info, dict) else None
    used = sum(last_usage.get(key, 0) or 0 for key in (
        "input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"
    ))
    context = (
        f"{min(100, used / window * 100):.1f}%"
        if used and isinstance(window, (int, float)) and window > 0
        else "未读取"
    )
    duration = result.get("duration_ms")
    elapsed = f"{duration / 1000:.1f}秒" if isinstance(duration, (int, float)) else "未读取"
    strength = effort.upper() if effort in {"low", "medium", "high", "xhigh", "max"} else "UNKNOWN"
    allowances = []
    if quota:
        for key, label in (("five_hour", "五小时"), ("weekly", "本周")):
            if key in quota:
                allowances.append(f"{label} {quota[key]:.0f}%")
    remaining = " · ".join(allowances) or "暂不可读"
    return (
        f"模型：{friendly_model(model)} · 推理：{strength} · 上下文：{context}\n"
        f"耗时：{elapsed} · 额度剩余：{remaining}"
    )


def adapt(event, state, quota_fn=read_quota):
    kind = event.get("type")
    if kind == "system" and event.get("subtype") == "init":
        state["model"] = event.get("model") or state["model"]
        state["effort"] = event.get("effort") or event.get("reasoning_effort") or state["effort"]
    if kind == "assistant":
        message = event.get("message", {})
        content = []
        for block in message.get("content", []):
            text = block.get("text") if block.get("type") == "text" else None
            if text:
                if state["has_text"]:
                    leading = len(text) - len(text.lstrip("\n"))
                    missing = max(0, 2 - state.get("trailing_newlines", 0) - leading)
                    if missing:
                        block = dict(block, text="\n" * missing + text)
                state["trailing_newlines"] = len(text) - len(text.rstrip("\n"))
                state["has_text"] = True
            content.append(block)
        event = dict(event, message=dict(message, content=content))
        message = event["message"]
        state["model"] = message.get("model") or state["model"]
        state["message_id"] = message.get("id") or state.get("message_id", "")
        state["effort"] = event.get("effort") or message.get("effort") or state["effort"]
        if message.get("usage"):
            state["usage"] = message["usage"]
        state["has_text"] |= any(
            block.get("type") == "text" and block.get("text") for block in message.get("content", [])
        )
    if kind != "result" or event.get("subtype") != "success" or event.get("is_error"):
        return [event]
    text = event.get("result", "")
    if text.strip().upper().strip("*") == "NO_REPLY" or text.rstrip().endswith("NO_REPLY"):
        state["has_text"] = False
        return [event]
    effort = actual_effort(event.get("session_id", ""), state.get("message_id", "")) or state["effort"]
    footer = status_footer(state["model"], effort, state["usage"], event, quota_fn())
    suffix = "\n\n" + footer
    output = []
    if state["has_text"]:
        output.append({
            "type": "assistant",
            "uuid": str(uuid.uuid4()),
            "session_id": event.get("session_id", ""),
            "message": {"role": "assistant", "content": [{"type": "text", "text": suffix}]},
        })
    event = dict(event, result=text + suffix)
    output.append(event)
    try:
        save("last-status.json", {"updated_at": time.time(), "footer": footer})
    except OSError:
        pass
    state["has_text"] = False
    state["trailing_newlines"] = 0
    state["usage"] = {}
    return output


def main():
    args = sys.argv[1:]
    if arg_value(args, "--output-format") != "stream-json":
        os.execv(CLAUDE, [CLAUDE, *args])
    state = {"model": "", "effort": configured_effort(args), "usage": {}, "has_text": False}
    child = subprocess.Popen([CLAUDE, *args], stdin=sys.stdin, stdout=subprocess.PIPE)
    try:
        for line in child.stdout:
            try:
                event = json.loads(line)
                events = adapt(event, state)
            except (ValueError, TypeError, AttributeError):
                sys.stdout.buffer.write(line)
                sys.stdout.buffer.flush()
                continue
            for output in events:
                print(json.dumps(output, ensure_ascii=False), flush=True)
    except BrokenPipeError:
        child.terminate()
    return child.wait()


if __name__ == "__main__":
    sys.exit(main())

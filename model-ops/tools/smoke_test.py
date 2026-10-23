#!/usr/bin/env python3
"""Post-deploy smoke test for one model behind an OpenAI-compatible endpoint (Gitee AI or a self-hosted vLLM/SGLang).

Checks are chosen by the model's kind in models.json (or --kind):
  llm   : listed in /models, basic answer, streaming (TTFT, tok/s), json_schema output, tool calling
  vlm   : llm checks + reads digits from a generated PNG
  omni  : vlm checks + transcribes a generated Chinese WAV + asks for audio output
  t2i   : /images/generations returns a decodable image of the requested size (saved for a human look)
  t2av  : skipped until the Gitee AI video endpoint is known (see models/minimax-h3.md)

Every check is "pass / FAIL / skip" with the evidence kept, because the Gitee AI failures seen so far are
silent: a parameter is accepted and ignored (see reference: guided_json on GLM-5.3), or the page name is
not the API id. Results go to results/<stamp>_<model>.json and one row per check in results/LOG.md.

  python3 tools/smoke_test.py qwen3.8-27b
  python3 tools/smoke_test.py glm-5.3 --base-url http://10.0.0.5:8000/v1 --model-id GLM-5.3 --api-key EMPTY
Key: --api-key, else $GITEE_AI_API_KEY or $MOARK_API_KEY (the gateway's moark provider key), else the gitee-ai
provider key in dailyworkinmetax/comic-skill/opencode.json, looked up next to this folder or next to its repo.
Stdlib only (macOS `say` + `afconvert` for the omni audio clip).
"""
import argparse
import base64
import datetime as dt
import json
import os
import pathlib
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
OPENCODE_PATHS = tuple(
    base / "dailyworkinmetax" / "comic-skill" / "opencode.json" for base in (ROOT.parent, ROOT.parent.parent)
)
RESULTS = ROOT / "results"


# ---------- HTTP ----------

class Client:
    def __init__(self, base, key, timeout):
        self.base, self.key, self.timeout = base.rstrip("/"), key, timeout

    def _req(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method, headers={
            "Authorization": f"Bearer {self.key}", "Content-Type": "application/json"})
        return urllib.request.urlopen(req, timeout=self.timeout)

    def get(self, path):
        with self._req("GET", path) as r:
            return json.load(r)

    def post(self, path, body):
        t0 = time.time()
        try:
            with self._req("POST", path, body) as r:
                return json.load(r), time.time() - t0
        except urllib.error.HTTPError as e:
            return {"_http_error": e.code, "_body": e.read().decode("utf-8", "replace")[:800]}, time.time() - t0

    def stream(self, path, body):
        """Yield (t_since_start, chunk_dict) for an SSE response."""
        t0 = time.time()
        try:
            r = self._req("POST", path, body)
        except urllib.error.HTTPError as e:
            yield time.time() - t0, {"_http_error": e.code, "_body": e.read().decode("utf-8", "replace")[:800]}
            return
        with r:
            for raw in r:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    yield time.time() - t0, json.loads(payload)
                except json.JSONDecodeError:
                    continue


# ---------- test inputs made with the stdlib ----------

FONT = {  # 5x7 bitmap digits
    "0": ["01110", "10001", "10011", "10101", "11001", "10001", "01110"],
    "1": ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
    "2": ["01110", "10001", "00001", "00010", "00100", "01000", "11111"],
    "3": ["11110", "00001", "00001", "01110", "00001", "00001", "11110"],
    "4": ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],
    "5": ["11111", "10000", "11110", "00001", "00001", "10001", "01110"],
    "6": ["00110", "01000", "10000", "11110", "10001", "10001", "01110"],
    "7": ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
    "8": ["01110", "10001", "10001", "01110", "10001", "10001", "01110"],
    "9": ["01110", "10001", "10001", "01111", "00001", "00010", "01100"],
}


def digits_png(text="4729", scale=24, pad=2):
    cols = len(text) * 6 - 1 + 2 * pad
    rows = 7 + 2 * pad
    grid = [[0] * cols for _ in range(rows)]
    for i, ch in enumerate(text):
        for y, row in enumerate(FONT[ch]):
            for x, bit in enumerate(row):
                if bit == "1":
                    grid[y + pad][pad + i * 6 + x] = 1
    w, h = cols * scale, rows * scale
    raw = b""
    for y in range(h):
        line = bytes(0 if grid[y // scale][x // scale] else 255 for x in range(w))
        raw += b"\x00" + line
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    return png


def speech_wav(text):
    with tempfile.TemporaryDirectory() as d:
        aiff, wav = os.path.join(d, "a.aiff"), os.path.join(d, "a.wav")
        subprocess.run(["say", "-v", "Tingting", text, "-o", aiff], check=True)
        subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", aiff, wav], check=True)
        return open(wav, "rb").read()


def image_size(blob):
    if blob[:8] == b"\x89PNG\r\n\x1a\n":
        return "png", struct.unpack(">II", blob[16:24])
    if blob[:2] == b"\xff\xd8":
        i = 2
        while i < len(blob):
            marker, seg = blob[i + 1], struct.unpack(">H", blob[i + 2:i + 4])[0]
            if marker in (0xC0, 0xC1, 0xC2):
                h, w = struct.unpack(">HH", blob[i + 5:i + 9])
                return "jpeg", (w, h)
            i += 2 + seg
    if blob[:4] == b"RIFF" and blob[8:12] == b"WEBP":
        return "webp", None
    return "unknown", None


# ---------- checks ----------

def msg_of(resp):
    try:
        return resp["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        return {}


def short(x, n=300):
    s = x if isinstance(x, str) else json.dumps(x, ensure_ascii=False)
    return s[:n]


def check_listed(c, mid):
    ids = [m["id"] for m in c.get("/models").get("data", [])]
    if mid in ids:
        return "pass", "listed"
    near = [i for i in ids if i.lower() == mid.lower()]
    return "FAIL", f"not in /models; case-insensitive match: {near}" if near else "not in /models"


def check_basic(c, mid, max_tokens):
    r, t = c.post("/chat/completions", {"model": mid, "max_tokens": max_tokens, "temperature": 0,
               "messages": [{"role": "user", "content": "17+25 等于几？只回答一个阿拉伯数字。"}]})
    if "_http_error" in r:
        return "FAIL", f"HTTP {r['_http_error']}: {r['_body']}", t
    m = msg_of(r)
    content, reasoning = m.get("content") or "", m.get("reasoning_content") or ""
    u = r.get("usage", {})
    ev = f"content={short(content, 80)!r} reasoning_chars={len(reasoning)} usage={u} finish={r['choices'][0].get('finish_reason')}"
    if "42" in content:
        return "pass", ev, t
    if not content and reasoning:
        return "FAIL", "empty content, answer stuck in reasoning (max_tokens too small or parser issue): " + ev, t
    return "FAIL", ev, t


def check_stream(c, mid, max_tokens):
    body = {"model": mid, "max_tokens": max_tokens, "temperature": 0, "stream": True,
            "stream_options": {"include_usage": True},
            "messages": [{"role": "user", "content": "用三句话介绍上海。"}]}
    ttft, last, n, usage, text, err = None, None, 0, None, "", None
    for t, ch in c.stream("/chat/completions", body):
        if "_http_error" in ch:
            err = f"HTTP {ch['_http_error']}: {ch['_body']}"
            break
        usage = ch.get("usage") or usage
        for choice in ch.get("choices", []):
            d = choice.get("delta", {})
            piece = (d.get("content") or "") + (d.get("reasoning_content") or "")
            if piece:
                ttft = t if ttft is None else ttft
                last, n = t, n + 1
                text += d.get("content") or ""
    if err:
        return "FAIL", err, None
    if ttft is None:
        return "FAIL", "stream produced no content chunks", None
    toks = (usage or {}).get("completion_tokens") or n
    rate = toks / (last - ttft) if last and last > ttft else None
    ev = f"TTFT {ttft:.2f}s, total {last:.2f}s, {toks} tok, {rate:.1f} tok/s" if rate else f"TTFT {ttft:.2f}s"
    ev += f"; usage_in_stream={'yes' if usage else 'no'}; answer={short(text, 60)!r}"
    return "pass", ev, last


def check_json_schema(c, mid, max_tokens):
    schema = {"type": "object", "properties": {"city": {"type": "string"}, "country": {"type": "string"},
              "population_million": {"type": "number"}}, "required": ["city", "country", "population_million"],
              "additionalProperties": False}
    r, t = c.post("/chat/completions", {"model": mid, "max_tokens": max_tokens, "temperature": 0,
               "response_format": {"type": "json_schema", "json_schema": {"name": "city", "schema": schema, "strict": True}},
               "messages": [{"role": "user", "content": "给出上海的城市名、所在国家和人口（百万）。"}]})
    if "_http_error" in r:
        return "FAIL", f"HTTP {r['_http_error']}: {r['_body']}", t
    content = (msg_of(r).get("content") or "").strip()
    try:
        obj = json.loads(content)
        missing = [k for k in schema["required"] if k not in obj]
        if missing:
            return "FAIL", f"JSON but missing {missing}: {short(content)}", t
        return "pass", short(content, 120), t
    except json.JSONDecodeError:
        return "FAIL", "response_format accepted but output is not JSON (silent ignore): " + short(content), t


def check_tools(c, mid, max_tokens):
    tools = [{"type": "function", "function": {"name": "get_weather", "description": "查询城市当前天气",
              "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}}]
    r, t = c.post("/chat/completions", {"model": mid, "max_tokens": max_tokens, "temperature": 0, "tools": tools,
               "messages": [{"role": "user", "content": "上海现在天气怎么样？"}]})
    if "_http_error" in r:
        return "FAIL", f"HTTP {r['_http_error']}: {r['_body']}", t
    calls = msg_of(r).get("tool_calls") or []
    if not calls:
        return "FAIL", "no tool_calls; content=" + short(msg_of(r).get("content") or ""), t
    f = calls[0].get("function", {})
    try:
        args = json.loads(f.get("arguments") or "{}")
    except json.JSONDecodeError:
        return "FAIL", f"arguments not JSON: {f.get('arguments')!r}", t
    city = str(args.get("city", ""))
    ok = f.get("name") == "get_weather" and ("上海" in city or "shanghai" in city.lower())
    return ("pass" if ok else "FAIL"), f"{f.get('name')}({args})", t


def check_vision(c, mid, max_tokens):
    b64 = base64.b64encode(digits_png("4729")).decode()
    r, t = c.post("/chat/completions", {"model": mid, "max_tokens": max_tokens, "temperature": 0, "messages": [
        {"role": "user", "content": [{"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                                     {"type": "text", "text": "图片里写的是什么数字？只回答数字。"}]}]})
    if "_http_error" in r:
        return "FAIL", f"HTTP {r['_http_error']}: {r['_body']}", t
    content = msg_of(r).get("content") or ""
    return ("pass" if "4729" in content.replace(" ", "") else "FAIL"), f"content={short(content, 80)!r}", t


def check_audio_in(c, mid, max_tokens):
    said = "今天上海的天气很好，气温二十三度。"
    b64 = base64.b64encode(speech_wav(said)).decode()
    r, t = c.post("/chat/completions", {"model": mid, "max_tokens": max_tokens, "temperature": 0, "messages": [
        {"role": "user", "content": [{"type": "input_audio", "input_audio": {"data": b64, "format": "wav"}},
                                     {"type": "text", "text": "请把这段语音逐字转写出来。"}]}]})
    if "_http_error" in r:
        return "FAIL", f"HTTP {r['_http_error']}: {r['_body']}", t
    content = msg_of(r).get("content") or ""
    ok = "上海" in content and ("二十三" in content or "23" in content)
    return ("pass" if ok else "FAIL"), f"said={said!r} heard={short(content, 80)!r}", t


def check_audio_out(c, mid, max_tokens, run_dir):
    body = {"model": mid, "max_tokens": max_tokens, "stream": True, "modalities": ["text", "audio"],
            "audio": {"voice": "Cherry", "format": "wav"},
            "messages": [{"role": "user", "content": "用一句话问候一下。"}]}
    audio_b64, text, err, last = "", "", None, None
    for t, ch in c.stream("/chat/completions", body):
        last = t
        if "_http_error" in ch:
            err = f"HTTP {ch['_http_error']}: {ch['_body']}"
            break
        for choice in ch.get("choices", []):
            d = choice.get("delta", {})
            text += d.get("content") or ""
            a = d.get("audio") or {}
            audio_b64 += a.get("data") or ""
            text += a.get("transcript") or ""
    if err:
        return "FAIL", err, last
    if not audio_b64:
        return "FAIL", f"no audio in stream (text-only reply: {short(text, 60)!r}); talker not served?", last
    blob = base64.b64decode(audio_b64)
    (run_dir / "audio_out.bin").write_bytes(blob)
    return "pass", f"{len(blob)} bytes audio saved; transcript={short(text, 60)!r}", last


def check_t2i(c, mid, size, extra, run_dir):
    body = {"model": mid, "prompt": "一只橘猫坐在窗台上，旁边的白纸上用黑色毛笔写着“沐曦”两个大字，柔和的午后阳光",
            "size": size, "n": 1, "response_format": "b64_json", **extra}
    r, t = c.post("/images/generations", body)
    if "_http_error" in r:
        return "FAIL", f"HTTP {r['_http_error']}: {r['_body']}", t
    try:
        item = r["data"][0]
    except (KeyError, IndexError):
        return "FAIL", "no data[0]: " + short(r), t
    if item.get("b64_json"):
        blob = base64.b64decode(item["b64_json"])
    elif item.get("url"):
        with urllib.request.urlopen(item["url"], timeout=120) as resp:
            blob = resp.read()
    else:
        return "FAIL", "data[0] has neither b64_json nor url: " + short(item), t
    fmt, dims = image_size(blob)
    out = run_dir / f"t2i.{fmt if fmt != 'unknown' else 'bin'}"
    out.write_bytes(blob)
    want = tuple(int(x) for x in size.split("x"))
    ok = dims == want
    return ("pass" if ok else "FAIL"), f"{fmt} {dims} (asked {want}), saved {out.relative_to(ROOT)}; check 「沐曦」 by eye", t


# ---------- main ----------

def load_key(arg):
    if arg:
        return arg
    for var in ("GITEE_AI_API_KEY", "MOARK_API_KEY"):
        if os.environ.get(var):
            return os.environ[var]
    for path in OPENCODE_PATHS:
        try:
            return json.loads(path.read_text())["provider"]["gitee-ai"]["options"]["apiKey"]
        except Exception:
            continue
    sys.exit("no API key: pass --api-key or set GITEE_AI_API_KEY / MOARK_API_KEY")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("model", help="key in models.json (e.g. qwen3.8-27b)")
    ap.add_argument("--base-url", default="https://ai.gitee.com/v1")
    ap.add_argument("--model-id", help="served model id (default: first gitee_ids entry)")
    ap.add_argument("--kind", help="override kind from models.json")
    ap.add_argument("--api-key")
    ap.add_argument("--max-tokens", type=int, default=4096, help="thinking models need room before the answer")
    ap.add_argument("--size", default="1024x1024", help="t2i size")
    ap.add_argument("--extra", default="{}", help='extra JSON for t2i, e.g. \'{"num_inference_steps": 8}\'')
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--only", help="comma list of checks to run")
    args = ap.parse_args()

    reg = {m["key"]: m for m in json.loads((ROOT / "models.json").read_text())["models"]}
    m = reg.get(args.model, {"key": args.model, "kind": args.kind, "gitee_ids": [args.model]})
    kind = args.kind or m["kind"]
    mid = args.model_id or m["gitee_ids"][0]
    c = Client(args.base_url, load_key(args.api_key), args.timeout)
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M")
    run_dir = RESULTS / f"{stamp}_{m['key']}"
    run_dir.mkdir(parents=True, exist_ok=True)
    mt = args.max_tokens

    plan = [("listed", lambda: check_listed(c, mid) + (None,))]
    if kind in ("llm", "vlm", "omni"):
        plan += [("basic", lambda: check_basic(c, mid, mt)), ("stream", lambda: check_stream(c, mid, mt)),
                 ("json_schema", lambda: check_json_schema(c, mid, mt)), ("tools", lambda: check_tools(c, mid, mt))]
    if kind in ("vlm", "omni"):
        plan += [("vision", lambda: check_vision(c, mid, mt))]
    if kind == "omni":
        plan += [("audio_in", lambda: check_audio_in(c, mid, mt)), ("audio_out", lambda: check_audio_out(c, mid, mt, run_dir))]
    if kind == "t2i":
        plan += [("t2i", lambda: check_t2i(c, mid, args.size, json.loads(args.extra), run_dir))]
    if kind == "t2av":
        plan += [("t2av", lambda: ("skip", "video endpoint on Gitee AI not documented yet; test by hand, log in models/minimax-h3.md", None))]
    if args.only:
        keep = set(args.only.split(","))
        plan = [p for p in plan if p[0] in keep]

    rows = []
    print(f"{m['key']} ({kind}) as {mid!r} @ {args.base_url}")
    for name, fn in plan:
        try:
            status, ev, secs = fn()
        except Exception as e:
            status, ev, secs = "FAIL", f"{type(e).__name__}: {e}", None
        rows.append({"check": name, "status": status, "seconds": round(secs, 2) if secs else None, "evidence": ev})
        print(f"  {status:4} {name:12} {('%.1fs' % secs) if secs else '':>7}  {ev}")

    rec = {"when": stamp, "model": m["key"], "model_id": mid, "kind": kind, "base_url": args.base_url, "checks": rows}
    (run_dir / "result.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1))
    log = RESULTS / "LOG.md"
    if not log.exists():
        log.write_text("# Smoke test log\n\n| when | model | endpoint | check | status | s | evidence |\n|---|---|---|---|---|---|---|\n")
    with log.open("a") as f:
        host = args.base_url.split("//")[-1].split("/")[0]
        for r in rows:
            ev = r["evidence"].replace("|", "\\|").replace("\n", " ")[:220]
            f.write(f"| {stamp} | {mid} | {host} | {r['check']} | {r['status']} | {r['seconds'] or ''} | {ev} |\n")
    fails = sum(r["status"] == "FAIL" for r in rows)
    print(f"  -> {len(rows) - fails}/{len(rows)} not failed; saved {run_dir.relative_to(ROOT)}/result.json")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())

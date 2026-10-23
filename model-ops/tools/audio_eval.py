#!/usr/bin/env python3
"""TTS acceptance on Moark (Gitee AI) or any OpenAI-style /v1/audio/speech endpoint: generate, check, compare.

  generate  synthesise every text in testsets/tts_texts.json with one model and save the audio + a manifest
  check     objective checks per clip (decodes, sample rate, duration, speech rate, leading/trailing silence,
            peak, clipping, loudness LUFS) plus an ASR round trip: the clip goes to an ASR model and the
            transcript is scored against the input text as CER, after punctuation removal and cn2an number
            normalisation on both sides
  compare   two checked runs side by side (before/after a migration): CER, duration, LUFS, failure counts

  ~/myworkspace/metax/tools/evalenv/bin/python tools/audio_eval.py generate --model IndexTTS-2 --label metax-20261023 \
      --extra '{"prompt_audio_url": "https://gitee.com/realhugh/imgs/raw/master/zero_shot_prompt.wav"}'
  ~/myworkspace/metax/tools/evalenv/bin/python tools/audio_eval.py check --label metax-20261023 --judge SenseVoiceSmall
  ~/myworkspace/metax/tools/evalenv/bin/python tools/audio_eval.py compare --a metax-20261023 --b c600-20261120

The ASR judge must stay the same model and endpoint for both sides of a comparison, otherwise a CER change
may come from the judge. SenseVoiceSmall runs on MetaX on Moark and costs nothing per call (2026-10-23).
Speaker similarity and predicted MOS need torch models and are not computed here (see ACCEPTANCE.md).
Needs numpy, soundfile, pyloudnorm and cn2an (metax/tools/evalenv). Audio files are git-ignored.
"""
import argparse
import datetime as dt
import hashlib
import io
import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
import warnings

import cn2an
import numpy as np
import pyloudnorm
import soundfile as sf

ROOT = pathlib.Path(__file__).resolve().parent.parent
RUNS = ROOT / "results" / "tts"
warnings.filterwarnings("ignore", module="cn2an")  # it warns on every string it cannot fully convert
PUNCT = re.compile(r"[\s，。！？、；：,.!?;:\"'“”‘’（）()《》<>【】\[\]…—\-·～~]+")


def load_key(arg):
    if arg:
        return arg
    for env in ("GITEE_AI_API_KEY", "MOARK_API_KEY"):
        if os.environ.get(env):
            return os.environ[env]
    for parent in (ROOT.parent, ROOT.parent.parent):
        p = parent / "dailyworkinmetax" / "comic-skill" / "opencode.json"
        if p.exists():
            return json.loads(p.read_text())["provider"]["gitee-ai"]["options"]["apiKey"]
    sys.exit("no API key: pass --api-key or set GITEE_AI_API_KEY")


def http(url, key, body=None, content_type="application/json", method="POST", timeout=300):
    data = body if isinstance(body, bytes) or body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": content_type})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read(), time.time() - t0
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read(), time.time() - t0


def fetch_audio(resp_headers, raw, key):
    """Sync TTS endpoints answer with audio bytes or with JSON holding a url / base64 / async task."""
    ctype = resp_headers.get("Content-Type", "")
    if not ctype.startswith("application/json"):
        return raw, None
    d = json.loads(raw)
    if d.get("task_id") and d.get("urls"):
        t0 = time.time()
        while d.get("status") not in ("success", "failure", "failed", "cancelled"):
            if time.time() - t0 > 900:
                return None, "async task timed out"
            time.sleep(2)
            _, _, r2, _ = http(d["urls"]["get"], key, method="GET")
            d = json.loads(r2)
        if d.get("status") != "success":
            return None, json.dumps(d, ensure_ascii=False)[:300]
        url = (d.get("output") or {}).get("file_url")
    else:
        url = d.get("url") or (d.get("data") or [{}])[0].get("url")
    if url:
        _, _, blob, _ = http(url, key, method="GET")
        return blob, None
    return None, "no audio in response: " + json.dumps(d, ensure_ascii=False)[:300]


def generate(a):
    texts = json.loads(pathlib.Path(a.texts).read_text())["texts"]
    est = len(texts) * a.price
    print(f"{len(texts)} texts with {a.model}, estimated ¥{est:.2f} at ¥{a.price}/call")
    if est > a.max_cost:
        sys.exit(f"above --max-cost {a.max_cost}; raise it to proceed")
    key = load_key(a.api_key)
    out = RUNS / a.label
    out.mkdir(parents=True, exist_ok=True)
    man = (out / "manifest.jsonl").open("a")
    extra = json.loads(a.extra)
    for t in texts:
        body = {"model": a.model, a.text_field: t["text"], **extra}
        st, h, raw, secs = http(f"{a.base_url.rstrip('/')}/{a.path}", key, body)
        rec = {"label": a.label, "model": a.model, "text_id": t["id"], "text": t["text"], "request": body,
               "status": st, "latency_s": round(secs, 2), "compute_s": h.get("X-Compute-Time"),
               "cost": h.get("X-Inference-Cost"), "trace_id": h.get("X-Trace-Id"),
               "when": dt.datetime.now().isoformat(timespec="seconds")}
        blob, err = (fetch_audio(h, raw, key) if st == 200 else (None, raw.decode("utf-8", "replace")[:300]))
        if blob:
            ext = "mp3" if blob[:3] == b"ID3" or blob[:2] == b"\xff\xfb" else "wav"
            f = out / a.model / f"{t['id']}.{ext}"
            f.parent.mkdir(exist_ok=True)
            f.write_bytes(blob)
            rec.update({"file": str(f.relative_to(out)), "sha256": hashlib.sha256(blob).hexdigest()})
        else:
            rec["error"] = err
        man.write(json.dumps(rec, ensure_ascii=False) + "\n")
        man.flush()
        print(f"  {t['id']:16} {'ok' if blob else 'FAIL'} {rec['latency_s']}s {err or ''}")


def norm(s):
    s = PUNCT.sub("", s)
    try:
        s = cn2an.transform(s, "cn2an")
    except Exception:
        pass
    return s.lower()


def cer(ref, hyp):
    r, h = norm(ref), norm(hyp)
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            cur = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
            prev, d[j] = d[j], cur
    return d[len(h)] / max(len(r), 1)


def silence_edges(x, sr, thresh_db=-45.0, frame_ms=10):
    n = max(int(sr * frame_ms / 1000), 1)
    frames = x[: len(x) // n * n].reshape(-1, n)
    db = 20 * np.log10(np.sqrt((frames ** 2).mean(axis=1)) + 1e-9)
    voiced = np.where(db > thresh_db)[0]
    if len(voiced) == 0:
        return None, None
    return voiced[0] * frame_ms / 1000, (len(db) - 1 - voiced[-1]) * frame_ms / 1000


def asr(blob, filename, judge, base_url, key):
    b = "----moark" + uuid.uuid4().hex
    fields = {"model": judge, "language": "zh"}
    if judge.startswith("whisper"):
        fields.update({"temperature": "0", "response_format": "json"})
    body = b"".join(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
                    for k, v in fields.items())
    body += (f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
             f"Content-Type: application/octet-stream\r\n\r\n").encode() + blob + f"\r\n--{b}--\r\n".encode()
    st, _, raw, _ = http(f"{base_url.rstrip('/')}/audio/transcriptions", key, body,
                         content_type=f"multipart/form-data; boundary={b}")
    return json.loads(raw).get("text", "") if st == 200 else None


def check(a):
    run = RUNS / a.label
    rows = [json.loads(line) for line in (run / "manifest.jsonl").read_text().splitlines() if line.strip()]
    flags = {t["id"]: t for t in json.loads(pathlib.Path(a.texts).read_text())["texts"]}
    key = load_key(a.api_key)
    out = []
    for r in rows:
        res = {"model": r["model"], "text_id": r["text_id"], "status": "ok" if r.get("file") else "no audio"}
        if r.get("file"):
            blob = (run / r["file"]).read_bytes()
            try:
                x, sr = sf.read(io.BytesIO(blob), always_2d=True)
            except Exception as e:
                res.update({"status": f"decode failed: {e}"})
                out.append(res)
                continue
            mono = x.mean(axis=1)
            dur = len(mono) / sr
            lead, trail = silence_edges(mono, sr)
            peak = float(np.abs(mono).max())
            try:
                lufs = float(pyloudnorm.Meter(sr).integrated_loudness(mono)) if dur >= 0.4 else None
            except Exception:
                lufs = None
            hyp = asr(blob, pathlib.Path(r["file"]).name, a.judge, a.base_url, key)
            score = flags.get(r["text_id"], {}).get("cer", True)
            res.update({
                "sr": sr, "channels": x.shape[1], "duration_s": round(dur, 2),
                "chars_per_s": round(len(norm(r["text"])) / dur, 2) if dur else None,
                "lead_silence_s": lead, "trail_silence_s": trail,
                "peak_dbfs": round(20 * np.log10(peak + 1e-9), 1),
                "clip_ratio": float((np.abs(mono) > 0.999).mean()), "lufs": round(lufs, 1) if lufs else None,
                "asr_judge": a.judge, "asr_text": hyp,
                "cer": round(cer(r["text"], hyp), 4) if (hyp is not None and score) else None,
            })
        out.append(res)
        print(f"  {res['text_id']:16} {res['status']:8} dur={res.get('duration_s')} cer={res.get('cer')} "
              f"lufs={res.get('lufs')} lead={res.get('lead_silence_s')} heard={str(res.get('asr_text'))[:40]!r}")
    (run / "checks.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    scored = [o["cer"] for o in out if o.get("cer") is not None]
    print(f"{len(out)} clips, {sum(o['status'] != 'ok' for o in out)} failed, "
          f"mean CER {np.mean(scored) if scored else float('nan'):.4f} over {len(scored)} scored clips")


def compare(a):
    A = {o["text_id"]: o for o in json.loads((RUNS / a.a / "checks.json").read_text())}
    B = {o["text_id"]: o for o in json.loads((RUNS / a.b / "checks.json").read_text())}
    lines = [f"# TTS 对比：{a.a} -> {a.b}", "", "| 文本 | CER A->B | 时长 A->B (s) | LUFS A->B | 首尾静音 B (s) | B 听到的 |",
             "|---|---|---|---|---|---|"]
    for tid in A:
        oa, ob = A[tid], B.get(tid, {})
        lines.append(f"| {tid} | {oa.get('cer')}->{ob.get('cer')} | {oa.get('duration_s')}->{ob.get('duration_s')} | "
                     f"{oa.get('lufs')}->{ob.get('lufs')} | {ob.get('lead_silence_s')}/{ob.get('trail_silence_s')} | "
                     f"{str(ob.get('asr_text'))[:30]} |")
    ca = [o["cer"] for o in A.values() if o.get("cer") is not None]
    cb = [o["cer"] for o in B.values() if o.get("cer") is not None]
    lines += ["", f"平均 CER：{np.mean(ca):.4f} -> {np.mean(cb):.4f}（差 {np.mean(cb) - np.mean(ca):+.4f}）",
              f"失败：{sum(o['status'] != 'ok' for o in A.values())} -> {sum(o['status'] != 'ok' for o in B.values())}"]
    out = ROOT / "results" / "compare" / f"tts_{a.a}__vs__{a.b}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n")
    print("\n".join(lines[-2:]) + f"\nreport {out}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("generate", "check", "compare"):
        p = sub.add_parser(name)
        p.add_argument("--api-key")
        p.add_argument("--base-url", default="https://ai.gitee.com/v1")
        p.add_argument("--texts", default=str(ROOT / "testsets" / "tts_texts.json"))
        if name == "generate":
            p.add_argument("--model", required=True)
            p.add_argument("--label", required=True)
            p.add_argument("--path", default="audio/speech", help="relative to --base-url")
            p.add_argument("--text-field", default="input", help="input for most models, inputs for some")
            p.add_argument("--extra", default="{}", help="model-specific JSON fields, e.g. voice or prompt audio")
            p.add_argument("--price", type=float, default=2.0, help="CNY per call, for the cost guard")
            p.add_argument("--max-cost", type=float, default=5.0)
        elif name == "check":
            p.add_argument("--label", required=True)
            p.add_argument("--judge", default="SenseVoiceSmall")
        else:
            p.add_argument("--a", required=True)
            p.add_argument("--b", required=True)
    a = ap.parse_args()
    {"generate": generate, "check": check, "compare": compare}[a.cmd](a)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Capture a reproducible image baseline from Moark (Gitee AI) for the image models that run on MetaX.

Why: once a model moves from C500 to C600 the old outputs can no longer be produced, so the same requests
(prompt x seed x explicit parameters) are captured before the move and replayed after it.
tools/compare_images.py then compares the two captures.

The request for each model is built from the package inventory (state/moark_pkg1492.json, written by
tools/moark_inventory.py): the MetaX text-to-image operation, its own parameter names (num_inference_steps vs
steps, guidance_scale vs cfg_scale) and its current defaults, written out explicitly so a later change of
platform defaults does not look like a hardware difference.

  python3 tools/image_baseline.py --label c500-20261023 --dry-run          # plan + estimated cost, no calls
  python3 tools/image_baseline.py --label c500-20261023 --models flux-1-schnell --prompts-limit 2
  python3 tools/image_baseline.py --label c500-20261023 --max-cost 30      # full run
Images go to results/baselines/<label>/<model>/ (git-ignored); results/baselines/<label>/manifest.jsonl
(committed) keeps the request, sha256, size, latency, server compute time, cost and trace id for each image.
Stdlib only.
"""
import argparse
import base64
import datetime as dt
import hashlib
import json
import os
import pathlib
import struct
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
BASE = "https://ai.gitee.com"
DEFAULT_MODELS = ["FLUX.1-dev", "HiDream-I1-Full", "Kolors", "qwen-image-2.1-viggle-turbo", "Qwen-Image-2512",
                  "stable-diffusion-3.5-large-turbo", "z-image-turbo", "flux-1-schnell"]
STEP_KEYS = ("num_inference_steps", "steps")
CFG_KEYS = ("guidance_scale", "cfg_scale")


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


def http(method, url, key, body=None, timeout=300):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read(), time.time() - t0
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read(), time.time() - t0


def image_info(blob):
    if blob[:8] == b"\x89PNG\r\n\x1a\n":
        return "png", list(struct.unpack(">II", blob[16:24]))
    if blob[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(blob):
            marker, seg = blob[i + 1], struct.unpack(">H", blob[i + 2:i + 4])[0]
            if marker in (0xC0, 0xC1, 0xC2):
                h, w = struct.unpack(">HH", blob[i + 5:i + 9])
                return "jpg", [w, h]
            i += 2 + seg
    if blob[:4] == b"RIFF" and blob[8:12] == b"WEBP":
        return "webp", None
    return "bin", None


def pick_operation(model):
    """The MetaX text-to-image operation at the default size, preferring the synchronous endpoint."""
    ops = [op for op in model["operations"] if op["vendor"] == "metax" and op["type"] == "text2image"
           and "control_image" not in op["params"]]
    if not ops:
        return None
    def rank(op):
        size = (op["params"].get("size") or {}).get("default", "")
        return (op["path"] != "v1/images/generations", size not in ("", "1024x1024"), op["price"])
    return sorted(ops, key=rank)[0]


def build_request(name, op, prompt, seed, size):
    p = op["params"]
    body = {"model": name, "prompt": prompt["prompt"]}
    if "size" in p:
        body["size"] = size
    elif "width" in p and "height" in p:
        w, h = size.split("x")
        body["width"], body["height"] = int(w), int(h)
    for keys in (STEP_KEYS, CFG_KEYS):
        for k in keys:
            if k in p and "default" in p[k]:
                body[k] = p[k]["default"]
                break
    if "seed" in p and seed is not None:
        body["seed"] = seed
    if prompt.get("negative_prompt") and "negative_prompt" in p:
        body["negative_prompt"] = prompt["negative_prompt"]
    if "response_format" in p and op["path"] == "v1/images/generations":
        body["response_format"] = "b64_json"
    if "return_image_format" in p:
        body["return_image_format"] = "PNG"
    return body


def run_one(key, op, body):
    """Returns (record fields, image bytes or None)."""
    if op["path"].startswith("v1/async/"):
        st, h, raw, sub_s = http("POST", f"{BASE}/{op['path']}", key, body)
        if st != 200:
            return {"status": f"HTTP {st}", "error": raw.decode("utf-8", "replace")[:400]}, None
        task = json.loads(raw)
        t0 = time.time()
        while True:
            st, h, raw, _ = http("GET", task["urls"]["get"], key)
            d = json.loads(raw)
            if d.get("status") not in ("waiting", "in_progress", "running", "pending", "queued"):
                break
            if time.time() - t0 > 900:
                return {"status": "timeout", "task_id": task.get("task_id")}, None
            time.sleep(2)
        if d.get("status") != "success":
            return {"status": d.get("status"), "task_id": d.get("task_id"), "error": json.dumps(d)[:400]}, None
        st, _, blob, _ = http("GET", d["output"]["file_url"], key)
        rec = {"status": "ok", "task_id": d.get("task_id"), "cost": d.get("price"),
               "queue_s": round((d["started_at"] - d["created_at"]) / 1000, 2),
               "run_s": round((d["completed_at"] - d["started_at"]) / 1000, 2),
               "latency_s": round((d["completed_at"] - d["created_at"]) / 1000 + sub_s, 2)}
        return rec, blob
    st, h, raw, secs = http("POST", f"{BASE}/{op['path']}", key, body)
    rec = {"latency_s": round(secs, 2), "compute_s": h.get("X-Compute-Time"), "cost": h.get("X-Inference-Cost"),
           "trace_id": h.get("X-Trace-Id")}
    if st != 200:
        return {**rec, "status": f"HTTP {st}", "error": raw.decode("utf-8", "replace")[:400]}, None
    item = json.loads(raw)["data"][0]
    if item.get("b64_json"):
        return {**rec, "status": "ok"}, base64.b64decode(item["b64_json"])
    if item.get("url"):
        _, _, blob, _ = http("GET", item["url"], key)
        return {**rec, "status": "ok"}, blob
    return {**rec, "status": "no image in response", "error": json.dumps(item)[:400]}, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True, help="capture name, e.g. c500-20261023 or c600-20261120")
    ap.add_argument("--models", default=",".join(DEFAULT_MODELS))
    ap.add_argument("--prompts", default=str(ROOT / "testsets" / "image_prompts.json"))
    ap.add_argument("--prompts-limit", type=int, default=0, help="use only the first N prompts")
    ap.add_argument("--seeds", default="42,20261023")
    ap.add_argument("--size", default="1024x1024")
    ap.add_argument("--repeat", type=int, default=1, help="runs per (prompt, seed); 2 measures run-to-run drift")
    ap.add_argument("--max-cost", type=float, default=5.0, help="refuse to start above this estimate (CNY)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--api-key")
    a = ap.parse_args()

    inv = json.loads((ROOT / "state" / "moark_pkg1492.json").read_text())["snapshot"]["models"]
    prompts = json.loads(pathlib.Path(a.prompts).read_text())["prompts"]
    if a.prompts_limit:
        prompts = prompts[:a.prompts_limit]
    seeds = [int(s) for s in a.seeds.split(",") if s]

    plan, cost = [], 0.0
    for name in a.models.split(","):
        if name not in inv:
            sys.exit(f"{name} is not in the package inventory; run tools/moark_inventory.py")
        op = pick_operation(inv[name])
        if not op:
            print(f"skip {name}: no MetaX text-to-image operation")
            continue
        has_seed = "seed" in op["params"]
        for pr in prompts:
            for seed in (seeds if has_seed else [None] * len(seeds)):
                for r in range(a.repeat):
                    plan.append((name, op, pr, seed, r))
                    cost += float(op["price"] or 0)
    by_model = {}
    for name, op, *_ in plan:
        by_model.setdefault(name, [op, 0])[1] += 1
    for name, (op, n) in by_model.items():
        seedinfo = "seeded" if "seed" in op["params"] else "NO SEED (distribution-level compare only)"
        print(f"  {name:34} {n:4d} images x ¥{op['price']}  {op['name']} {op['path']}  {seedinfo}")
    print(f"plan: {len(plan)} images, estimated ¥{cost:.2f}")
    if a.dry_run:
        name, op, pr, seed, _ = plan[0]
        print("example request:", json.dumps(build_request(name, op, pr, seed, a.size), ensure_ascii=False))
        return
    if cost > a.max_cost:
        sys.exit(f"estimated ¥{cost:.2f} is above --max-cost {a.max_cost}; raise it to proceed")

    key = load_key(a.api_key)
    out = ROOT / "results" / "baselines" / a.label
    out.mkdir(parents=True, exist_ok=True)
    manifest = (out / "manifest.jsonl").open("a")
    spent, fails = 0.0, 0
    for i, (name, op, pr, seed, r) in enumerate(plan, 1):
        body = build_request(name, op, pr, seed, a.size)
        rec, blob = run_one(key, op, body)
        rec.update({"label": a.label, "model": name, "prompt_id": pr["id"], "seed": seed, "repeat": r,
                    "operation": op["name"], "path": op["path"], "request": body,
                    "when": dt.datetime.now().isoformat(timespec="seconds")})
        if blob:
            fmt, dims = image_info(blob)
            stem = f"{pr['id']}_s{seed if seed is not None else 'none'}_r{r}"
            f = out / name / f"{stem}.{fmt}"
            f.parent.mkdir(exist_ok=True)
            f.write_bytes(blob)
            rec.update({"file": str(f.relative_to(out)), "sha256": hashlib.sha256(blob).hexdigest(),
                        "format": fmt, "dims": dims})
        else:
            fails += 1
        spent += float(rec.get("cost") or 0)
        manifest.write(json.dumps(rec, ensure_ascii=False) + "\n")
        manifest.flush()
        print(f"[{i}/{len(plan)}] {rec['status']:8} {name:30} {pr['id']:16} seed={seed} "
              f"{rec.get('latency_s', '')}s ¥{rec.get('cost', '')}")
    print(f"done: {len(plan) - fails} ok, {fails} failed, spent about ¥{spent:.2f}; manifest {out / 'manifest.jsonl'}")


if __name__ == "__main__":
    main()

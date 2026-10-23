#!/usr/bin/env python3
"""Snapshot a Moark (Gitee AI) resource package and report what changed since the last run.

The package page (https://ai.gitee.com/serverless-api/packages/<id>) is a client-rendered app. Its data comes from
the public JSON API the page itself calls:
  GET https://ai.gitee.com/api/pay/services/<id>                       package (name, vendor, compute)
  GET https://ai.gitee.com/api/pay/service/operations?package_id=<id>  every model in it, with its operations
Each operation carries the compute it runs on (vendor "metax" + region "prod-mx-sh-ip" means MetaX's Shanghai
cluster, "bailian" means it is forwarded to Alibaba Bailian), the HTTP path, the price and the request parameters
with their defaults. A model moving to C600 should show up here as a compute or region change.

  python3 tools/moark_inventory.py                 # package 1492 (沐曦 Token 资源包), all modalities
  python3 tools/moark_inventory.py --kinds image   # only image generation / editing rows in the printout
State: state/moark_pkg<id>.json; changes are appended to state/CHANGELOG.md. Stdlib only.
"""
import argparse
import datetime as dt
import json
import pathlib
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
API = "https://ai.gitee.com/api/pay"
UA = {"User-Agent": "Mozilla/5.0 (metax-model-ops)"}  # the CDN refuses requests without a browser-like UA

# operation.type values seen in package 1492 (2026-10-23), grouped the way the acceptance work is split
KINDS = {
    "image": {"text2image", "image2image", "image_matting"},
    "audio": {"text2speech", "speech2text", "text2music"},
    "video": {"text2video", "image2video", "image_video2video", "audio_video2video"},
}


def get_json(url, attempts=4):
    err = None
    for i in range(attempts):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            sys.exit(f"{url}: HTTP {e.code}")
        except Exception as e:  # local proxy drops TLS now and then
            err = e
            time.sleep(1.5 * (i + 1))
    sys.exit(f"{url}: {err}")


def param_summary(params):
    """Keep what matters for testing: name, type, default, and the allowed values."""
    out = {}
    for p in params or []:
        entry = {"type": p.get("type")}
        for src, dst in (("default_value", "default"), ("fixed_value", "fixed"), ("minimum", "min"),
                         ("maximum", "max"), ("step", "step"), ("required", "required")):
            if p.get(src) is not None:
                entry[dst] = p[src]
        if p.get("options"):
            entry["options"] = [o.get("value") for o in p["options"]][:30]
        out[p.get("name")] = entry
    return out


def snapshot(pkg_id):
    pkg = get_json(f"{API}/services/{pkg_id}")
    items = get_json(f"{API}/service/operations?package_id={pkg_id}")
    models = {}
    for it in items:
        s = it["service"]
        key = s.get("ident") or s.get("name")
        ops = []
        for op in it.get("operations", []):
            ops.append({
                "id": op.get("id"), "name": op.get("name"), "type": op.get("type"), "path": op.get("path"),
                "vendor": op.get("vendor"), "region": op.get("region"), "compute": op.get("compute"),
                "price": op.get("price"), "params": param_summary(op.get("params")),
            })
        models[key] = {
            "service_id": s.get("id"), "owned_by": (s.get("props") or {}).get("owned_by"),
            "tags": sorted({t["name"] for t in s.get("tags", [])}),
            "created": dt.datetime.fromtimestamp(s["created_at"] / 1000).strftime("%Y-%m-%d"),
            "operations": ops,
        }
    return {"package": {k: pkg.get(k) for k in ("id", "name", "vendor", "region", "compute")}, "models": models}


def kind_of(model):
    types = {op["type"] for op in model["operations"]}
    for k, vals in KINDS.items():
        if types & vals:
            return k
    return "other"


def diff(old, new):
    out = []
    o, n = old["models"], new["models"]
    for k in sorted(set(n) - set(o)):
        out.append(f"+ model {k} ({kind_of(n[k])}, {', '.join(sorted({op['vendor'] for op in n[k]['operations']}))})")
    for k in sorted(set(o) - set(n)):
        out.append(f"- model {k} removed from package")
    for k in sorted(set(o) & set(n)):
        oo = {op["id"]: op for op in o[k]["operations"]}
        nn = {op["id"]: op for op in n[k]["operations"]}
        for i in sorted(set(nn) - set(oo)):
            out.append(f"+ {k}: operation {nn[i]['name']} ({nn[i]['path']})")
        for i in sorted(set(oo) - set(nn)):
            out.append(f"- {k}: operation {oo[i]['name']} removed")
        for i in sorted(set(oo) & set(nn)):
            for field in ("vendor", "region", "compute", "path", "price"):
                if oo[i][field] != nn[i][field]:
                    flag = "  <- compute moved" if field in ("vendor", "region", "compute") else ""
                    out.append(f"~ {k} / {nn[i]['name']}: {field} {oo[i][field]} -> {nn[i][field]}{flag}")
            if oo[i]["params"] != nn[i]["params"]:
                out.append(f"~ {k} / {nn[i]['name']}: request parameters changed")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--package", type=int, default=1492)
    ap.add_argument("--kinds", default="image,audio,video", help="kinds to print: image,audio,video,other")
    ap.add_argument("--quiet", action="store_true", help="print only changes")
    a = ap.parse_args()

    state = ROOT / "state" / f"moark_pkg{a.package}.json"
    new = snapshot(a.package)
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    old = json.loads(state.read_text())["snapshot"] if state.exists() else None
    changes = diff(old, new) if old else [f"(baseline recorded for package {a.package}: {len(new['models'])} models)"]

    if not a.quiet:
        p = new["package"]
        print(f"package {p['id']} {p['name']}  compute={p['compute']}  models={len(new['models'])}")
        want = set(a.kinds.split(","))
        for key, m in sorted(new["models"].items(), key=lambda kv: (kind_of(kv[1]), kv[0].lower())):
            k = kind_of(m)
            if k not in want:
                continue
            vendors = sorted({f"{op['vendor']}/{op['region']}" for op in m["operations"]})
            paths = sorted({op["path"] for op in m["operations"]})
            print(f"  [{k:5}] {key:36} {','.join(vendors):28} {' '.join(paths)}")
        print()

    if changes:
        print(f"[{now}] {len(changes)} change(s) in package {a.package}:")
        for c in changes:
            print("  " + c)
        with (ROOT / "state" / "CHANGELOG.md").open("a") as f:
            f.write(f"\n## {now} (Moark package {a.package})\n\n" + "\n".join(f"- {c}" for c in changes) + "\n")
    elif not a.quiet:
        print(f"[{now}] no changes in package {a.package}")
    state.write_text(json.dumps({"updated": now, "snapshot": new}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

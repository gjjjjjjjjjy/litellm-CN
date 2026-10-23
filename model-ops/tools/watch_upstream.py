#!/usr/bin/env python3
"""Watch upstream for the models in models.json and report what changed since the last run.

What it checks, per model:
  - HF main repo (and hf_alt repos): commit sha + lastModified  -> weights / config / chat template changed
  - HF official siblings (variant_search): new FP8 / AWQ / GGUF / -Flash repos from the same org
  - HF community quants (community_search): top repos by downloads across all authors
  - HF discussions on the main repo: new threads (known issues usually show up here first)
  - ModelScope mirror exists or not
  - Gitee AI (ai.gitee.com/v1/models): is any of gitee_ids listed
Per framework (frameworks): latest GitHub release tag.

State is kept in state/upstream.json; every change is appended to state/CHANGELOG.md.
Stdlib only, so it runs on the plain Homebrew python3.

  python3 tools/watch_upstream.py            # full report + changes
  python3 tools/watch_upstream.py --quiet    # print only changes (for cron/launchd)
"""
import argparse
import datetime as dt
import json
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "models.json"
STATE = ROOT / "state" / "upstream.json"
CHANGELOG = ROOT / "state" / "CHANGELOG.md"
HF = "https://huggingface.co"
UA = {"User-Agent": "metax-model-ops/0.1"}


def fetch(url, timeout=25, attempts=4):
    """Return (bytes, None) or (None, error string).
    The machine goes out through a local proxy (127.0.0.1:7897) that drops TLS now and then,
    so transport errors are retried; HTTP errors are real answers and are returned at once."""
    req = urllib.request.Request(url, headers=UA)
    err = None
    for i in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read(), None
        except urllib.error.HTTPError as e:
            return None, f"HTTP {e.code}"
        except Exception as e:
            err = e
            time.sleep(1.5 * (i + 1))
    return None, f"{type(err).__name__}: {err}"


def get_json(url):
    body, err = fetch(url)
    return {"_error": err} if err else json.loads(body)


def hf_repo(repo):
    d = get_json(f"{HF}/api/models/{repo}")
    if "_error" in d:
        return {"error": d["_error"]}
    return {"sha": d.get("sha"), "lastModified": d.get("lastModified"), "downloads": d.get("downloads")}


def hf_search(author=None, search=None, limit=30, sort="createdAt"):
    q = {"search": search, "limit": limit, "sort": sort, "direction": -1}
    if author:
        q["author"] = author
    d = get_json(f"{HF}/api/models?" + urllib.parse.urlencode(q))
    if isinstance(d, dict):
        return {"error": d.get("_error")}
    return sorted(m["id"] for m in d)


def hf_discussions(repo, n=15):
    d = get_json(f"{HF}/api/models/{repo}/discussions")
    if "_error" in d:
        return {"error": d["_error"]}
    items = d.get("discussions", [])[:n]
    return {str(x["num"]): x.get("title", "") for x in items}


def modelscope_exists(repo):
    d = get_json(f"https://www.modelscope.cn/api/v1/models/{repo}")
    return bool(d.get("Success")) if "_error" not in d else False


def modelscope_info(repo):
    d = get_json(f"https://www.modelscope.cn/api/v1/models/{repo}")
    if "_error" in d:
        return {"error": d["_error"]}
    x = d.get("Data") or {}
    if not d.get("Success"):
        return {"exists": False}
    ts = x.get("LastUpdatedTime")
    return {"exists": True, "updated": dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else None,
            "size_gb": round((x.get("StorageSize") or 0) / 1e9, 1)}


def gitee_ids():
    d = get_json("https://ai.gitee.com/v1/models")
    if "_error" in d:
        return None
    return {m["id"].lower(): m["id"] for m in d.get("data", [])}


def gh_release(repo):
    # Atom feeds instead of api.github.com: the API allows 60 unauthenticated calls an hour, feeds aren't counted.
    # releases.atom lists pre-releases too; repos with no releases fall back to tags.atom.
    ns = {"a": "http://www.w3.org/2005/Atom"}
    for feed in ("releases", "tags"):
        body, err = fetch(f"https://github.com/{repo}/{feed}.atom")
        if err:
            return {"error": err}
        entry = ET.fromstring(body).find("a:entry", ns)
        if entry is not None:
            link = entry.find("a:link", ns).get("href", "")
            return {"tag": link.rsplit("/", 1)[-1], "published": entry.findtext("a:updated", "", ns)[:10], "from": feed}
    return {"error": "no releases or tags"}


def snapshot(reg):
    snap = {"models": {}, "frameworks": {}}
    listed = gitee_ids()
    for m in reg["models"]:
        s = {"main": hf_repo(m["hf"])}
        for alt in m.get("hf_alt", []):
            s[f"alt:{alt}"] = hf_repo(alt)
        variants = set()
        for a, q in m.get("variant_search", []):
            found = hf_search(a, q)
            if isinstance(found, list):
                variants.update(found)
        s["official_variants"] = sorted(variants)
        cs = hf_search(None, m.get("community_search", m["hf"].split("/")[1]), limit=20, sort="downloads")
        s["community_top20"] = cs if isinstance(cs, list) else []
        s["discussions"] = hf_discussions(m["hf"])
        s["modelscope"] = modelscope_exists(m["modelscope"]) if m.get("modelscope") else None
        for alt in m.get("modelscope_alt", []):
            s[f"ms:{alt}"] = modelscope_info(alt)
        if listed is not None:
            s["gitee_listed"] = sorted(listed[g.lower()] for g in m.get("gitee_ids", []) if g.lower() in listed)
        snap["models"][m["key"]] = s
    for fw in reg.get("frameworks", []):
        snap["frameworks"][fw] = gh_release(fw)
    return snap


def diff(old, new, path=""):
    """Yield human-readable change lines between two nested dict/list snapshots."""
    if isinstance(old, dict) and isinstance(new, dict):
        for k in sorted(set(old) | set(new)):
            p = f"{path}.{k}" if path else k
            if k not in old:
                yield f"+ {p}: {json.dumps(new[k], ensure_ascii=False)[:200]}"
            elif k not in new:
                yield f"- {p} (gone)"
            else:
                yield from diff(old[k], new[k], p)
    elif isinstance(old, list) and isinstance(new, list):
        added, removed = sorted(set(new) - set(old)), sorted(set(old) - set(new))
        for a in added:
            yield f"+ {path}: {a}"
        for r in removed:
            yield f"- {path}: {r}"
    elif old != new:
        yield f"~ {path}: {old} -> {new}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true", help="print only changes")
    args = ap.parse_args()

    reg = json.loads(REGISTRY.read_text())
    new = snapshot(reg)
    old = json.loads(STATE.read_text())["snapshot"] if STATE.exists() else None
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")

    if old is not None:
        # a failed fetch is not an upstream change: keep last known value and say so
        def carry(o, n, path=""):
            if isinstance(o, dict) and isinstance(n, dict):
                for k in list(n):
                    if k in o:
                        if isinstance(n[k], dict) and "error" in n[k] and isinstance(o[k], dict) and "error" not in o[k]:
                            print(f"warn: {path}{k} fetch failed ({n[k]['error']}), kept last value", file=sys.stderr)
                            n[k] = o[k]
                        else:
                            carry(o[k], n[k], f"{path}{k}.")
        carry(old, new)

    if old is None:
        changes = ["(baseline recorded)"]
    else:
        # downloads move every day; not a change worth reporting
        def strip(s):
            s = json.loads(json.dumps(s))
            for m in s.get("models", {}).values():
                for v in m.values():
                    if isinstance(v, dict):
                        v.pop("downloads", None)
            return s
        changes = list(diff(strip(old), strip(new)))

    if not args.quiet:
        for key, s in new["models"].items():
            main_ = s["main"]
            print(f"== {key}: sha {str(main_.get('sha'))[:10]}  modified {main_.get('lastModified')}  "
                  f"modelscope={'yes' if s.get('modelscope') else 'no'}  gitee={s.get('gitee_listed') or '-'}")
            print(f"   official variants: {', '.join(s['official_variants']) or '-'}")
            print(f"   latest discussions: {list(s['discussions'].items())[:3] if isinstance(s['discussions'], dict) else s['discussions']}")
        for fw, r in new["frameworks"].items():
            print(f"== {fw}: {r.get('tag')} {r.get('published') or ''}{r.get('error') or ''}")
        print()

    if changes:
        print(f"[{now}] {len(changes)} change(s):")
        for c in changes:
            print("  " + c)
        with CHANGELOG.open("a") as f:
            f.write(f"\n## {now}\n\n" + "\n".join(f"- {c}" for c in changes) + "\n")
    elif not args.quiet:
        print(f"[{now}] no upstream changes")

    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps({"updated": now, "snapshot": new}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    sys.exit(main())

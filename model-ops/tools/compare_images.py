#!/usr/bin/env python3
"""Compare two image captures from tools/image_baseline.py, e.g. before and after the C500 to C600 move.

Seeded models are compared pair by pair (same model, prompt, seed): byte-identical, or PSNR / SSIM / mean
absolute difference. Models whose API exposes no seed (Kolors, SD3.5-large-turbo) cannot be paired, so their
images are compared as groups on coarse statistics that move when something is broken (brightness, saturation,
sharpness, near-black or near-white frames).

Writes results/compare/<a>__vs__<b>/report.md, side_by_side.html (A | B | difference) and blind.html, which
shows each pair in random order for a blind A/B vote, with the answer key in blind_key.json.

  ~/myworkspace/metax/tools/evalenv/bin/python tools/compare_images.py --a c500-20261023 --b c600-20261120
Needs numpy and Pillow (metax/tools/evalenv). Verdict thresholds are explained in ACCEPTANCE.md.
"""
import argparse
import html
import json
import pathlib
import random
from collections import defaultdict

import numpy as np
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
BASE = ROOT / "results" / "baselines"

# first-pass thresholds, to be recalibrated on a known-equivalent pair (see ACCEPTANCE.md 图像 4.2)
SSIM_SAME, PSNR_SAME = 0.98, 35.0
SSIM_CLOSE = 0.90


def load(label):
    rows = [json.loads(line) for line in (BASE / label / "manifest.jsonl").read_text().splitlines() if line.strip()]
    return [r for r in rows if r.get("status") == "ok" and r.get("file")]


def rgb(label, rec, size=None):
    im = Image.open(BASE / label / rec["file"]).convert("RGB")
    if size and im.size != size:
        im = im.resize(size, Image.Resampling.LANCZOS)
    return np.asarray(im, dtype=np.float64)


def gaussian_kernel(size=11, sigma=1.5):
    x = np.arange(size) - size // 2
    k = np.exp(-(x ** 2) / (2 * sigma ** 2))
    return k / k.sum()


def blur(img, k):
    pad = len(k) // 2
    p = np.pad(img, pad, mode="reflect")
    tmp = np.apply_along_axis(lambda r: np.convolve(r, k, mode="valid"), 1, p)
    return np.apply_along_axis(lambda c: np.convolve(c, k, mode="valid"), 0, tmp)


def ssim(a, b):
    """SSIM on luma (Wang et al. 2004, 11x11 Gaussian window, sigma 1.5)."""
    def luma(x):
        return 0.299 * x[..., 0] + 0.587 * x[..., 1] + 0.114 * x[..., 2]
    x, y = luma(a), luma(b)
    k = gaussian_kernel()
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    mx, my = blur(x, k), blur(y, k)
    sxx, syy, sxy = blur(x * x, k) - mx ** 2, blur(y * y, k) - my ** 2, blur(x * y, k) - mx * my
    m = ((2 * mx * my + c1) * (2 * sxy + c2)) / ((mx ** 2 + my ** 2 + c1) * (sxx + syy + c2))
    return float(m.mean())


def psnr(a, b):
    mse = float(((a - b) ** 2).mean())
    return float("inf") if mse == 0 else 10 * np.log10(255 ** 2 / mse)


def stats(img):
    gray = img.mean(axis=2)
    mx, mn = img.max(axis=2), img.min(axis=2)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0)
    lap = gray[1:-1, 1:-1] * 4 - gray[:-2, 1:-1] - gray[2:, 1:-1] - gray[1:-1, :-2] - gray[1:-1, 2:]
    return {"brightness": float(gray.mean()), "saturation": float(sat.mean()), "sharpness": float(lap.var()),
            "near_black": bool(gray.mean() < 8), "near_white": bool(gray.mean() > 247)}


def verdict(row):
    if row["identical"]:
        return "identical"
    if row["ssim"] >= SSIM_SAME and row["psnr"] >= PSNR_SAME:
        return "same"
    if row["ssim"] >= SSIM_CLOSE:
        return "close, look"
    return "different, review"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True, help="reference capture label (before)")
    ap.add_argument("--b", required=True, help="candidate capture label (after)")
    ap.add_argument("--seed", type=int, default=0, help="shuffle seed for blind.html")
    args = ap.parse_args()

    A, B = load(args.a), load(args.b)
    key = lambda r: (r["model"], r["prompt_id"], r["seed"], r.get("repeat", 0))
    bmap = {key(r): r for r in B}
    out = ROOT / "results" / "compare" / f"{args.a}__vs__{args.b}"
    out.mkdir(parents=True, exist_ok=True)

    paired, unpaired = [], defaultdict(lambda: {"a": [], "b": []})
    for ra in A:
        if ra["seed"] is None:
            unpaired[ra["model"]]["a"].append(ra)
            continue
        rb = bmap.get(key(ra))
        if not rb:
            continue
        row = {"model": ra["model"], "prompt_id": ra["prompt_id"], "seed": ra["seed"], "a": ra, "b": rb,
               "identical": ra["sha256"] == rb["sha256"]}
        if row["identical"]:
            row.update({"psnr": float("inf"), "ssim": 1.0, "mae": 0.0})
        else:
            ia = rgb(args.a, ra)
            ib = rgb(args.b, rb, size=(ia.shape[1], ia.shape[0]))
            row.update({"psnr": psnr(ia, ib), "ssim": ssim(ia, ib), "mae": float(np.abs(ia - ib).mean()),
                        "dims_changed": ra.get("dims") != rb.get("dims")})
            diff = np.clip(np.abs(ia - ib).mean(axis=2) * 4, 0, 255).astype(np.uint8)
            dfile = out / "diff" / ra["model"] / f"{ra['prompt_id']}_s{ra['seed']}.png"
            dfile.parent.mkdir(parents=True, exist_ok=True)
            Image.fromarray(diff).save(dfile)
            row["diff_file"] = str(dfile.relative_to(out))
        row["verdict"] = verdict(row)
        paired.append(row)
    for rb in B:
        if rb["seed"] is None:
            unpaired[rb["model"]]["b"].append(rb)

    lines = [f"# 图像对比：{args.a} -> {args.b}", ""]
    by_model = defaultdict(list)
    for r in paired:
        by_model[r["model"]].append(r)
    lines += ["## 同 seed 逐张对比", "", "| 模型 | 对数 | 完全一致 | same | close | different | SSIM 最低 | PSNR 最低 |",
              "|---|---|---|---|---|---|---|---|"]
    for m, rows in sorted(by_model.items()):
        cnt = defaultdict(int)
        for r in rows:
            cnt[r["verdict"]] += 1
        lines.append(f"| {m} | {len(rows)} | {cnt['identical']} | {cnt['same']} | {cnt['close, look']} | "
                     f"{cnt['different, review']} | {min(r['ssim'] for r in rows):.3f} | "
                     f"{min(r['psnr'] for r in rows):.1f} |")
    lines += ["", "## 无 seed 模型：按组比较粗统计", "",
              "| 模型 | A 张数 | B 张数 | 亮度 A->B | 饱和度 A->B | 清晰度 A->B | 全黑/全白 A->B |", "|---|---|---|---|---|---|---|"]
    for m, g in sorted(unpaired.items()):
        sa = [stats(rgb(args.a, r)) for r in g["a"]]
        sb = [stats(rgb(args.b, r)) for r in g["b"]]
        if not sa or not sb:
            lines.append(f"| {m} | {len(sa)} | {len(sb)} | | | | |")
            continue
        def mean(xs, k):
            return float(np.mean([x[k] for x in xs]))
        bad = lambda xs: sum(x["near_black"] or x["near_white"] for x in xs)
        lines.append(f"| {m} | {len(sa)} | {len(sb)} | {mean(sa, 'brightness'):.1f}->{mean(sb, 'brightness'):.1f} | "
                     f"{mean(sa, 'saturation'):.3f}->{mean(sb, 'saturation'):.3f} | "
                     f"{mean(sa, 'sharpness'):.0f}->{mean(sb, 'sharpness'):.0f} | {bad(sa)}->{bad(sb)} |")
    lines += ["", "## 需要人工看的", ""]
    for r in sorted(paired, key=lambda r: r["ssim"]):
        if r["verdict"] in ("close, look", "different, review"):
            lines.append(f"- {r['model']} / {r['prompt_id']} / seed {r['seed']}: SSIM {r['ssim']:.3f}, "
                         f"PSNR {r['psnr']:.1f} dB ({r['verdict']})")
    (out / "report.md").write_text("\n".join(lines) + "\n")

    def img_tag(label, rec):
        return f'<img src="../../baselines/{label}/{rec["file"]}" loading="lazy">'
    cells = []
    for r in sorted(paired, key=lambda r: (r["model"], r["prompt_id"], r["seed"])):
        diff = f'<img src="{r["diff_file"]}" loading="lazy">' if r.get("diff_file") else "<p>identical</p>"
        cells.append(f"<tr><td>{html.escape(r['model'])}<br>{r['prompt_id']}<br>seed {r['seed']}<br>"
                     f"SSIM {r['ssim']:.3f}<br>{r['verdict']}</td><td>{img_tag(args.a, r['a'])}</td>"
                     f"<td>{img_tag(args.b, r['b'])}</td><td>{diff}</td></tr>")
    style = ("<style>body{font-family:sans-serif}img{width:300px}td{vertical-align:top;padding:4px}"
             "table{border-collapse:collapse}tr{border-bottom:1px solid #ccc}</style>")
    (out / "side_by_side.html").write_text(
        f"<meta charset=utf-8>{style}<h1>{args.a} | {args.b} | 差异（放大 4 倍）</h1><table>{''.join(cells)}</table>")

    rnd = random.Random(args.seed)
    blind, answer = [], {}
    for i, r in enumerate(p for p in paired if not p["identical"]):
        left_is_a = rnd.random() < 0.5
        lft, rgt = (r["a"], r["b"]) if left_is_a else (r["b"], r["a"])
        llab, rlab = (args.a, args.b) if left_is_a else (args.b, args.a)
        answer[f"Q{i + 1}"] = {"left": llab, "right": rlab, "model": r["model"], "prompt_id": r["prompt_id"]}
        blind.append(f"<h3>Q{i + 1}（左好 / 右好 / 看不出差别）</h3>{img_tag(llab, lft)} {img_tag(rlab, rgt)}")
    (out / "blind.html").write_text(f"<meta charset=utf-8>{style}<h1>盲评：只看画面，不看模型名</h1>{''.join(blind)}")
    (out / "blind_key.json").write_text(json.dumps(answer, ensure_ascii=False, indent=1))
    print(f"{len(paired)} pairs, {sum(r['identical'] for r in paired)} identical; "
          f"{sum(len(g['a']) + len(g['b']) for g in unpaired.values())} unpaired images; report {out / 'report.md'}")


if __name__ == "__main__":
    main()

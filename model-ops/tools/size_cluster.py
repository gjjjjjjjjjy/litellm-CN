#!/usr/bin/env python3
"""How many servers do the migrating models need on C500 vs C600?  Memory-fit sizing, one replica each.

Big LLMs: weights must fit in `weight_share` of the instance's usable memory
(usable per card = HBM x mem_util - overhead), the rest is KV cache / activations; sizes go 1/2/4/8 cards,
then whole servers. Small models use the instance size MetaX has validated (vllm-omni-metax deploy files,
LightX2V metax configs) where one exists. Small instances are packed onto shared servers.

This is a floor for "same replicas as today". Throughput is a separate question: compare per-replica
bandwidth / compute (printed at the end), then scale replicas by measured QPS from Gitee.AI's 压测.

  python3 tools/size_cluster.py
  python3 tools/size_cluster.py --weight-share 0.8
Sources for every number: C600_MIGRATION.md.
"""
import argparse
import math

CARDS = {
    "C500": {"hbm_gb": 64, "per_server": 8},
    "C600": {"hbm_gb": 144, "per_server": 8},
}

# weights in GB (HF safetensors totals). int8 = MetaX W8A8 (maca-llm-quantizer), same footprint as FP8.
BIG = {
    "Qwen3.8-Max (2.4T-A95B)": {"bf16": 4892, "fp8": 2496, "int8": 2496},
    "GLM-5.3 (753B)": {"bf16": 1507, "fp8": 756, "int8": 756},
}

# cards per instance; numbers marked * are MetaX-validated layouts, others computed
SMALL = {
    "Qwen3.8-27B":            {"C500": 2, "C600": 1, "why": "BF16 55.6 GB: C500 TP2 / C600 1 card"},
    "Qwen3-Omni (语音输出)":   {"C500": 3, "C600": 2, "why": "*C500 thinker TP2 + talker 1 (vllm-omni-metax yaml); C600 thinker 1 + talker 1"},
    "Qwen-Image-2.1":         {"C500": 1, "C600": 1, "why": "33 GB, one card"},
    "MiniMax-H3 FL2VA":       {"C500": 2, "C600": 1, "why": "*C500 TP2 + layerwise offload (vllm-omni-metax); C600 ~102 GB with AdaLN cache"},
    "MiniMax-H3 Ref2VA":      {"C500": 2, "C600": 1, "why": "served as a separate instance (port 8092)"},
}


def big_cards(gb, card, mem_util, overhead, share):
    usable = card["hbm_gb"] * mem_util - overhead
    need = gb / share / usable
    for n in (1, 2, 4, 8):
        if need <= n:
            return n
    return math.ceil(need / card["per_server"]) * card["per_server"]


def plan(card_name, prec, a):
    card = CARDS[card_name]
    per = card["per_server"]
    rows, big_servers, small_cards = [], 0, 0
    for name, w in BIG.items():
        p = prec[name]
        n = big_cards(w[p], card, a.mem_util, a.overhead_gb, a.weight_share)
        rows.append((name, f"{p} {w[p]:.0f} GB", n))
        if n >= per:
            big_servers += n // per
        else:
            small_cards += n
    for name, s in SMALL.items():
        rows.append((name, s["why"], s[card_name]))
        small_cards += s[card_name]
    return rows, big_servers + math.ceil(small_cards / per), big_servers, small_cards


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mem-util", type=float, default=0.90)
    ap.add_argument("--overhead-gb", type=float, default=4.0, help="per-card runtime + activations")
    ap.add_argument("--weight-share", type=float, default=0.75, help="max share of usable memory for weights")
    ap.add_argument("--current-c500", type=int, default=20, help="C500 servers these models use today")
    a = ap.parse_args()

    max_, glm = list(BIG)
    scenarios = [
        ("C500 现状推测 A：两个大模型都用沐曦 INT8 W8A8", "C500", {max_: "int8", glm: "int8"}),
        ("C500 现状推测 B：Qwen3.8-Max INT8，GLM-5.3 BF16", "C500", {max_: "int8", glm: "bf16"}),
        ("C600：官方 FP8 或沐曦 INT8（显存一样）", "C600", {max_: "fp8", glm: "fp8"}),
        ("C600：全 BF16（保守，不量化）", "C600", {max_: "bf16", glm: "bf16"}),
    ]
    print("一、显存下限：每个模型 1 个实例、不做 PD 分离、不留冗余")
    print(f"   规则：大模型权重 ≤ 可用显存的 {a.weight_share:.0%}（可用 = HBM × {a.mem_util} − {a.overhead_gb} GB/卡）\n")
    for title, card, prec in scenarios:
        rows, servers, bs, sc = plan(card, prec, a)
        print(f"== {title}\n   → {servers} 台（大模型整台 {bs} 台 + 小模型 {sc} 卡拼 {math.ceil(sc / 8)} 台）")
        for name, info, n in rows:
            print(f"   {name:24} {n:3d} 卡   {info}")
        print()

    # MetaX's own minimum-deployment table (gitee.com/metax-maca/llm-dist-inference-guide, SGLang PD, W8A8,
    # 8 GPUs/node): GLM-5.x 6 -> 3, Kimi-K2.6 8 -> 4, DeepSeek-V4-Pro 10 -> 5 going C500/C550 -> C588/C600.
    small_c500 = math.ceil(sum(s["C500"] for s in SMALL.values()) / 8)
    small_c600 = math.ceil(sum(s["C600"] for s in SMALL.values()) / 8)
    big_c500 = a.current_c500 - small_c500
    big_c600 = math.ceil(big_c500 / 2)
    print("二、按现有容量折算（沐曦官方最小部署表：大模型从 C500/C550 换到 C600，台数减半）")
    print(f"   现有 {a.current_c500} 台 C500 = 小模型约 {small_c500} 台 + 大模型 {big_c500} 台")
    print(f"   → C600：大模型 {big_c500} ÷ 2 = {big_c600} 台 + 小模型 {small_c600} 台 = {big_c600 + small_c600} 台")


if __name__ == "__main__":
    main()

# C500 → C600 迁移评估

2026-10-23。范围：GLM-5.3、Qwen3.8-Max、Qwen3.8-27B、Qwen-Image-2.1、Qwen3-Omni-30B-A3B-Instruct、MiniMax-H3。
DeepSeek V4 Flash 在宁夏 C500 6 节点，不在这次搬迁范围内，不计入。

## 结论

> **10-23 下午补充，台数前提待确认。** 模力方舟「沐曦 Token 资源包」（1492）的接口数据显示，`qwen3.8-max` 和 `qwen3.8-max-0902` 只走阿里百炼，不在沐曦算力上；GLM-5.3 是沐曦加百炼加 ztzn 三路，DeepSeek-V4-Flash 是百炼加 ztzn。如果 20 台 C500 上其实没有 Qwen3.8 Max，下面「18 台大模型 ÷ 2」的拆分就要重算。Qwen3.8 Max 若是计划在 C600 上新部署，要按新增容量另算（显存下限约 4 台）。数据见 `state/moark_pkg1492.json`

1. **可以直接迁到 C600，但精度不要跟着一起换。** 第一步沿用 C500 上的 INT8 W8A8（小模型用 BF16），
   先把「换卡」和「换精度」两件事拆开。按模型分批迁移，每批先在 1 台 C600 上过测试，C500 留作回滚。
   官方 FP8 权重等沐曦软件栈明确支持后，作为第二步优化。
2. **20 台 C500 → C600 约 10 台**（每台 8 卡）。最少 7 台能放下全部模型，但只有一份副本、没有余量。
   10 台是按现在的容量折算的规划数。需要拿现网每个模型的实际分配校准（见文末「要确认的」）。

## 一、能不能直接迁到 C600

### 支持直接迁的理由

- **同一条软件线。** MACA 同一版本号同时支持 C500 系列和 C600 系列，只是固件分开
  （C500 系 VBIOS 1.35.6.0，C600 系 VBIOS 2.3.7.0）[14]。vLLM-metax 0.28 有 C500、C600 两套镜像 [19][39]。
- **大模型已有沐曦 INT8 权重和 C600 支持记录。**
  - GLM-5.3：`metax-tech/GLM-5.3-W8A8`（756 GB，2026-09-02）[40]。GLM-5.x 在沐曦部署表里有 C600 档 [20]，
    GLM-5.1-W8A8 列在 C600 应用发布说明里 [15]。
  - Qwen3.8-Max：沐曦 INT8 版是 `FlagRelease/Qwen3.8-2.4T-A95B-INT8-metax-FlagOS`（2026-08-09）[41]。
    它走的是 FlagOS（vllm-plugin-FL + vLLM 0.24 + MACA 3.7），不是 vLLM-metax。
  - Qwen3.8-27B：`metax-tech/Qwen3.8-27B-W8A8`（36.4 GB，2026-08-25）[40]。
- **台数省一半。** 沐曦自己的最小部署表里，大模型从 C500/C550 换到 C600，台数都减半 [20]（见第二节）。

### 不要一步到位用 FP8 的理由

- C600 硬件有原生 FP8 Tensor 指令（XCORE 1.5），C500 没有 [10][11]。
- **但公开软件栈还没准备好：**
  - vLLM-metax 的 FP8 默认关闭，要设 `VLLM_METAX_SUPPORTS_FP8=1` 才打开，否则直接报 "FP8 is not supported" [38]。
  - mcBLAS 的数据类型枚举里没有 FP8 [18]。
  - 推理手册写的是「不支持 FP8 类型 KV Cache 和相关 FP8 模型」[17]（手册可能没跟上新版本）。
  - 沐曦发布的大模型权重全是 INT8 W8A8（compressed-tensors，int-quantized）[21][40]。
- 所以 FP8 要等沐曦确认 C600 上的 FP8 W8A8 路径可用，再拿官方 FP8 权重和 INT8 做精度、速度对比。
- **对台数没影响：** INT8 和 FP8 权重一样大，台数测算按 INT8 算。

### 风险，迁移前要逐条确认

| 风险 | 说明 | 谁确认 |
|---|---|---|
| C600 卡间互连比 C500/C550 慢 | 官方原话：「受限于工艺制程，曦云 C600 系列的卡间互连带宽略有下降，同时功耗有所提升」[10]。大 TP / EP 的通信会更慢，Qwen3.8-Max 这种跨 4 台的实例影响最大 | 迁移后实测 |
| 功耗 1000 W/卡 | C500 是 350 W [1]，C600 最大 1000 W，风冷或液冷 [4][8]。机房供电和散热要提前准备 | Gitee.AI / 机房 |
| 模力方舟侧只有 C500 的文档 | 模力方舟算力文档只写了 C500 实例，内置模型库 `/mnt/moark-models` 只挂在 C500 上 [36]。C600 的实例、镜像、模型挂载要 Gitee.AI 准备 | Gitee.AI |
| Qwen3.8-Max 的沐曦参考部署还很初级 | FlagOS 版用 `--enforce-eager`、关了前缀缓存、上下文 32K，精度评测还写着「Evaluating」[41]。没有 C600 的部署记录 | 我们 + 框架组 |
| 小模型的沐曦方案只在 C500 上验证过 | Omni（3 卡）和 H3（每个变体 2 卡）的 vllm-omni-metax 配置只在 C500 上验证过 [42]，且停在 0.26 版。Qwen-Image-2.1 的 Day-0 镜像支持 C500 和 C600，要求 MACA ≥ 3.9，2026-11-20 到期 [43] | 我们 |
| C600 已知问题 | vllm-metax 在 C600 上「不支持模型 FP16 测试」[15]（BF16 不受影响） | — |

### 建议顺序

1. **小模型先迁**（Qwen3.8-27B、Qwen-Image-2.1、Omni、H3 合计 1 台 C600）：风险低，顺带把 C600 的镜像、驱动、模型挂载跑通。
2. **GLM-5.3**：有沐曦 W8A8 权重，也有官方 C600 部署档（PD 1P1 + 1D2 = 3 台）[20]。
3. **Qwen3.8-Max 最后迁**：跨台最多，受互连变慢影响最大，参考部署也最初级。

每个模型都按同一个流程走：

1. 在 1 台 C600 上起实例。
2. 跑 `tools/smoke_test.py`，再拿同一组提示词和现网 C500 的返回逐条对比。
3. Gitee.AI 压测。
4. 切流量。
5. C500 保留一周再回收。

## 二、要多少台 C600

### 依据：C600 每卡大约是 C500 的两倍

| | C500 | C600 | 来源 |
|---|---|---|---|
| 显存 | 64 GB HBM2e | 144 GB HBM3e（2.25 倍） | [1][13][25] |
| 显存带宽 | ~1.8 TB/s（第三方） | 3.35–3.6 TB/s（媒体，非官方） | [29][30][31] |
| FP16/BF16 | 240 TFLOPS（第三方） | 官方只说「加倍 FP16/BF16 tensor 矩阵运算算力」 | [10][29] |
| FP8 | 无 | 原生 | [10] |
| 卡间互连 | MetaXLink | 比 C500/C550「略有下降」 | [10] |
| 每台 | 8 卡 | 8 卡 OAM | [5][8][20] |

台数减半后，总显存还多 12%，总带宽和总算力大致持平，所以同样的流量用一半的台数撑得住。
唯一变差的是卡间互连。

### 沐曦官方最小部署表（SGLang，PD 分离，W8A8，每台 8 卡）[20]

| 模型 | C500/C550 | C600 |
|---|---|---|
| GLM-5 / 5.1 / 5.2 | 6 台（1P2 + 1D4） | 3 台（1P1 + 1D2） |
| Kimi-K2.5 / K2.6 | 8 台（1P4 + 1D4） | 4 台（1P2 + 1D2） |
| DeepSeek-V4-Pro | 10 台（1P2 + 1D8） | 5 台（1P1 + 1D4） |

`1P2` 表示一个 Prefill 实例占 2 台。GLM-5.3 和 GLM-5.2 结构、参数量相同（都是 753B，`GlmMoeDsaForCausalLM`），可以直接套用。

### 算法 A：按现有容量折算（规划数）

现有 20 台 C500 里，小模型合计 10 卡，约占 2 台，其余 18 台是两个大模型。

| | C500（现有） | C600 |
|---|---|---|
| GLM-5.3 + Qwen3.8-Max | 18 台 | 18 ÷ 2 = **9 台** |
| Qwen3.8-27B | 2 卡（BF16 TP2） | 1 卡 |
| Qwen3-Omni（带语音输出） | 3 卡（thinker TP2 + talker 1，沐曦已验证 [42]） | 2 卡 |
| Qwen-Image-2.1 | 1 卡 | 1 卡 |
| MiniMax-H3（FL2VA、Ref2VA 各一份） | 2 + 2 卡（TP2，沐曦已验证 [42]） | 1 + 1 卡 |
| 小模型合计 | 10 卡 ≈ 2 台 | 6 卡 = **1 台** |
| **合计** | **20 台** | **10 台** |

**18 台的拆分不影响结果。** 比如 GLM-5.3 按官方 PD 档 6 台、Qwen3.8-Max 12 台，
折到 C600 就是 3 台 + 6 台，合计还是 9 台。
Qwen3.8-Max 6 台的可行性：可以拆成 1P3 + 1D3，每个实例 3 台，权重占显存 72%。
它只有 23 层全注意力，而且只有 4 个 KV 头，KV cache 很小，剩下 28% 的显存够用。

### 算法 B：显存下限（每个模型只有一份，不做 PD 分离，不留冗余）

规则：权重不超过可用显存的 75%（可用显存 = HBM × 0.9 − 4 GB/卡）。运行 `python3 tools/size_cluster.py` 可复现。

| 模型 | 权重 | C500 | C600 |
|---|---|---|---|
| Qwen3.8-Max | INT8 2496 GB | 64 卡 = 8 台（与沐曦 FlagOS 参考部署 TP16 × PP4 = 64 卡一致 [41]） | 32 卡 = 4 台 |
| GLM-5.3 | INT8 756 GB | 24 卡 = 3 台 | 16 卡 = 2 台 |
| 小模型 | — | 10 卡 = 2 台 | 6 卡 = 1 台 |
| **合计** | | **13 台** | **7 台** |

C600 全用 BF16、不量化（保守情况）：10 台。

### 结论

**规划按 10 台 C600 报，7 台是放得下的最少台数，不建议按这个数采购。**
C500 现在用了 20 台，而显存下限只要 13 台，差出来的部分是现网的 PD 分离和冗余。
按 7 台搬过去，等于把这部分余量全部去掉。

## 要确认的（会改变台数）

1. **现网 20 台各分给了谁。** 每个模型几台、几个副本、是否 PD 分离、什么精度（INT8 / BF16）、什么框架。
   有了这份清单可以把 10 台算准，误差大约 ±2 台。
2. **「C500」具体指 C500（PCIe）还是 C550（OAM）。** 官方 C500 是 PCIe 卡，2 卡或 4 卡互连；8 卡全互连的是 C550 [1][2]。
   两者在沐曦部署表里是同一档，台数不受影响，但影响和 C600 的互连对比。
3. **流量会不会涨。** 以上都是「容量不变」。如果要扩容，按 Gitee.AI 压测得到的单实例 QPS 加副本。
4. **Omni 要不要语音输出。** 只出文本的话，C500 上少 1 卡，C600 上少 1 卡。
5. **H3 两个变体是不是都要上。** 只上 FL2VA 的话，每种卡各少 1–2 卡。

以上 5 条都不改变结论的量级：C600 在 9–12 台之间，规划数 10 台。

## 数据来源

编号沿用调研记录。[1]–[37] 来自 C500 / C600 规格调研，[38] 起为本文补充。

- [1] C500 产品页 https://www.metax-tech.com/prod.html?cid=107&id=21
- [2] C550 https://www.metax-tech.com/prod.html?cid=107&id=35
- [4] C600 https://www.metax-tech.com/prod.html?cid=107&id=68
- [5] C500 服务器 https://www.metax-tech.com/prod.html?cid=110&id=37
- [8] C600 服务器 https://www.metax-tech.com/prod.html?cid=110&id=71
- [10] 上交所问询回复（2025-08）https://static.sse.com.cn/stock/disclosure/announcement/c/202508/002078_20250827_OO1E.pdf
- [11] 招股书（2025-12-11）https://stockmc.xueqiu.com/202512/688802_20251211_82K6.pdf
- [12] 2026 半年报 https://dataclouds.cninfo.com.cn/shgonggao/hsomarket/2026/20260830/3e37ba6a9801412f8400718faea88997.PDF
- [13] 东海证券研报（2026-06-12）https://pdf.dfcfw.com/pdf/H3_AP202606121823512802_1.pdf
- [14] MXMACA 发布说明 https://developer.metax-tech.com/api/client/document/preview/1419/index.html
- [15] AI-C600 应用发布说明 https://developer.metax-tech.com/api/client/document/preview/1220/index.html
- [17] 推理手册 vLLM-metax 章 https://developer.metax-tech.com/api/client/document/preview/1360/split_files/macart_vllm_metax.html
- [18] mcBLAS API https://developer.metax-tech.com/api/client/document/preview/1446/index.html
- [19] vllm-metax 0.28.0 发布说明 https://vllm-metax.readthedocs.io/en/latest/release/0.28.0/index.html
- [20] 沐曦 PD 分布式推理部署指南（最小部署表，每节点 8 卡）https://gitee.com/metax-maca/llm-dist-inference-guide
- [21] 沐曦 W8A8 权重格式示例 https://modelscope.cn/models/metax-tech/DeepSeek-V4-Pro-W8A8
- [25] 上证报（2025-07-29，显存 64 GB → 144 GB）https://finance.sina.com.cn/stock/relnews/cn/2025-07-29/doc-infiaksk9725970.shtml
- [29] CSDN C500 规格表（第三方）https://blog.csdn.net/qq_23934063/article/details/132473834
- [30] mirrorfrog（聚合站）https://mirrorfrog.com/docs/cards/others/metax-c600/
- [31] 东方财富股吧（2025-08-24）https://caifuhao.eastmoney.com/news/20250824025550377224840
- [36] 模力方舟沐曦算力文档 https://moark.com/docs/compute/clusters_gpu/mx_gpu
- [38] vLLM-metax `platform.py` / `envs.py`（FP8 开关）https://github.com/MetaX-MACA/vLLM-metax/blob/master/vllm_metax/envs.py
- [39] 沐曦开发者社区镜像目录 https://developer.metax-tech.com/softnova/docker
- [40] ModelScope `metax-tech/GLM-5.3-W8A8`、`metax-tech/Qwen3.8-27B-W8A8`（API 实查，2026-10-23）
- [41] `FlagRelease/Qwen3.8-2.4T-A95B-INT8-metax-FlagOS` 模型卡 https://huggingface.co/FlagRelease/Qwen3.8-2.4T-A95B-INT8-metax-FlagOS
- [42] vllm-omni-metax（Omni deploy yaml、H3 测试说明）https://github.com/MetaX-MACA/vllm-omni-metax
- [43] 沐曦 Day-0 镜像页 https://developer.metax-tech.com/softnova/Day0

# Qwen3.8-Max（开源名 Qwen3.8-2.4T-A95B）

更新：2026-10-23。只为 C500 → C600 搬迁建卡，详细测算见 `../C600_MIGRATION.md`。

## 先分清两个东西

HF 模型卡原话：**Qwen3.8-Max 是基于 Qwen3.8-2.4T-A95B 的官方版本**，多了图片输入、非思考模式、默认 1M 上下文、内置工具。
开源权重只有文本输入，**而且只能思考，不能关**。如果模力方舟的 `qwen3.8-max` 是自部署的开源权重，就没有图片输入和非思考模式。
要和 Gitee.AI 确认它对外宣称的能力和实际部署是否一致。

## 模型源

| 项 | 值 |
|---|---|
| HF BF16 | `Qwen/Qwen3.8-2.4T-A95B` @ `207bd685a7`（2026-08-12），**4892 GB** |
| HF FP8 | `Qwen/Qwen3.8-2.4T-A95B-FP8`（2496 GB） |
| **沐曦 INT8** | `FlagRelease/Qwen3.8-2.4T-A95B-INT8-metax-FlagOS`（2026-08-09），ModelScope 同名 |
| 许可证 | `license_name: qwen3.8-max`（自定义；FlagRelease 卡片写 Apache-2.0，以原仓库为准，待核） |
| 模力方舟 | 公开 `/v1/models` 列了 `qwen3.8-max`；**我们现在的 key 调不了**（「您绑定的资源包不支持当前模型或算力」） |

## 结构

- `Qwen3_5MoeForCausalLM`：92 层 = 69 层 Gated DeltaNet 线性注意力 + 23 层全注意力（3:1）；512 专家选 10 + 1 共享；MTP
- 上下文 262K，可扩到约 1M
- KV cache 很小：全注意力只有 23 层 × 4 个 KV 头 × 256 维 ≈ 94 KB/token；线性注意力每个请求另有约 0.3–0.6 GB 固定状态
- 迁移风险：GDN 线性注意力 kernel（和 Qwen3.8-27B 同一套）+ 512 专家的 MoE / EP 通信。C600 卡间互连比 C500 慢，这个模型受影响最大

## 沐曦部署

- 沐曦参考部署：FlagOS 镜像 `harbor.baai.ac.cn/flagrelease-public/qwen3.8-2.4t-metax001-gems5.4.0-...-vllm0.24.0-cp312-pt28-maca37-x64-3.8.1:202608121009`，
  `vllm serve` **TP16 × PP4 = 64 卡 = 8 台**，ray 后端，`--enforce-eager`、关前缀缓存、`--max-model-len 32768`
- 这是 Day-0 的跑通配置，不是生产配置：精度评测还写着「Evaluating」，没开 CUDA graph 和前缀缓存
- 不在沐曦官方 PD 部署表里；沐曦自己的文档只列到 Qwen3.6
- C600：显存下限 4 台（32 卡，权重占 54%），按 C500 台数减半折算约 6 台（1P3 + 1D3）

## 待办

- [ ] 要一把能调 `qwen3.8-max` 的 key，跑 smoke_test
- [ ] 确认现网部署：FlagOS 还是 vLLM-metax、几台、几个副本、是否 PD
- [ ] 确认对外宣称的能力（图片输入、非思考）和开源权重的差别
- [ ] C600 上最后迁；重点测跨台 EP / PP 的吞吐

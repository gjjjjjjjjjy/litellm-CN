# GLM-5.3（753B MoE，文本）

更新：2026-10-23。只为 C500 → C600 搬迁建卡，详细测算见 `../C600_MIGRATION.md`。

## 模型源

| 项 | 值 |
|---|---|
| HF 主仓库 | `zai-org/GLM-5.3` @ `ba32f8c19c`（**2026-10-14 更新过**）——注意主仓库现在就是 **FP8**（756 GB，`quant_method: fp8`） |
| HF BF16 | `zai-org/GLM-5.3-BF16`（1507 GB） |
| **沐曦 W8A8** | ModelScope `metax-tech/GLM-5.3-W8A8`（755.9 GB，2026-09-02）—— **C500 / C600 上用这个** |
| 同系列 | `GLM-5.3-Flash`（另一个更小的模型，`glm5_next` 架构，不是同一个） |
| 模力方舟 | 已上架 `GLM-5.3` |

10-14 那次主仓库更新要查清改了什么（权重、配置还是 chat template）：沐曦的 W8A8 是 09-02 做的，如果上游改了权重或模板，W8A8 可能要重做。
讨论区最新一帖就是 chat template 的改动（#31，工具结果校验和重排）。

## 结构

- `GlmMoeDsaForCausalLM`：78 层，256 专家选 8 + 1 个共享专家；**MLA**（kv_lora_rank 512）+ **DSA 稀疏注意力**（indexer top-k 2048）；1 层 MTP；上下文 1M
- KV cache 约 100 KB/token（MLA 潜向量 + DSA indexer key），很小
- 迁移风险在 DSA：沐曦 SGLang 分支有提交写明 C550 上 TileLang sparse-MLA kernel 不支持 FP8 输入，要反量化成 BF16（MetaX-MACA/sglang commit 9e48619）

## 沐曦部署

- 官方最小部署（SGLang，PD 分离，W8A8，每台 8 卡）：**C500/C550 6 台（1P2 + 1D4），C600 3 台（1P1 + 1D2）**。
  表里写的是 GLM-5 / 5.1 / 5.2，5.3 结构和参数量与 5.2 一样（gitee.com/metax-maca/llm-dist-inference-guide）
- GLM-5.2-W8A8 进了 vllm-metax 3.8.0.103；GLM-5.1-W8A8 列在 C600 应用发布说明里

## 部署后测试（2026-10-23，模力方舟 `GLM-5.3`）

5 项过 4：基础 / 流式（首字 0.55 s，34.6 tok/s）/ 工具调用通过，会返回 `reasoning_content`；
**`response_format: json_schema` 被静默忽略**（返回 Markdown 列表）。

## 待办

- [ ] 查 10-14 主仓库更新内容，判断沐曦 W8A8 要不要重做
- [ ] 确认现网用的是 W8A8 还是 BF16、SGLang 还是 vLLM、是否 PD 分离、几台
- [ ] C600 上按 1P1 + 1D2 起，和现网逐条对比

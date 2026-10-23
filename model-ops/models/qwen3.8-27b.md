# Qwen3.8-27B（VLM）

更新：2026-10-23。

## 模型源

| 项 | 值 |
|---|---|
| HF | `Qwen/Qwen3.8-27B` @ `1d4bf0f2ff`（2026-08-14），BF16 55.6 GB，Apache-2.0 |
| 官方 FP8 | `Qwen/Qwen3.8-27B-FP8`（30.9 GB，block-wise FP8 E4M3 `[128,128]`，动态激活；视觉塔 / lm_head / embedding / GDN 小参数保持 BF16） |
| ModelScope | `Qwen/Qwen3.8-27B`、`Qwen/Qwen3.8-27B-FP8` 都可用 |
| 模力方舟 | 已上架 `qwen3.8-27b` |
| 社区量化 | INT4（RedHatAI W4A16、cyankiwi AWQ）、昇腾 INT8（Eco-Tech w8a8，ModelScope）、GGUF、NVFP4（NVIDIA 专用） |

## 结构（迁移风险在这里）

- 稠密 27.8B，文本 + 图片 + 视频输入，文本输出
- **64 层 = 16 × (3 层 Gated DeltaNet 线性注意力 + 1 层 Gated Attention)**，也就是 48 层线性注意力 + 16 层全注意力
- Gated DeltaNet 的递归状态是 fp32；全注意力是 GQA 24/4，head_dim 256，部分 RoPE + 交错 MRoPE，注意力输出带 swish 门
- 1 层 MTP 头（可做投机解码）
- 上下文 262K，YaRN 可扩到 1M
- 默认开思考；单请求关闭用 `chat_template_kwargs: {"enable_thinking": false}`；`reasoning_effort` 只认 xhigh / medium / low

## 权重

| 方案 | C500 64 GB | C600 | 条件 |
|---|---|---|---|
| BF16 | **2 卡 TP2**（单卡只剩约 6 GiB，低于 vLLM 建议的 67 GB 下限） | 1 卡 | 无 |
| 官方 FP8 | 1 卡 | 1 卡 | MACA 要有 block-128 FP8 W8A8 算子；C500 不支持原生 FP8 的话不选 |

**建议：C500 上 BF16 TP2；C600 上先用 BF16 单卡对齐精度，再测官方 FP8，两者结果对比后决定。**
FP8 的风险：vLLM 对没调过的卡用默认 block-FP8 kernel 配置（FP8 仓库讨论 #16），沐曦上要自己调；FP8 量化的 MTP 头可能让投机解码接受率降 3–4%（#13，有争议）。

## 框架

- **沐曦：vLLM-metax v0.28.0**（2026-10-12，对齐上游 v0.28.0；MACA 3.8.2，torch 2.10.0+metax，triton 3.6.0+metax），
  镜像 `cr.metax-tech.com/public-ai-release/maca/vllm-metax:0.28.0-maca.ai3.8.2.401-torch2.10-py310-ubuntu22.04-amd64`，C500 / C600 都有。
  - `qwen3_5` **不在**它的测试模型清单里，但 v0.25 / v0.26 发布说明修过 Qwen3.5 的加载；插件不覆盖 `Qwen3_5ForConditionalGeneration`，走上游实现。
    v0.28 自带 `flash-linear-attention 0.5.0+metax`、`causal_conv1d`、`mamba_ssm`（GDN 需要的就是这些）。沐曦说 Qwen3.5 的 GDN Triton kernel 在 MACA 上零修改跑通（metax-tech.com/ndetail/12563.html）。**没找到 Qwen3.8-27B 的 Day-0 公告**，要自己验。
  - **FP8 默认关**：要 `VLLM_METAX_SUPPORTS_FP8=1`，否则报 "FP8 is not supported"。沐曦自己的量化路线是 BF16 → INT8 W8A8（maca-llm-quantizer，支持 Qwen3.5 / 3.6 结构）。
- 上游 vLLM：架构最低 0.17.0，但 v0.27.1 加载 FP8 仓库时只认文本、不认多模态（讨论 #146）。上游当前 v0.32.0（10-18），vLLM-metax 落后约 4 个小版本。
- 推荐启动参数（vLLM recipe，H200）：
  ```
  vllm serve Qwen/Qwen3.8-27B --tensor-parallel-size 1 --enable-auto-tool-choice \
    --tool-call-parser qwen3_coder --reasoning-parser qwen3 --mm-encoder-tp-mode data
  ```
  MTP：`--speculative-config '{"method":"mtp","num_speculative_tokens":3}'`
- **`--reasoning-parser qwen3` 必须开**（每轮回答都以 `<think>` 开头）；工具解析器用 `qwen3_coder`，不要用 hermes。
- 采样：思考模式 temp 1.0 / top_p 0.95 / top_k 20；非思考模式 temp 0.7 / top_p 0.8 / top_k 20 / presence 1.5。

## 迁移风险（最可能在 MACA 上出问题的算子）

1. Gated DeltaNet 的 chunked delta-rule 和 causal-conv1d：vLLM 用 Triton 实现 → MACA 上 Triton 能不能跑、精度对不对
2. 混合缓存管理（线性注意力状态 + KV cache 共存）
3. head_dim 256 的注意力 kernel
4. MTP 投机解码
5. 视觉塔（MRoPE）

精度对齐方法：同一组提示词（含图片、视频、长上下文、工具调用）在 NVIDIA 参考部署或官方 API 上跑一遍，和沐曦部署逐条比较。

## 已知问题（上游，跟踪是否修复）

- 对话中间出现 system 消息时模板报错 → HTTP 500，Agent 客户端会踩（讨论 #148，模板 08-13 后没改）
- `reasoning_effort="high"` 模板报错 → HTTP 500，Claude Code 经 `/v1/messages` 会发 "high"（#147，修复 PR 未合并）
- Claude Code 下工具调用仍有问题，只有社区模板能修（#68、#138、#216）
- 过度思考：SGLang 上出现 2 万–5.5 万 token 的思考循环（#178）
- 混合层前缀缓存块是 1584 token，5K 以下的提示词基本命中不了缓存（#169）

## 部署后测试（2026-10-23，模力方舟 `qwen3.8-27b`）

| 项 | 结果 |
|---|---|
| 列表 / 基础问答 / 流式 / 工具调用 / 看图读数字 | 通过；首字 0.31 s，33.8 tok/s |
| `response_format: json_schema` | **失败**：参数被接受，返回散文（静默忽略） |
| 思考内容 | 答「42」用了 52 个 completion token，但 `reasoning_content` 为空、content 以 `\n\n` 开头 → 思考内容可能被平台丢掉了。同时测的 GLM-5.3 会正常返回 `reasoning_content` |

结果：`results/2026-10-23_1409_qwen3.8-27b/result.json`

## 待办

- [ ] 反馈：json_schema 被忽略；reasoning_content 不返回（问是否故意关闭）
- [ ] 问 Gitee.AI 现网用的是 BF16 还是 FP8、什么框架版本、有没有开 MTP
- [ ] 在 C600 上起 BF16 单卡实例，跑 smoke_test + 精度对照

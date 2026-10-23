# Qwen3-Omni-30B-A3B-Instruct（全模态：文本 / 图片 / 音频 / 视频输入，文本 + 语音输出）

更新：2026-10-23。

## 模型源

| 项 | 值 |
|---|---|
| HF | `Qwen/Qwen3-Omni-30B-A3B-Instruct` @ `26291f7938`（2025-09-22，一年多没更新），BF16 70.5 GB |
| 同系列 | `-Thinking`（只有 thinker，输出文本，63.4 GB）、`-Captioner`（音频进、文本出，单轮，≤30 s） |
| 官方量化 | **没有**（FP8 需求帖 #22 无人回复）。社区：AWQ 4/8 bit（cyankiwi）、FP8（marksverdhei 等）、Intel int4 AutoRound、GGUF |
| ModelScope | 三个都可用；模型卡本身建议国内用 `modelscope download` |
| 模力方舟 | 未上架（现有 `Qwen3.8-Omni-Flash`，那是闭源 API 模型，不是同一个东西） |

## 结构

Thinker–Talker 结构，共 35.3B：
- **Thinker**（31.7B）：MoE 48 层，128 专家选 8，激活约 3B；GQA 32/4，head_dim 128；交错 MRoPE；
  外加音频编码器 AuT（0.65B）和视觉塔（0.54B）。上下文 65,536
- **Talker**（3.2B）：MoE 20 层 + 5 层 code predictor（16 个码本）+ Code2Wav（0.22B，滑窗 transformer + 反卷积上采样），出 24 kHz 语音
- Instruct 不思考；3 个音色 Ethan（默认）/ Chelsie / Aiden

## 权重

**BF16**（没有官方量化，社区量化在全模态模型上风险大，音频质量要单独验证）。

| 方案 | C500 64 GB | C600 |
|---|---|---|
| 只出文本（thinker） | 2 卡 TP2 | 1 卡 |
| 文本 + 语音（vLLM-Omni） | **3 卡**：thinker TP2 + talker / Code2Wav 一张 | 1–2 卡（thinker 一张 + talker 一张最稳） |

模型卡的显存表（Transformers，BF16）：15 s 视频 78.9 GB，60 s 107.7 GB，120 s 144.8 GB —— 长视频输入很吃显存。

## 框架

- **要语音输出只能用 vLLM-Omni**（≥ 0.18.0，当前 0.30.0）或 Transformers。普通 vLLM、SGLang 都只跑 thinker（只出文本）。
  ```
  vllm serve Qwen/Qwen3-Omni-30B-A3B-Instruct --omni --port 8091
  ```
  每个请求用 `"modalities": ["text"]` 或 `["text","audio"]` 选输出。
- vLLM-Omni 默认部署（2×H100 验证）：thinker 在第 0 卡（0.9 显存），talker 0.6 + Code2Wav 0.1 在第 1 卡。
  上游 vLLM-Omni 的平台清单里没有沐曦。
- **沐曦：vllm-omni-metax**（github.com/MetaX-MACA/vllm-omni-metax，基于 vllm-omni 0.26.0 + vllm-metax 0.26.0，最后提交 09-16），
  镜像 `vllm-omni-metax:0.26.0-maca.ai3.8.2.0-torch2.10-py312-ubuntu22.04-amd64`。
  它的 `deploy/qwen3_omni_moe.yaml` 已在 C500 上验证：**3 卡，thinker TP2 在 0、1 卡，talker + Code2Wav 在 2 卡**
  （原因写的是「MoE thinker 单张 MACA 卡放不下」）；**Code2Wav 必须 eager**（沐曦驱动的 CUDA graph 问题）。
- 只要文本输出：vLLM-metax 的测试清单里有 `Qwen3OmniMoeThinkerForConditionalGeneration`。
- ⚠️ HF 模型卡已过时：让装 `wangxiongts/vllm` 分支 + 0.9.2 wheel + `VLLM_USE_V1=0`，wheel 链接已 404。以 GitHub README 为准。
- Transformers ≥ 5.2.0（4.57 精度低）。

## 迁移风险

1. Fused MoE：vLLM-Omni 对 thinker 和 talker 都写死 `moe_backend: triton` → 依赖 MACA 上的 Triton
2. Code2Wav 的 `conv_transpose1d` 在 CUDA graph 捕获里有问题：ROCm 要 eager 跑；B200 + cuDNN 9.20 上低精度 Conv1d 有 bug，强制 FP32
3. vLLM 0.27 上 MRoPE 算子融合改变了音频输出 → 配置里加了 `custom_ops +rotary_embedding`
4. talker 种子固定为 42 防止音频退化
5. 音频质量没法用文本对比，要人耳听 + ASR 回写对比

## 已知问题

- 64 GB 卡上 vLLM 很难放下；在线 FP8 要求 BF16 先放得下；bitsandbytes 不支持（讨论 #17）
- TP2 并发请求 + json_schema 会胡编（#12，未解决）
- vLLM 和 SGLang 下 GPU 利用率都低（#27）
- vLLM 上工具调用没有指南，模板报错（#11）
- `use_audio_in_video` 在 `vllm serve` 下不可用，且多轮里每一轮都要设一样

## 部署后要测

- 文本问答、看图、**语音输入转写**、**语音输出**（`smoke_test.py` 的 audio_in / audio_out 两项；输出的音频会存下来，要人听）
- 视频输入（15 s / 60 s）显存和延迟
- 并发下 json_schema 是否胡编

## 待办

- [ ] 确认模力方舟要不要上语音输出（决定 vLLM-Omni 还是普通 vLLM、几张卡）
- [ ] 写沐曦的 vLLM-Omni deploy yaml（参考 NPU / MUSA 配置）
- [ ] C600 上起实例，跑 smoke_test

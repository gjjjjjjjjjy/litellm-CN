# MiniMax-H3（音视频联合生成）

更新：2026-10-23。注意：它不是语言模型，是 33B 的视频 DiT，一次生成带立体声音频的视频。

## 模型源

| 项 | 值 |
|---|---|
| HF | `MiniMaxAI/MiniMax-H3` @ `42ed227ee7`（2026-08-13），仓库 498 GB（去重后 354 GB） |
| ModelScope | **`MiniMax/MiniMax-H3`**（注意不是 `MiniMaxAI/`，后者 404） |
| 官方变体 | 只有 BF16。社区：Comfy-Org（int8 / 剪枝 BF16 / 剪枝 FP8）、unsloth FP8 / GGUF、lightx2v Turbo 4 / 8 步 LoRA |
| 模力方舟 | 已上架 `MiniMax-H3` |
| ⚠️ PyPI `minimax-h3` | **不是 MiniMax 官方的包**，是第三方 API 客户端，不要装 |

## 结构

| 组件 | 大小（BF16） | 说明 |
|---|---|---|
| DiT | 66.3 GB | 33B，其中约 13B 是 AdaLN 分支，可预计算缓存不加载 → 剪枝后 40.2 GB |
| 文本编码器 | 66.7 GB | 完整 Qwen3-VL-32B，只用到第 50 层 → 截断后 51.5 GB |
| 视频 VAE | 10.4 GB（FP32） | 自定义代码，纯 PyTorch SDPA，没有 triton / flash_attn 依赖 |
| 音频 VAE | 0.6 GB | 32 kHz |

- 两个任务 checkpoint：**FL2VA**（文生视频 + 首帧 / 尾帧 / 首尾帧生视频）、**Ref2VA**（最多 9 图 + 3 视频 + 3 音频参考）
- 输出：24 fps，32 kHz 立体声，4–15 s，短边默认 768；帧数为 17n+5；宽高 32 的倍数
- CFG 已蒸馏：不要负向提示词、不要 guidance_scale，每步一次前向。默认 50 步
- **没开源**：提示词改写 H3-Context-IR（官方「强烈建议」，只有 API）、2K 超分 H3-Regenerate-2K、稀疏注意力。
  所以本地部署只能出 768p，且是全注意力

## 部署哪些文件

基础文生视频 / 图生视频服务：**144 GB**（一个 DiT + 文本编码器 + 两个 VAE）。
- SGLang / vLLM-Omni 用原格式：`hf download MiniMaxAI/MiniMax-H3 --include "model_index.json" "FL2VA/*"`
- diffusers / LightX2V 用根目录的 `transformer` + `text_encoder` + `vae` + `audio_vae` + `tokenizer` + `processor` + 调度器
- 再加 Ref2VA：diffusers 格式 +66.3 GB
- 讨论 #77：有人发现 `FL2VA/transformer` 的 qkv 权重和根目录 `transformer/` 不一致，官方没回。**部署前自己比一下两份的 sha256**

## 权重

- **建议：BF16 + AdaLN 缓存（剪枝）**。精度不变，DiT 从 66 GB 降到 40 GB。
- FP8 只作用于 DiT（vLLM-Omni），在 C600 原生 FP8 确认后再考虑。
- 步数蒸馏（lightx2v Turbo 4 / 8 步）能把 15 s 视频从约 112 s 降到约 16.5 s（8×B300，vLLM-Omni 数据），但改变画质，上线前要业务方确认。

## 框架

| 框架 | 沐曦 | 说明 |
|---|---|---|
| **LightX2V** | ✅ 有沐曦脚本 | `scripts/platforms/metax/run_minimax_h3_t2av_tp_sp.sh`：8 卡 TP2 × Ulysses SP4，`metax_flash_attn2`，`use_adaln_cache: true`，文本编码器 TP，29 步，544×960，124 帧，torch.compile；另有单卡 block offload 版 |
| SGLang | 文档有 NVIDIA / AMD / 昇腾 | `sglang serve --model-path MiniMaxAI/MiniMax-H3 --num-gpus 4 --ulysses-degree 4 --model-variant fl2va`；接口 `POST /v1/videos` → 轮询 → `GET /content` |
| vLLM-Omni | 有 NVIDIA / ROCm 镜像 | **纯 Ulysses 会在每张卡上复制 66.3 GB DiT，64 GB 卡不能用**，要 TP、FP8 或 AdaLN 剪枝 |
| diffusers | 原生 PyTorch | ≥ v0.40.0，ModularPipeline；官方 requirements.txt 还指向旧分支，别照抄 |
| **vllm-omni-metax** | ✅ C500 已验证 | `tests/minimax_h3/README.md`：**2 卡 TP2 + 分布式逐层 offload + VAE tiling + `--enforce-eager`**；FL2VA、Ref2VA 分开起（8091 / 8092 端口）；要 `cache-dit==1.3.0`；**这一版不支持尾帧、首尾帧**（`frame_indices=[0,-1]`）。基于 vllm-omni 0.26 |

沐曦 2026-08-03 发过 H3 的 Day-0 适配公告（metax-tech.com/ndetail/12632.html）。

**建议：要 OpenAI 风格的服务接口用 vllm-omni-metax（模力方舟现网大概率是它，待确认）；要首尾帧或更快的出片，用 LightX2V 的沐曦脚本（8 卡 TP2 × SP4）。**

## 迁移风险

- 模型自带的 VAE 代码是纯 PyTorch，风险低。NVIDIA 专用的东西都在推理框架里（FA4、SageAttention、FlashInfer 等），
  LightX2V 沐曦配置已换成 `metax_flash_attn2`。
- 显存：C500 64 GB 单卡放不下（DiT 66 GB）。C500 上至少 TP2 拆 DiT；C600 单卡放得下剪枝 DiT + 截断文本编码器（约 102 GB），
  但为了延迟仍要多卡序列并行。

## 显存与卡数

| 卡 | 单实例（能跑） | 单实例（延迟可用） |
|---|---|---|
| C500 64 GB | 2 卡（TP2 + 逐层 offload，vllm-omni-metax 已验证；FL2VA、Ref2VA 各一份） | 8 卡（LightX2V 沐曦配置 TP2 × SP4） |
| C600 | 1 卡 | 4–8 卡 SP |

参考延迟（50 步，5 s 视频）：4×H200 74.4 s，8×昇腾 55.1 s，8×B300 19.0 s（SGLang cookbook）。

## 许可证

MiniMax H3 Community License（2026-08-02）：
- **地域：欧盟、英国、韩国、美国除外**；这些地区的用户要另外申请
- 商用允许，但年收入超过 2000 万美元要事先书面授权；**产品界面上要显著标出「MiniMax H3」**
- 托管服务要让用户受使用限制约束，并提供违规举报渠道；禁止用输出训练其他模型；生成内容要标注为机器生成

## 已知问题

开头约 0.5 s 语音乱码或被截断（讨论 #76）；768p 比 352–576p 更不听提示词（#65）；动漫风格实际只有 12 fps（#74）；
视频 VAE 偏色（#78）；ComfyUI 里完整 INT8 / BF16 不稳定、剪枝版正常（GitHub issue #85）。

## 部署后要测

- 模力方舟接口（10-23 从资源包数据查到）：异步 `v1/async/videos/generations`，三种操作「文生视频」「首尾帧生视频」「参考生视频」，参数有 `aspect_ratio`（默认 16:9）和 `seed`，¥0.5 一条；算力是壁仞加沐曦。提交后轮询 `urls.get`，结果在 `output.file_url`（和图片异步接口一样）
- 文生视频 / 首帧生视频各一条：时长、帧率、分辨率、有没有音轨、音画是否同步、开头 0.5 s 语音
- 界面上有没有「MiniMax H3」标识（许可证要求）

## 待办

- [ ] 问 Gitee.AI 视频接口
- [ ] 比对 `FL2VA/transformer` 和根目录 `transformer/` 的 qkv 权重
- [ ] 在 C600 上用 LightX2V 沐曦脚本起实例，量 5 s / 15 s 视频的延迟

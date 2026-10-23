# Qwen-Image-2.1（图片生成 + 编辑）

更新：2026-10-23。来源全部为当天抓取；原始文件在会话草稿目录，未入库。

## ⚠️ 先看许可证

**Qwen Research License：仅限非商用**（"FOR NON-COMMERCIAL PURPOSES ONLY"），商用要另找
model-business@notice.qwencloud.com 签授权；HF 讨论区有人反映这个邮箱退信或不回。Turbo、PE 两个配套模型同一许可证。
模力方舟如果是收费服务，**上线前要先确认商用授权**。—— https://huggingface.co/Qwen/Qwen-Image-2.1/raw/main/LICENSE ，讨论 #7

（FlagRelease 的沐曦版卡片写的是 Apache-2.0，但仓库里附的是 Qwen 原许可证文件，按 Qwen 许可证算。）

## 模型源

| 项 | 值 |
|---|---|
| HF | `Qwen/Qwen-Image-2.1` @ `d26bb61231`（2026-09-30），33.13 GB |
| ModelScope | `Qwen/Qwen-Image-2.1`（33.13 GB，可用） |
| 官方变体 | `-Turbo`（8 步，sigmas 写死在 model_index.json，改 `num_inference_steps` 无效）、`-PE-T2I` / `-PE-I2I`（提示词改写 LLM，各 18.84 GB，可选） |
| 沐曦专用 | `FlagRelease/Qwen-Image-2.1-BF16-metax-FlagOS`（FlagGems Triton 算子，MACA 3.8.1，torch 2.10） |
| 模力方舟 | 未上架（现有 `qwen-image-2.0`、`qwen-image-2.0-pro`） |

## 结构（决定显存和迁移风险）

- DiT 7.1B（BF16 14.2 GB），32 层单流，块因果注意力，文本和参考图的 KV 在各步之间复用（前缀缓存）
- 文本编码器 = Qwen3-VL-8B（17.5 GB），和原版逐张量一致
- VAE 0.34B（FP32 1.35 GB），RGBA 四通道
- 原生 2K：2048×2048、2752×1536 等；宽高必须是 32 的倍数
- 默认 40 步、CFG 关（`true_cfg_scale=1.0`）；带负向提示词才开 CFG，此时每步跑两次 DiT
- 任务：文生图；最多 10 张参考图的编辑；圈选 / 涂抹 / mask 局部编辑；原生透明底输出

## 权重

- **建议：BF16 原版。** 一张卡就放得下（SGLang 在 H200 上 1024² 峰值 38.4 GiB），不需要量化。
- 官方没有 FP8 / INT 版。社区有 FP8（unsloth）、int8_convrot（Comfy-Org）；文本编码器 FP8 约省 6 GB，DiT FP8 约省 2 GB，
  且速度不变（vLLM 实测），收益小。
- 要提速：考虑 Turbo（8 步）或 `lightx2v/Qwen-Image-2.1-Lightning`（4 步 LoRA，LightX2V 的沐曦脚本用的就是它）。
  步数蒸馏会改变出图质量，上线哪个版本要和业务方确认。

## 框架

| 框架 | 沐曦 | 说明 |
|---|---|---|
| **LightX2V** | ✅ 有沐曦脚本 | `scripts/platforms/metax/qwen_image_21_t2i.sh` / `_i2i.sh`；配置 `configs/platforms/metax/qwen_image_21_dmd_4step.json`：`metax_flash_attn2`、实数 RoPE、4 步 Lightning LoRA、CPU offload |
| FlagOS（FlagRelease） | ✅ 沐曦专用镜像 | MACA 3.8.1 |
| diffusers | 原生 PyTorch 可跑 | ≥ v0.41.0（10-06）；Turbo 要 git main（PR #14950）。默认 SDPA |
| SGLang Diffusion | 文档只写 NVIDIA | 首发支持，nightly |
| vLLM-Omni | 不支持 | 支持 PR #7759 已关闭，没合并 |
| **沐曦 Day-0 镜像** | ✅ | 2026-09-20 公告（metax-tech.com/ndetail/12659.html）；镜像 `public-init/qwenimage21:v1.0`：diffusers 0.41.0.dev0、torch 2.10、**MACA ≥ 3.9.0**、C500 / C600；**2026-11-20 到期**（developer.metax-tech.com/softnova/Day0） |
| 沐曦 diffusers 镜像 | 有，但没列 2.1 | `modelzoo.llm.diffusers:1.0.3-maca.ai3.9.0.12-torch2.8`，列了 Qwen-Image / 2512 / Edit 系列 |

**建议：用沐曦 Day-0 镜像起服务（11-20 前把镜像存到自己的仓库），LightX2V 沐曦脚本作为 4 步快速版的备选；用 diffusers 原版 40 步出图做画质对照。**

## 迁移风险

- **复数 RoPE**：昇腾上 diffusers 去噪报 `aclnnIndex` complex64 错误（QwenLM/Qwen-Image-2.1 issue #11）。
  LightX2V 的沐曦配置已改成实数 RoPE（`torch_real_rope`），这一点 MACA 上要验证。
- `flex_attention` 依赖 Triton 编译，不编译会退回 FP32 稠密注意力，高分辨率直接 OOM。不要用 `QwenImage21FlexAttnProcessor`。
- 编辑任务的耗时主要花在文本编码器上（约 30 s 文本编码器对 10 s DiT，issue #25），要测编辑延迟，不能只测文生图。

## 显存与卡数

| 卡 | 单实例 | 备注 |
|---|---|---|
| C500 64 GB | 1 卡 | 2K 分辨率峰值待实测 |
| C600 | 1 卡 | |

## 部署后要测

- 文生图 1024² 和 2048²：尺寸对、中文字能写对（`smoke_test.py` 会存图，需人工看）
- 编辑：单图、多参考图、透明底输出
- 参数：Gitee 接口上 `num_inference_steps` / `true_cfg_scale` 是否真的生效（vLLM-Omni 默认 50 步 + CFG 4.0，和官方默认 40 步 + CFG 1.0 不同）
- 已知画质问题：VAE 菱形格纹（讨论 #12）、同 seed 生成后再编辑会过饱和（#61）、手部变形（issue #12）

## 待办

- [ ] 确认商用授权
- [ ] 定上线版本：标准 40 步 / Turbo 8 步 / Lightning 4 步
- [ ] 拿 LightX2V 沐曦脚本在 C600 上起一个实例，跑 smoke_test

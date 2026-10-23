# 总表

更新：2026-10-23。✅ 完成　🟡 进行中 / 有问题　⬜ 未开始。「建议」是根据调研给出的，还没和现网核对。

| 模型 | 模力方舟 | 模型源（HF sha） | 权重（建议） | 框架（建议） | C500 → C600 卡数 | 部署后测试 | 反馈 |
|---|---|---|---|---|---|---|---|
| Qwen3.8-27B | ✅ `qwen3.8-27b` | `Qwen/Qwen3.8-27B` @ `1d4bf0f2ff` | BF16；沐曦 W8A8（`metax-tech/Qwen3.8-27B-W8A8`）备选 | vLLM-metax 0.28 | 2 → 1 | 🟡 10-23 6 项过 5 | ⬜ json_schema、reasoning_content |
| Qwen-Image-2.1 | ⬜ 未上 | `Qwen/Qwen-Image-2.1` @ `d26bb61231` | BF16 | 沐曦 Day-0 镜像（11-20 到期）/ LightX2V | 1 → 1 | ⬜ | ⚠️ 许可证仅限非商用 |
| Qwen3-Omni-30B-A3B-Instruct | ⬜ 未上 | `Qwen/Qwen3-Omni-30B-A3B-Instruct` @ `26291f7938` | BF16 | vllm-omni-metax 0.26（带语音） | 3 → 2 | ⬜ | — |
| MiniMax-H3 | ✅ `MiniMax-H3` | `MiniMaxAI/MiniMax-H3` @ `42ed227ee7` | BF16 + AdaLN 缓存 | vllm-omni-metax 0.26 / LightX2V | 2+2 → 1+1 | ⬜ 视频接口未知 | — |
| GLM-5.3 | ✅ `GLM-5.3` | `zai-org/GLM-5.3` @ `ba32f8c19c`（10-14 更新） | 沐曦 W8A8（`metax-tech/GLM-5.3-W8A8`） | SGLang PD（沐曦部署表） | 6 台 → 3 台 | 🟡 10-23 5 项过 4 | ⬜ json_schema |
| Qwen3.8-Max | ✅ `qwen3.8-max` | `Qwen/Qwen3.8-2.4T-A95B` @ `207bd685a7` | 沐曦 INT8（FlagOS） | FlagOS vLLM（TP16 × PP4） | ~12 台 → ~6 台（推测） | ⬜ key 无权限 | — |

C600 合计：约 10 台（规划数），最少 7 台。详见 `C600_MIGRATION.md`。

## 生图与音频（2026-10-23 起负责）

负责跟踪资源包 1492 里的生图模型、确保迁移过程无误，以及音频合成和图像、音频、视频的验收标准与方法。详见 `models/IMAGE_MODELS.md`、`models/AUDIO_MODELS.md`、`ACCEPTANCE.md`

| 事项 | 状态 |
|---|---|
| 资源包盘点（每个模型跑在哪家算力） | ✅ 10-23 基线：图像 29 个里 11 个用到沐曦，音频 17 个里 3 个，视频 16 个里 3 个 |
| 生图迁移基线 | 🟡 试采 4 张通过（同 seed 逐字节一致）；完整 256 张约 ¥14，待确认后采 |
| 生图对比工具 | ✅ `compare_images.py` 自测通过 |
| TTS 验收工具 | ✅ `audio_eval.py` 用免费 ASR 自测通过；IndexTTS-2 现网样本未采（¥2 一条） |
| 验收标准文档 | ✅ `ACCEPTANCE.md` 初稿，门槛为建议初值，待首次迁移校准 |
| 视频验收工具 | ⬜ 计划中（需要 ffmpeg） |

## 待办（按优先级）

- [ ] **确认迁移时间表和范围**：基线必须在迁移前采；只是 C500 换 C600，还是也包括把别家卡上的模型搬到沐曦
- [ ] **采生图完整基线**（约 ¥14），以及编辑类、RMBG-2.0、Real-ESRGAN 的基线
- [ ] **向 Gitee.AI 提：让 GiEngine 在 CPU 上生成初始噪声（或接受固定噪声）**，这样迁移前后同 seed 的图可以逐张对比；最好在采基线前改好（见 `ACCEPTANCE.md` 2.4）
- [ ] **qwen3.8-max 在资源包里只走阿里百炼**，不在沐曦上；向组长确认 20 台 C500 里到底有没有它（影响 C600 台数）
- [ ] **授权**：IndexTTS-2（年收入超 1 亿需另行授权）、Spark-TTS 和 ChatTTS（权重仅限非商用）

- [ ] **拿现网 20 台 C500 的分配清单**：每个模型几台、几个副本、精度、框架、是否 PD 分离。用来校准 C600 台数
- [ ] **Qwen-Image-2.1 商用授权**：Qwen Research License 仅限非商用，上模力方舟前要确认
- [ ] **Qwen-Image-2.1 沐曦 Day-0 镜像 11-20 到期**，到期前存到自己的镜像仓库
- [ ] 查 GLM-5.3 主仓库 10-14 的更新内容，判断沐曦 W8A8（09-02 做的）要不要重做
- [ ] 要一把能调 `qwen3.8-max` 的 key
- [ ] 问 Gitee.AI：C600 实例、镜像、模型挂载的准备情况；多家共用的模型能否指定算力或返回服务节点（MiniMax-H3 的视频接口已从资源包数据查到：`v1/async/videos/generations`，见 `models/minimax-h3.md`）
- [ ] 整理反馈单：json_schema 被静默忽略（qwen3.8-27b、GLM-5.3）；qwen3.8-27b 不返回 reasoning_content
- [ ] MiniMax-H3：比对 `FL2VA/transformer` 和根目录 `transformer/` 的 qkv 权重（讨论 #77）

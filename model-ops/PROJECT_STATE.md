# PROJECT_STATE — model-ops

## 是什么

跟进、维护模力方舟（Gitee.AI）上跑在沐曦卡上的模型，包括 C500 → C600 迁移。
我们负责：模型源、权重模式、推理框架、迁移适配、部署后测试、问题反馈、上游跟进。
Gitee.AI 负责：上线前压测、公网端口映射。

跟进对象：Qwen3.8-27B、Qwen-Image-2.1、Qwen3-Omni-30B-A3B-Instruct、MiniMax-H3，以及搬迁范围内的 GLM-5.3、Qwen3.8-Max。
DeepSeek V4 Flash 在宁夏 C500 6 节点，不在这次搬迁范围内。

## 当前状态（2026-10-23，第一天）

- 建了目录、登记表 `models.json`、三个脚本（`watch_upstream.py` / `smoke_test.py` / `size_cluster.py`）、6 张模型卡、总表、C600 迁移评估
- 上游基线已记录（`state/upstream.json`）
- 模力方舟实测：qwen3.8-27b 6 项过 5、GLM-5.3 5 项过 4，两者 json_schema 都被静默忽略；qwen3.8-max 当前 key 无权限
- C600 结论：可以直接迁，但先沿用 INT8 W8A8 不换精度；20 台 C500 → 约 10 台 C600（最少 7 台）

### 2026-10-23 下午：生图跟踪和验收标准

用户明确了分工：负责跟踪生图模型、确保迁移过程无误，以及思考音频合成和图像、音频、视频的验收标准与方法。范围是模力方舟「沐曦 Token 资源包」（package 1492，https://ai.gitee.com/serverless-api/packages/1492）

- 找到资源包页面背后的公开接口（`/api/pay/services/1492`、`/api/pay/service/operations?package_id=1492`），每个接口都标了实际算力。资源包共 209 个模型，但用到沐曦的只是一部分：图像 29 个里 11 个，音频 17 个里 3 个，视频 16 个里 3 个，其余在昇腾、燧原、壁仞、Gitee 自有卡、TeleAI、阿里百炼
- 我们这把 key 只能调沐曦算力上的服务（只在百炼、燧原上的模型都被拒），所以用它采的基线来自沐曦
- **qwen3.8-max 在资源包里只走百炼，不在沐曦上**，和 C600 迁移评估里「20 台 C500 包含 Qwen3.8 Max」的前提冲突，待确认
- 新增 `tools/moark_inventory.py`、`tools/image_baseline.py`、`tools/compare_images.py`、`tools/audio_eval.py`，`testsets/` 两个固定测试集，`ACCEPTANCE.md`，`models/IMAGE_MODELS.md`、`models/AUDIO_MODELS.md`
- 实测：Qwen-Image-2512 同 seed 两次输出逐字节相同（部署是确定性的）；服务端计算时间波动大（同请求 7.3 秒和 29.1 秒）；SenseVoiceSmall 免费、可作 TTS 验收的 ASR 判官
- 评测 venv：`metax/tools/evalenv`（numpy、Pillow、soundfile、pyloudnorm、cn2an），在仓库外
- 花费：试采 4 张图 ¥0.2，flux-1-schnell 探测 ¥0.01，whisper ¥0.015

## 卡在哪

- 不知道现网 20 台 C500 的具体分配（台数测算的最大误差来源）
- 没有能调 qwen3.8-max 的 key
- 模力方舟视频接口（H3）已查到：`v1/async/videos/generations`（10-23 下午，从资源包数据）
- 迁移时间表不知道（生图基线必须在迁移前采）
- 没有 C600 机器可以上手验证

## 下一步

见 `TRACKER.md` 待办。

## 环境备注

- 本机出网经过 127.0.0.1:7897 代理，Python 访问 HF 偶尔 TLS 断开，脚本已加重试
- GitHub API 未登录每小时 60 次，脚本改读 releases.atom，不占额度
- 模力方舟 key：`--api-key` → `$GITEE_AI_API_KEY` / `$MOARK_API_KEY` → `dailyworkinmetax/comic-skill/opencode.json`（gitignored，
  在本目录或仓库目录的上一级找），不要复制进本目录
- 2026-10-23 起本目录在 litellm-CN 仓库（`github.com/gjjjjjjjjjy/litellm-CN`，公开仓库）的 `litellm_zh_cn` 分支里，
  路径 `model-ops/`，和 QosLLM 网关（`deploy/qosllm/`、`qos/`）放在一起。本机 `metax/model-ops` 是指向
  `metax/litellm-CN/model-ops` 的链接。改完要 commit + push；对方常改这个分支，push 前先 `git pull --rebase`

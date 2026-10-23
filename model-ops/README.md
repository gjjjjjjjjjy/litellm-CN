# model-ops — 模力方舟（Gitee.AI）上沐曦卡的模型跟进与维护

跟进对象（2026-10-23 起）：Qwen3.8-27B（VLM）、Qwen-Image-2.1（图片）、Qwen3-Omni-30B-A3B-Instruct（音频 / 全模态）、
MiniMax-H3（音视频生成）；这次 C500 → C600 搬迁还包括 GLM-5.3、Qwen3.8-Max。DeepSeek V4 Flash 在宁夏 C500 6 节点，不在这次搬迁范围内。

## 分工

| 环节 | 谁做 | 这里留什么 |
|---|---|---|
| 1. 模型源：选哪个仓库、哪个 commit | 我们 | `models/<模型>.md` 的「模型源」节，记下 sha |
| 2. 权重模式：BF16 / FP8 / INT8 / 蒸馏版 | 我们 | 同上「权重」节，写清为什么选它 |
| 3. 推理框架 + 版本：vLLM-metax / SGLang / diffusers / vllm-omni | 我们 | 同上「框架」节，含启动命令 |
| 4. 迁移到沐曦卡（算子、精度对齐） | 我们 + 框架组 | 同上「迁移风险」节 |
| 5. 上线前压测 | Gitee.AI | 只记结论（QPS、延迟、卡数） |
| 6. 公网端口映射 / 网关 | Gitee.AI | 只记 endpoint 和 model id |
| 7. 部署后测试 | 我们 | `tools/smoke_test.py` → `results/` |
| 8. 问题反馈与复测 | 我们 | `feedback/`，用 `TEMPLATE.md` |
| 9. 上游跟进：新权重、新量化、框架新版、已知问题 | 我们 | `tools/watch_upstream.py` → `state/CHANGELOG.md` |

## 目录

- `TRACKER.md` — 总表，每个模型走到哪一步、卡在哪
- `models/` — 每个模型一张卡：源、权重、框架、显存、迁移风险、测试结论、待办
- `C600_MIGRATION.md` — C500 → C600：能不能直接迁、要几台（含数据来源）
- `tools/watch_upstream.py` — 查 HF 主仓库 sha、官方量化版、社区量化、讨论区新帖、ModelScope、模力方舟上架、框架新版本，和上次比
- `tools/smoke_test.py` — 部署后冒烟测试（对模力方舟或自部署的 OpenAI 兼容接口都能跑）
- `tools/size_cluster.py` — 按显存算每个模型要几张卡、几台
- `models.json` — 上面三个脚本共用的模型登记表
- `results/LOG.md` — 每次测试每一项一行；`results/<时间>_<模型>/` 放原始返回和生成的图片 / 音频
- `feedback/` — 发出去的问题单

## 日常用法

```bash
cd model-ops                                 # 在 litellm-CN 仓库根目录下
python3 tools/watch_upstream.py              # 每周至少一次；有变化会写进 state/CHANGELOG.md
python3 tools/smoke_test.py qwen3.8-27b      # 模力方舟上的线上版本
python3 tools/smoke_test.py glm-5.3 --base-url http://<节点>:8000/v1 --model-id GLM-5.3 --api-key EMPTY   # 自部署
python3 tools/size_cluster.py                # 台数测算
```

上游一变（主仓库 sha 变了、出了新的 FP8 版、框架发新版），先看 CHANGELOG 里是哪一项，再决定要不要重新部署；
重新部署后一定再跑一遍 smoke_test，结果和上一次对比。

## 和本仓库的 QosLLM 网关一起用

这个目录放在 litellm-CN 的 `litellm_zh_cn` 分支里，和网关是同一个仓库。网关的 `moark` provider 连的也是模力方舟
（`https://api.moark.com/v1`，key 读 `MOARK_API_KEY`），所以 `smoke_test.py` 也认 `MOARK_API_KEY`，两边用同一把 key。

- 直接测模力方舟：上面的默认用法，查的是模型本身（参数是不是被静默忽略、model id 对不对）。
- 走网关测：把 `--base-url` 换成网关地址，key 用网关里建的虚拟密钥，`--model-id` 用网关里配的公开模型名：

  ```bash
  python3 tools/smoke_test.py qwen3.8-27b --base-url http://localhost:4000/v1 --api-key $LITELLM_API_KEY --model-id <网关模型名>
  ```

  这样查的是「网关 + 模力方舟」整条链路。2026-10-23 还没实测过走网关。
- 压测和回答质量评测不在这里做，用仓库里的 `qos/run-perf.sh`、`qos/run-eval.sh`（evalscope），结果在管理界面「服务质量」页看。
  smoke_test 只管能不能用、返回对不对。

## 已知的坑（模力方舟）

- 页面上的名字不一定是 API 的 model id，以 `GET /v1/models` 为准。
- `response_format: json_schema`（以及 GLM 的 `guided_json`）会被接受但不生效，返回散文。2026-10-23 实测
  qwen3.8-27b、GLM-5.3 都是这样。要结构化输出就用 tool calling。
- key 绑定的资源包决定能调哪些模型：未鉴权的 `/v1/models` 列出了 `qwen3.8-max`，但用现在这把 key 调会返回 400
  「您绑定的资源包不支持当前模型或算力」。

# 音频模型跟踪（沐曦 Token 资源包 1492）

2026-10-23 建，还在补。负责范围：思考语音合成（TTS）怎么迁移、怎么验收，ASR 作为 TTS 验收的判官也一并跟踪。验收方法见 `../ACCEPTANCE.md` 第三节。接口参数来自 `state/moark_pkg1492.json`

## 现状：只有 3 个跑在沐曦上

| 模型 | 类型 | 算力 | 接口 | seed | 单价 ¥ |
|---|---|---|---|---|---|
| IndexTTS-2 | TTS（克隆 + 情感控制） | 沐曦 + 燧原，failover 默认开 | `v1/audio/speech` 同步和异步，音频控制语气、文本控制语气两种 | 无 | 2.0 |
| SenseVoiceSmall | ASR | 沐曦 | `v1/audio/transcriptions` | 不需要 | 0 |
| whisper-large-v3-turbo | ASR | 沐曦 | `v1/audio/transcriptions`，`temperature` 默认 0.7 | 不需要 | 0.015 |

其余在别家：CosyVoice3、Step-Audio-TTS-3B、ACE-Step 在 Gitee 自有卡；Qwen3-TTS、GLM-TTS、GLM-ASR、Fun-ASR-Nano 在燧原；Spark-TTS 在昇腾；ChatTTS 在壁仞；TeleTTS 三个和 TeleASR 在 TeleAI（远程接口）；whisper-large-v3 在商汤。只有 CosyVoice3（`seed`）和 ACE-Step（`seeds`）能固定随机种子

10-23 实测：SenseVoiceSmall 和 whisper-large-v3-turbo 都能用，延迟不到 1 秒。SenseVoice 会把中文数字转成阿拉伯数字（「二十三」写成「23」），算 CER 前要统一

## 搬到沐曦的可行性

沐曦公开验证过的 TTS 只有 Qwen3-TTS：vllm-omni-metax 0.26 镜像（C500、C600 都有），`tests/qwen3_tts`（克隆，对应模力方舟的克隆接口）和 `tests/qwen3_tts_customvoice`（9 个预置音色，和模力方舟的音色列表一致），还有 C600 高并发配置。部署配置要点：talker 和 code2wav 分两段，talker 采样 temperature 0.9、top_k 50，code2wav 贪心；沐曦平台强制第二段 eager（驱动在有 CUDA graph 时建流会超时）

上游 vllm-omni 0.26 还列了 CosyVoice3、GLM-TTS、IndexTTS-2，但都没有沐曦的测试，IndexTTS-2 和 GLM-TTS 只标了 NVIDIA。Spark-TTS、ChatTTS、Step-Audio-TTS-3B、ACE-Step 没有加速框架支持，只能用 MACA 版 PyTorch 直接跑。ASR 方面，vLLM-metax 自带 Whisper 的测试

## IndexTTS-2（现在就在沐曦上）

**来源。** HF `IndexTeam/IndexTTS-2` @ `740dcaff39`（2026-01-20），GitHub `index-tts/index-tts` 现在默认是 2.5 版，2.0 由 `indextts/infer_v2.py` 提供

**许可证要确认。** bilibili 自定义许可，以中文版为准（英文版第 9 条写明）：月活超过 1 亿或年收入超过 1 亿人民币要另行授权（英文版写 10 亿，以中文版为准）。量化后的权重算衍生作品，要保留许可证和免责声明。模力方舟、沐曦是否已有授权，要向 Gitee.AI 确认

**随机性。** 三处：GPT 采样（temperature 0.8、top_p 0.8、top_k 30、num_beams 3）、flow matching 初始噪声、情感向量随机选行。官方代码不暴露 seed，同一台机器上外部固定 torch 和 Python 的随机数应该能复现（未验证）。输出 22050 Hz 单声道 16 bit

**迁移要专门测的。** 上游有用户反馈：torch 2.9 下输出满是噪声，退回 2.8 就好（issue #496）；transformers 不是 4.52.1 时有「电流声」（#527）；连续合成 200 多次后 CUDA 报错（#364）。沐曦的 PyTorch 是 2.10，所以迁移后要听噪声、电流声，并做连续 300 次的稳定性测试。结尾杂音本来就有：上游统计 146 次生成里 11 次结尾有咔哒声（7.5%），#806 加了 20 ms 淡出，但嘶声类没修。验收时要区分「本来就有」和「迁移后变多」，所以迁移前要先在现网采一批样本留底

**参考指标。** 论文（arXiv 2506.21619）Seed-TTS test-zh：SS 0.865、WER 1.008，但用的是 FunASR 的说话人模型，和别家不可比。第三方按 seed-tts-eval 工具链（Paraformer-zh、WavLM-large）重测 PyTorch FP32：test-zh CER 1.01、SIM-o 0.765；test-en WER 1.84、SIM-o 0.706（arXiv 2607.21042）。迁移后自己测要用固定的同一套工具

**其他。** 参考音频截断到 15 秒；模力方舟 `emo_alpha` 默认 0.5（上游默认 1.0，文本情感推荐 0.6 左右）；时长控制 2.0 版没开放

## Spark-TTS-0.5B、ChatTTS：权重不能商用

Spark-TTS 代码是 Apache-2.0，但 HF 上的权重已改为 CC BY-NC-SA 4.0（训练数据许可原因），只能非商用。ChatTTS 代码 AGPL-3.0，权重 CC BY-NC 4.0，维护者明确说「代码允许商用，但模型要用自己的」。模力方舟上这两个都在对外提供（Spark 标价 0，ChatTTS 0.02），要向 Gitee.AI 确认授权情况，再决定要不要投入迁移

Spark-TTS 输出 16 kHz，单次最长约 60 秒，已知问题有生成空语音时报错（#82）、偶发 1 分钟空白（#107）、数字和电话读错（#205）。ChatTTS 输出 24 kHz，有官方 `manual_seed`，但模力方舟接口没暴露；不注册文本归一化时会直接删掉数字（#644），验收必须带数字用例

## CosyVoice3（Gitee 自有卡，可能要搬）

**来源。** HF `FunAudioLLM/Fun-CosyVoice3-0.5B-2512` @ `29e01c4e8d`（2026-02-03），同一仓库里有基础版 `llm.pt` 和 RL 版 `llm.rl.pt`，代码默认加载基础版。代码仓库已迁到 `QwenAudio/CosyVoice`。没有 1.5B 开源版

**许可证要法务确认。** 标的是 Apache-2.0，但 README 和模型卡末尾写着「仅供学术用途」，HF 上有人问商用没人回

**随机性。** 只有 LLM 采样 speech token 这一处随机（ras_sampling，top_p 0.8、top_k 25）；flow matching 的噪声和声码器的噪声都是建模型时固定的。所以每次调用前设 seed、没有并发请求时可以复现。模力方舟接口暴露了 `seed`，迁移时可以先试逐条比。输出 24 kHz 单声道；参考音频 ≤ 30 秒，建议 24 kHz

**迁移要专门测的。** transformers ≥ 4.53 会生成流畅但毫无意义的语音（issue #1953，要锁 4.51.3）；TensorRT 加 fp16 会出 NaN 音频（#1930）；vLLM 加 fp16 的 flow 会出无法播放的音频（#1873）。沐曦上如果用新版 transformers 或 fp16，最先出问题的就是这些。另有重复读句、把提示文本读出来、长指令被读出来（#1703、#1733、#1903），以及流式首尾长静音（#1756）

**参考指标（模型卡，2512 版）。** test-zh CER 1.21、SS 78.0；test-en WER 2.24；test-hard CER 6.71。RL 版 test-zh CER 0.81。模型卡没写用的是哪个 ASR 和说话人模型；论文用 Paraformer 和 WavLM

**沐曦。** 沐曦自己的 `MetaX-MACA/VirtualHuman/projects/cosyvoice` 只适配了 CosyVoice2 和 300M 版，没有 3 代

## ASR 判官怎么选

| 模型 | 解码 | 做判官 | 公开 CER |
|---|---|---|---|
| SenseVoiceSmall | 非自回归 CTC 贪心，确定性 | **默认用它**：结果稳定，模力方舟上在沐曦、免费。固定 `language`，去掉情感和事件标签 | AISHELL-1 2.96、AISHELL-2 ios 3.80、WenetSpeech net 7.84 |
| Paraformer-zh | 非自回归，确定性 | seed-tts-eval 的标准判官，对外报数用它。**注意**：FunASR 默认从 ModelScope 下载时 `paraformer-zh` 指向 SeACo-Paraformer，从 HF 下载是普通 Paraformer，两个不是同一个模型，必须写死模型 id 和 sha。seed-tts-eval 只去标点、不做数字归一化 | Paraformer-large：AISHELL-1 1.95、AISHELL-2 ios 2.85 |
| Fun-ASR-Nano-2512 | LLM 解码 | 不建议：LLM 的语言先验可能把 TTS 读错的地方「纠正」回来，掩盖问题；超过 30 秒不切分会出幻觉 | AISHELL-1 1.80、Fleurs-zh 2.56 |
| whisper-large-v3-turbo | 自回归 | 英文用；`temperature` 必须设 0（模力方舟默认 0.7） | |

SenseVoiceSmall 的模型许可是 FunASR MODEL_LICENSE，维护者说可以商用但要署名，有一个确认商用的 issue（#334）还没关

## 待补

Qwen3-TTS、GLM-TTS、Step-Audio-TTS-3B、TeleTTS、ACE-Step 的来源、许可证和公布指标还没查完（两路调研因网络中断失败，这些模型都不在沐曦上，不急）

## 待办

- [ ] 迁移前在现网采 IndexTTS-2 样本（16 条文本，约 ¥32；或先挑 8 条，约 ¥16），并用 SenseVoiceSmall 打 CER
- [ ] 采一批固定音频的 ASR 转写，作为 SenseVoiceSmall、whisper-large-v3-turbo 迁移的基线（免费或很便宜）
- [ ] 向 Gitee.AI 确认：IndexTTS-2、Spark-TTS、ChatTTS 的商用授权；IndexTTS-2 关掉 failover 的方法
- [ ] 将来要把 TTS 搬到沐曦时，优先 Qwen3-TTS（已有沐曦验证）

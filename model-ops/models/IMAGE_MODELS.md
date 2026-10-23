# 生图模型跟踪（沐曦 Token 资源包 1492）

2026-10-23 建。负责范围：资源包里的图像生成、编辑、放大、抠图模型，重点是跑在沐曦上的那些，确保迁移过程没有问题。验收方法见 `../ACCEPTANCE.md` 第二节

数据来源是模力方舟页面背后的公开接口（`/api/pay/service/operations?package_id=1492`），由 `tools/moark_inventory.py` 拉取，快照在 `state/moark_pkg1492.json`。每个接口都标了实际算力：`metax / prod-mx-sh-ip` 是沐曦上海集群，`bailian` 是转发阿里百炼的闭源接口，另外还有昇腾、燧原、壁仞和 Gitee 自有卡。资源包虽然叫「沐曦」，里面 29 个图像类服务只有 11 个用到沐曦。所有沐曦接口的推理引擎都标为 `GiEngine`（Gitee 自己的封装，没有公开文档）

## 跑在沐曦上的（11 个，迁移重点）

| 模型 | 算力 | 接口 | 默认步数 | 默认引导 | seed | 单价 ¥ |
|---|---|---|---|---|---|---|
| Qwen-Image-2512 | 沐曦 | 文生图 1024 / 2048，同步和异步 | 4（4 到 20） | cfg_scale 1 | 有 | 0.05 起 |
| Qwen-Image-Edit | 沐曦 | 图生图 | 30 | cfg_scale 4 | 有 | 0.05 |
| qwen-image-2.1-viggle-turbo | 沐曦 | 文生图、图像编辑，只有异步 | 6（4 到 6） | cfg_scale 1 | 有 | 0.2 |
| FLUX.1-dev | 沐曦 | 文生图 1024 / 1536、局部重绘、图生图 | 20 | guidance_scale 7.5 | 有（默认 42） | 0.05 起 |
| HiDream-I1-Full | 沐曦 | 文生图 | steps 15 | guidance_scale 7.5 | 有 | 0.03 |
| Kolors | 沐曦 | 文生图、局部重绘、风格迁移、垫图 | 25（20 到 30） | guidance_scale 7.5 | 只有局部重绘有 | 0.02 起 |
| stable-diffusion-3.5-large-turbo | 沐曦 | 文生图 | steps 4 | guidance_scale 0 | 无 | 0.03 |
| RMBG-2.0 | 沐曦 | 抠图 | | | 不需要 | 0.01 |
| z-image-turbo | 沐曦 + 昇腾 | 文生图 1024 / 2048（两家都有），ControlNet（只在沐曦） | 9 | ControlNet 为 guidance_scale 1 | 有 | 0.05 起 |
| flux-1-schnell | 沐曦 + 壁仞 | 文生图 1024 / 1536 / 2048，人脸迁移（只在沐曦） | 不可调 | guidance_scale 7.5 | 有（默认 42） | 0.005 起 |
| Real-ESRGAN | 沐曦 + Gitee | 图片放大 2 / 4 倍，5 种权重 | | | 不需要 | 0.01 |

## 上游来源与许可证

sha 是 2026-10-23 的 HF 主分支，迁移前后都要核对部署用的是不是同一个版本

| 模型 | 上游 | 许可证 | 收费 API 能不能用 |
|---|---|---|---|
| Qwen-Image-2512 | `Qwen/Qwen-Image-2512` @ `25468b98e3`；默认值和 `lightx2v/Qwen-Image-2512-Lightning` @ `4609161e30` 的 4 步版一致 | Apache-2.0 | 能 |
| Qwen-Image-Edit | `Qwen/Qwen-Image-Edit` @ `ac7f9318f6` | Apache-2.0 | 能 |
| qwen-image-2.1-viggle-turbo | `Viggle/Qwen-Image-2.1-viggle-turbo` @ `009a44a895`（Viggle AI 做的 LoRA，底座 `Qwen/Qwen-Image-2.1`） | Qwen Research License | **不能**，仅限非商用 |
| FLUX.1-dev | `black-forest-labs/FLUX.1-dev` @ `3de623fc3c` | FLUX.1 [dev] Non-Commercial | **不能**，要向 BFL 买商用许可（生成的图可以商用） |
| flux-1-schnell | `black-forest-labs/FLUX.1-schnell` @ `741f7c3ce8` | Apache-2.0 | 能 |
| ├ 人脸迁移 | 应该是 PuLID（`guozinan/PuLID` @ `492b145125`，参数名一致） | 依赖 insightface antelopev2 | **不能**，insightface 模型仅限非商用研究 |
| HiDream-I1-Full | `HiDream-ai/HiDream-I1-Full` @ `8ccbbfb270` | MIT，但文本编码器是 Llama-3.1-8B | 能，受 Llama 3.1 许可约束 |
| Kolors | `Kwai-Kolors/Kolors` @ `59e638b671` | 代码 Apache-2.0，权重 Kolors 许可 | **要授权**：英文版写明云平台厂商要向快手申请，中文版写任何商用都要申请 |
| SD3.5-large-turbo | `stabilityai/stable-diffusion-3.5-large-turbo` @ `ec07796fc0` | Stability Community License | 年收入 100 万美元以下免费，**超过要企业许可** |
| RMBG-2.0 | `briaai/RMBG-2.0` @ `2fd7b4b0f2`（**10-21 刚更新过**） | CC BY-NC 4.0 | **不能**，商用要和 BRIA 签协议 |
| z-image-turbo | `Tongyi-MAI/Z-Image-Turbo` @ `f332072aa7`；ControlNet 是 `alibaba-pai/Z-Image-Turbo-Fun-Controlnet-Union`（1.0 到 2.1 之一，具体版本查不到） | Apache-2.0 | 能 |
| Real-ESRGAN | GitHub `xinntao/Real-ESRGAN` @ `a4abfb2979`（HF 上没有官方仓库） | BSD-3-Clause | 能；`face_enhance` 用的 GFPGAN 里有非商用的第三方组件 |

**11 个里有 6 个（加上人脸迁移）有商用限制**，没找到 Gitee 持有这些授权的证据。要不要花力气迁移、迁移后能不能继续收费，要先和 Gitee.AI 确认授权

## 默认参数和官方推荐不一致的

迁移时这些默认值要原样保留，否则画质变化会被误判成换卡造成的。同时值得问 Gitee.AI 是否有意为之

| 模型 | 模力方舟默认 | 官方推荐 | 影响 |
|---|---|---|---|
| FLUX.1-dev | 20 步，guidance 7.5；图生图 strength 0.1 | 50 步，guidance 3.5；diffusers 图生图 strength 0.6 | 引导偏高容易过饱和；`negative_prompt` 只在 `true_cfg_scale > 1` 时生效，而接口没暴露 true_cfg，所以负向提示词其实被忽略 |
| flux-1-schnell | guidance 7.5，不暴露步数 | 4 步，guidance 0 | schnell 没有引导嵌入，7.5 被忽略；如果后端没改步数，diffusers 默认会跑 28 步（实际用几步查不到） |
| 人脸迁移（PuLID） | 4 步，guidance 4，起始步 0，id_weight 步长 1 | PuLID 是给 FLUX.1-dev 做的：28 步，guidance 4，写实风格起始步 4，id_weight 步长 0.05 | 在 schnell 上 guidance 不起作用 |
| HiDream-I1-Full | 15 步，guidance 7.5 | 50 步，guidance 5.0，UniPC 调度器 shift 3 | 步数比 HiDream-Fast 版的 16 步还少 |
| Kolors | 25 步（20 到 30），guidance 7.5 | 50 步 / 5.0（Euler）或 25 步 / 5.0（EDM-DPM） | 引导偏高 |
| Qwen-Image-2512 | 4 步，cfg 1 | 原版 50 步、true_cfg 4.0；Lightning 4 步版就是 4 步、cfg 1 | 和 Lightning 一致；cfg 1 时负向提示词不起作用 |
| Qwen-Image-Edit | 30 步，cfg 4 | 50 步，true_cfg 4.0 | 步数少 |
| qwen-image-2.1-viggle-turbo | 6 步（可选 4 到 6），cfg 1（可到 20） | 6 步要配指定的 sigma 列表、cfg 1、不加负向提示词；作者说普通的步数参数和 CFG 都没用 | 4 步、5 步要配对应 sigma，开 CFG 可能变差。Gitee 部署的是哪个版本（v0.1 是 4 步，v0.2 是 5 步，v0.3 是 6 步）查不到 |
| z-image-turbo ControlNet | guidance 1 | Turbo 要求 guidance 0 | diffusers 里 guidance 大于 0 就会开 CFG，计算量翻倍，结果也不同 |
| Real-ESRGAN | 动漫权重 anime_6B，2 倍，`face_enhance` 开 | x4plus，4 倍，`face_enhance` 关 | Gitee 自己的参数说明写着动漫和风景图要关 face_enhance，默认值却是开的 |

## 迁移时要注意的

**换 C600 会连带换软件。** 沐曦的 diffusers 镜像（modelzoo.llm.diffusers）要到 `maca.ai3.7.0.8`（2026-05-21）才有 C600 版本，MACA 3.1、3.3、3.5 的镜像都只支持 C500。所以迁到 C600 至少要升到 MACA 3.7，torch 也会跟着换，数值一定会有变化，这正是要做基线对比的原因

**版本要锁死。** diffusers 升级可能改变同一参数的含义：例如 PR #13730 之后 Z-Image 的 `steps=9` 实际前向次数变了。HiDream 仓库 2025-04 改过调度器配置，导致部分流水线出错。RMBG-2.0 依赖 `trust_remote_code`，transformers 5 曾经让它加载失败，而它 10-21 刚更新过。迁移时 diffusers、transformers 和每个模型仓库都要锁版本

**部署是确定性的，但跨硬件随机数可能不同。** 10-23 试采 Qwen-Image-2512 同 seed 两次输出逐字节相同。但公开测试显示，两个后端的随机数序列不同时，同 seed 出的图完全不一样（FlagOS 实测 Qwen-Image-2512 同 seed 跨后端 PSNR 只有 9.5 dB）。把初始噪声对齐以后才在 35 dB 左右。所以迁移后第一件事是判断随机数序列有没有变，判断方法和后续怎么比见 `ACCEPTANCE.md` 2.4

**多家共用的三个模型没法从公网指定算力。** z-image-turbo、flux-1-schnell、Real-ESRGAN 的部分接口默认开着 `X-Failover-Enabled`，同 seed 的请求可能被别家卡处理，出的图就不同。我们这把 key 只能调沐曦算力，所以用它采的基线应该来自沐曦，但最好向 Gitee.AI 要一个能看出服务节点的响应头

**接口本身的小问题，验收时顺带测。** FLUX.1-dev 局部重绘和图生图、Kolors 风格迁移和垫图、人脸迁移的尺寸选项里有 `1024x683`，683 不是 16 的倍数：FLUX 会悄悄缩放，Z-Image 遇到这种尺寸会报错。HiDream、Kolors 文生图、SD3.5 的参数表里没列 `prompt`（应该只是表漏了）。参数名不统一：`num_inference_steps` 和 `steps`、`guidance_scale` 和 `cfg_scale` 混用，`tools/image_baseline.py` 按每个模型自己的参数名发请求

## 不在沐曦上的（18 个，暂不跟迁移）

| 算力 | 模型 |
|---|---|
| 昇腾 | FLUX.2-dev、GLM-Image、Qwen-Image-Edit-2511、UVDoc |
| 燧原 | CogView4_6B、FLUX.2-klein-4B、FLUX.2-klein-9B、FLUX_1-Krea-dev、LongCat-Image、LongCat-Image-Edit、SeedVR2-3B |
| 壁仞 | stable-diffusion-3.5-large |
| Gitee 自有卡 | AnimeSharp、FLUX.1-Kontext-dev |
| 阿里百炼（闭源接口，不涉及硬件迁移） | qwen-image-2.0、qwen-image-2.0-pro、wan2.7-image、wan2.7-image-pro |

如果迁移范围包括把这些搬到沐曦，流程一样：先在现有算力上采基线，搬过去后对比

## 第一次跟进时的列表里有、资源包里没有的

Qwen-Image-2.1 原版不在资源包里，资源包里的是 qwen-image-2.1-viggle-turbo（底座就是它）。原版的情况见 `qwen-image-2.1.md`。注意许可证仅限非商用，FlagRelease 的沐曦版把它标成 Apache-2.0，和上游冲突，以上游为准

## 待办

- [ ] 采完整基线：8 个文生图模型 × 16 条提示词 × 2 个 seed，256 张，约 ¥14（`tools/image_baseline.py --label c500-<日期> --max-cost 20`），要赶在迁移之前
- [ ] 编辑类基线：Qwen-Image-Edit、FLUX.1-dev 局部重绘和图生图、Kolors 风格迁移和垫图、qwen-image-2.1-viggle-turbo 编辑，要先定输入图
- [ ] RMBG-2.0、Real-ESRGAN 基线：确定性模型，各 10 张输入图即可
- [ ] 向 Gitee.AI 确认：6 个有商用限制模型的授权；迁移时间表；每个模型部署的上游版本和 LoRA（尤其 viggle-turbo 的版本、Qwen-Image-2512 用的 Lightning 版本）；多家共用模型能否指定算力或返回服务节点；上表里默认值是否有意为之
- [ ] 给 `compare_images.py` 加 CLIPScore（需要 open_clip 和 torch），作为随机数序列变了以后的主要判据

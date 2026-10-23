# 生图模型跟踪（沐曦 Token 资源包 1492）

2026-10-23 建。负责范围：资源包里的图像生成、编辑、放大、抠图模型，重点是跑在沐曦上的那些，确保迁移过程没有问题。验收方法见 `../ACCEPTANCE.md` 第二节

数据来源是模力方舟页面背后的公开接口（`/api/pay/service/operations?package_id=1492`），由 `tools/moark_inventory.py` 拉取，快照在 `state/moark_pkg1492.json`。每个接口都标了实际算力：`metax / prod-mx-sh-ip` 是沐曦上海集群，`bailian` 是转发阿里百炼的闭源接口，另外还有昇腾、燧原、壁仞和 Gitee 自有卡。资源包虽然叫「沐曦」，里面 29 个图像类服务只有 11 个用到沐曦

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
| z-image-turbo | 沐曦 + 昇腾 | 文生图 1024 / 2048（两家都有），ControlNet（只在沐曦） | 9 | guidance_scale 1 | 有 | 0.05 起 |
| flux-1-schnell | 沐曦 + 壁仞 | 文生图 1024 / 1536 / 2048，人脸迁移（只在沐曦） | 不可调 | guidance_scale 7.5 | 有（默认 42） | 0.005 起 |
| Real-ESRGAN | 沐曦 + Gitee | 图片放大 2 / 4 倍，5 种权重 | | | 不需要 | 0.01 |

## 已经发现要核对的地方

**部署是确定性的。** 2026-10-23 试采 Qwen-Image-2512 两个提示词，同 seed 两次输出逐字节相同，迁移后可以逐张对比

**Qwen-Image-2512 跑的是加速配置。** 默认 4 步、cfg 1、最多 20 步，官方原版是几十步。很可能加载了 Lightning 一类步数蒸馏 LoRA，迁移后要确认还是同一个 LoRA、同样的默认值，否则画质变化会被误判成换卡造成的

**FLUX.1-dev 默认 guidance_scale 7.5 偏高。** 官方推荐值在 3.5 左右，7.5 容易过饱和、过锐。这不是迁移问题，但值得向 Gitee.AI 确认是不是有意为之（待上游资料核实后补来源）

**flux-1-schnell 默认 guidance_scale 7.5、不暴露步数。** schnell 是引导蒸馏模型，一般用 0 引导、4 步，引导参数大概率被忽略。之前在漫画项目里实测过：套用别的模型的 25 步 / 7.5 会让画风乱跳（见 `reference_gitee_ai_gotchas`）

**Kolors 文生图和 SD3.5-large-turbo 没有 seed。** 迁移前后只能按组比较，多采几次，再加盲评

**多家共用的三个模型没法从公网指定算力。** z-image-turbo、flux-1-schnell、Real-ESRGAN 的同一个接口同时挂在两家卡上，部分还有默认开启的 `X-Failover-Enabled`。我们这把 key 只能调沐曦算力，所以用它采的基线应该来自沐曦，但最好向 Gitee.AI 要一个能看出服务节点的响应头

**参数名不统一。** `num_inference_steps` 和 `steps`、`guidance_scale` 和 `cfg_scale` 混用；qwen-image-2.1-viggle-turbo 用 `return_image_format`，flux-1-schnell 用 `response_format`。`tools/image_baseline.py` 按每个模型自己的参数名发请求

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

Qwen-Image-2.1 原版不在资源包里，资源包里的是 qwen-image-2.1-viggle-turbo。原版的情况见 `qwen-image-2.1.md`（注意许可证仅限非商用）

## 待办

- [ ] 采完整基线：8 个文生图模型 × 16 条提示词 × 2 个 seed，256 张，约 ¥14（`tools/image_baseline.py --label c500-<日期> --max-cost 20`），要赶在迁移之前
- [ ] 编辑类基线：Qwen-Image-Edit、FLUX.1-dev 局部重绘和图生图、Kolors 风格迁移和垫图、qwen-image-2.1-viggle-turbo 编辑，要先定输入图
- [ ] RMBG-2.0、Real-ESRGAN 基线：确定性模型，各 10 张输入图即可
- [ ] 问 Gitee.AI：迁移时间表；多家共用模型能不能指定算力或返回服务节点；FLUX.1-dev 和 flux-1-schnell 的默认引导值是否有意为之
- [ ] 补每个模型的上游仓库、版本、许可证（调研中）

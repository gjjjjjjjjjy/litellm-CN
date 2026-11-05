# QosLLM 公网部署

在本机构建完整的 `linux/amd64` 应用镜像并推送到镜像仓库，服务器拉取指定版本后运行。前后端都包含在镜像中，数据库和证书保存在独立的 Docker 卷中。服务器需要 Docker 和 Docker Compose 插件，Node 与 npm 在本机的构建容器内运行

服务由 PostgreSQL、QosLLM 网关、音视频探测服务和 Caddy 组成。只有 Caddy 对外开放 80 和 443，网关、探测服务和数据库使用 Docker 内部网络

上游按选定的稳定版本系列维护，日常发布使用当前 Fork 的代码。构建与检查从 `pyproject.toml` 读取上游版本，升级步骤见[维护上游版本](../../localization/zh-CN/README.md#维护上游版本)

## 检查和发布

`.github/workflows/qosllm.yml` 只能手动运行，推送和 PR 都不会触发。需要时在 GitHub 仓库的 Actions 页面选择 QosLLM，点 Run workflow 并选择分支。检查以分支所基于的上游版本为基准，即 `pyproject.toml` 版本号对应的上游标签，只检查 Fork 改动的部分。后端对 Fork 新增的 Python 文件运行 ruff，并运行 Fork 改过的测试以及改过模块对应的测试。前端运行 TypeScript 检查和翻译检查，对 Fork 改过的文件运行 eslint、prettier 和对应的 vitest 测试，出现未翻译的文案时检查失败

检查全部通过后，构建镜像并推送到镜像仓库，镜像标签与本机 `publish.sh` 相同，为提交编号的前 12 位，显示在运行结果的摘要中。同一次发布还会推送音视频探测镜像，标签是网关标签加 `-media-probe`。首次使用前在 GitHub 仓库的 Settings > Secrets and variables > Actions 中添加三个 Secret

| 名称 | 内容 |
|---|---|
| `QOSLLM_IMAGE_REPOSITORY` | `<仓库域名>/<命名空间>/qosllm`，与 `publish.sh` 的参数相同 |
| `QOSLLM_REGISTRY_USERNAME` | 镜像仓库用户名 |
| `QOSLLM_REGISTRY_PASSWORD` | 镜像仓库密码 |

仓库公开时 Actions 日志所有人可见，镜像仓库地址也放在 Secret 中，日志里显示为 `***`。服务器更新时把 `.env` 的 `LITELLM_IMAGE` 改为 `<QOSLLM_IMAGE_REPOSITORY>:<镜像标签>`，再运行 `docker compose pull --policy always litellm media-probe` 和 `./start.sh`

## 本机发布

多人合作时，先把经过测试的改动合并到 `litellm_zh_cn`，再从该提交构建一次发布镜像。先用 `docker login` 登录镜像仓库，密码在终端交互输入

```bash
git pull --ff-only origin litellm_zh_cn
docker login <仓库域名> --username <仓库用户名>
./deploy/qosllm/publish.sh <仓库域名>/<命名空间>/qosllm
```

`publish.sh` 使用当前 Git 提交中的文件，镜像标签为该提交的 12 位编号。未提交文件、`.env` 和本机数据库都不会被打包。脚本执行中文翻译检查、TypeScript 检查、前端编译、镜像打包和推送，并打印完整镜像地址。音视频探测镜像用同一个提交构建，推送为 `<镜像地址>-media-probe`，`compose.yaml` 按 `LITELLM_IMAGE` 自动找到它，两者总是同一版本

前端依赖需要通过代理下载时，给发布命令传入容器可访问的代理地址，例如

```bash
HTTPS_PROXY=http://host.docker.internal:7897 \
HTTP_PROXY=http://host.docker.internal:7897 \
./deploy/qosllm/publish.sh <仓库域名>/<命名空间>/qosllm
```

后端基础镜像由 Docker BuildKit 下载，需要保证 Docker 的镜像仓库网络可用。镜像仓库按层复用内容，服务器已有的层无需重复传输。修改前端仍需要在本机重新编译，服务器只拉取和运行

## 首次部署

在云服务器的安全组和防火墙中只放行 22、80 和 443。服务器先获取部署文件并登录镜像仓库

```bash
git clone -b litellm_zh_cn <你的 Fork 地址> litellm-CN
cd litellm-CN/deploy/qosllm
docker login <仓库域名> --username <仓库用户名>
./start.sh
```

第一次运行会生成 `.env`，其中的主密钥、加密盐和数据库密码都是随机值。编辑 `.env`，设置 `SERVER_IP` 为服务器公网 IP，设置 `LITELLM_IMAGE` 为本机发布脚本打印的完整镜像地址

```bash
docker compose pull --policy always litellm media-probe
./start.sh
```

首次启动还需要 `postgres:16` 和 `caddy:2.8.4` 镜像，已有部署继续使用原来的镜像和数据卷

`.env` 要单独备份。`LITELLM_SALT_KEY` 用来加密数据库中的服务商密钥，已有部署应保留其原值

## HTTPS 证书

没有域名时无法申请公认证书，Caddy 用自己的根证书为服务器 IP 签发 HTTPS 证书并自动续期，传输全程加密。浏览器第一次访问 `https://<服务器 IP>/ui/` 会提示证书不受信任，确认继续即可。想去掉提示，把根证书导出后安装到自己电脑的“受信任的根证书颁发机构”中

```bash
docker compose cp caddy:/data/caddy/pki/authorities/local/root.crt ./qosllm-root.crt
```

根证书保存在 `qosllm_caddy_data` 卷中，删除该卷后会生成新的根证书，需要重新安装

## 管理员和用户

启动后创建第一个管理员，脚本会打印一次随机强密码，首次登录时系统会要求修改

```bash
./create-admin.sh admin@example.com
```

用管理员登录 `https://<服务器 IP>/ui/` 后，在用户页面创建其他账号。所有人只能使用管理员创建的账号登录：环境变量账号和主密钥登录已关闭，也没有配置 SSO 或自助注册

密码至少 12 位，必须同时包含大写字母、小写字母、数字和特殊字符，并且不能出现在已泄露密码库中

## Moark 双端点

在模型管理中选择 `Moark (Gitee AI)`，`API Base` 可以填写 `https://api.moark.com/v1` 或 `https://ai.gitee.com/v1`，API Key 填写对应端点可用的密钥。留空使用 `https://api.moark.com/v1`

添加模型时填写的 API Key 默认保存为凭据，凭据名取服务商名称，例如 `moark`，同时填写的 API Base 也存进去。之后再选同一个服务商，表单会自动选用这个凭据，不用再输入 Key。该服务商有多个凭据时，从“已有凭据”里选一个。不想保存时取消勾选“保存为凭据”，Key 就只属于这个模型。凭据在“模型与端点 → LLM 凭据”里修改，所有用它的模型一起生效

需要同时接入时，用同一个对外模型名分别添加两个部署，各自填写 API Base 和上游模型名称。QoS 会将两个端点都显示为 Moark，并保留各自的部署 ID 和接口地址；压测时可以单独选择一个部署，也可以比较两个部署的结果

## 账号锁定

同一账号每连续输错 3 次密码锁定 15 分钟，锁定期间输入正确密码也无法登录，到时间后自动解锁。累计输错 10 次后永久锁定，只能由管理员解锁。登录成功或管理员解锁都会清零失败次数

管理员在用户页面可以看到“临时锁定”或“已锁定”标记，打开该用户点击“解锁账号”即可立即恢复

任何人都可以对已知账号连续输错密码使其锁定，管理员账号也一样。管理员自己被永久锁定时，在服务器上运行

```bash
./unlock-user.sh admin@example.com
```

## 接入异步图片模型

仓库提供了一个仅加入 `internal` 网络的图片适配器。它把模力方舟的异步图片任务包装成 LiteLLM 可调用的 `/v1/images/generations`，并将任务 ID、费用和总耗时写入响应头。适配器不会把 `MOARK_API_KEY` 转发到结果图片的下载地址。

首次部署时复制环境变量模板；已有 `.env` 时直接编辑原文件，保留现有密钥：

```bash
cp .env.example .env
```

在 `.env` 中填写 `MOARK_API_KEY` 和随机生成的 `IMAGE_ADAPTER_KEY`。默认 `config.yaml` 保持空模型列表。将 `config.image-adapter.example.yaml` 中的模型项合并到现有 `config.yaml` 的 `model_list`，并将示例里的设置合并到 `general_settings`；不要用示例文件覆盖现有配置。然后从部署目录启动覆盖文件：

```bash
docker compose -f compose.yaml -f compose.image-adapter.yaml up -d --build
```

`IMAGE_ADAPTER_KEY` 只在 LiteLLM 和适配器之间使用，不能与模力方舟 API key 相同。适配器没有映射宿主机端口，局域网客户端只能访问 LiteLLM 的公开入口。

通用健康检查可能对图像模型发起真实的付费生图请求。示例模型的 `disable_background_health_check: true` 使后台检查跳过它；示例中的 `health_check_skip_disabled_background_models: true` 也使手动健康检查跳过已标记的模型。通过管理页面新增的图像模型目前不会自动带这个标记，需逐个设置。验证图像模型时，使用“服务质量 → 图像”的小样本测试并核对费用。以下直接调用网关的示例同样会产生一次付费请求：

```bash
curl http://127.0.0.1:4000/v1/images/generations \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen-image-2.1-viggle-turbo","prompt":"极简风格海报，白色背景，中央是黑色粗体大字“国产算力”，下方一行小字“2026 上海”","size":"1024x1024"}'
```

服务质量页面的 Images 标签提供图片专用测试。先选两条提示词、一个 seed，确认预算后启动；页面显示成功率、P50/P95 延迟、上游排队和生成时间，并提供原图及逐张人工评分。对话压测与图片测试分开，不用 TTFT、TPOT 判断图片服务。图片和评分保存在 `qos_image_runs` 卷，重建网关不会删除；不要运行 `docker compose down -v`。

### 通过模型管理共享图像模型

管理员在“模型与端点 → 添加模型”选择图像生成模式，填写上游模型、API Base、共享 API Key、单张预估费用和能力参数。模力方舟同步模型使用 OpenAI 兼容接口 `https://api.moark.com/v1`；异步 `qwen-image-2.1-viggle-turbo` 使用网关配置的图片适配器及 `.env` 中的 `MOARK_API_KEY`。保存模型配置不会发起付费生图请求。

图像模型与其他网关模型一样由管理员部署和管理。目前只有管理员能在“服务质量 → 图像”发起评测和查看共享评测记录。已存在的旧个人评测记录仍按原用户归属保留，可继续读取；旧个人 API Key 的保存和推理入口已移除。更新代码不会清除 `qos_image_runs` 卷中的任何文件；若要清除旧凭据文件，应先备份并单独检查卷中的 `personal-models` 目录。

## 音视频测评

`compose.yaml` 里的 `media-probe` 服务运行 `qos/media_probe.py`，网关的 `QOS_MEDIA_PROBE_URL` 已指向它。“服务质量”的“音频”和“视频”标签页里点“开始测评”，网关把请求转给探测服务，探测服务再经网关调用各模型。两者之间用 master key 鉴权，探测服务没有映射宿主机端口。部署里没有设置 `--at`，探测服务只在页面发起测评时运行，不会定时花钱

模型要参与测评，部署的 `model_info` 需要设置 `mode` 和 `qos_probe`。添加模型时把“模式”选为 `/audio/speech`、`/audio/transcriptions` 或 `/videos`，再在“高级设置 → 模型信息”里填写

```json
{"qos_probe": {}}
```

视频模型可以在 `qos_probe` 里加 `"image": true` 表示图生视频，`params` 原样作为请求字段，例如 `{"qos_probe": {"params": {"num_frames": 73}}}`。语音合成需要的固定参数（例如 IndexTTS-2 的 `prompt_audio_url`）放在 LiteLLM 参数里。视频打分和写 Prompt 默认用网关上的 `qwen3.8-27b`，这个模型要先在网关上配置好

合成的语音保存在 `qosllm_media_probe_audio` 卷，评审页面回放时从这里读取。每次测评按服务商标价计费，规则和参数见 `qos/README.md`

## 首页资讯

首页看板的 AI 资讯来自几个 RSS 源，默认是量子位、InfoQ、Hugging Face、OpenAI 和 Google AI，网关每 30 分钟抓取一次。国内服务器可能访问不到海外源，看板会在资讯栏底部列出抓取失败的源。要换成别的源，在 `config.yaml` 的 `general_settings` 中写出完整列表，然后运行 `docker compose restart litellm`

```yaml
general_settings:
  qos_news_feeds:
    - name: 量子位
      url: https://www.qbitai.com/feed
    - name: InfoQ
      url: https://www.infoq.cn/feed
```

公告由管理员在首页看板右侧发布和删除，所有用户可见

## 日常更新

在本机测试并发布镜像后，服务器拉取部署文件，修改 `.env` 中的 `LITELLM_IMAGE` 为该次发布的完整地址，再运行

```bash
git pull --ff-only origin litellm_zh_cn
docker compose pull --policy always litellm media-probe
./start.sh
```

拉取新镜像期间原服务继续运行，`start.sh` 通过 Compose 让网关使用新镜像，并等待健康检查通过。普通启动继续运行 `./start.sh`，复用已拉取的镜像，镜像版本和配置均未变化时不会重建容器

只改部署配置时无需编译镜像。`compose.yaml` 或 `.env` 的改动运行 `./start.sh` 生效，`config.yaml` 的改动运行 `docker compose restart litellm` 生效

服务器不挂载应用源码目录。后台模型和服务商配置保存在数据库中，Git 更新或镜像拉取不会覆盖它们。数据库卷为 `qosllm_postgres_data`，证书卷为 `qosllm_caddy_data`，保留这些卷和现有 `.env`。升级上游版本前备份数据库

```bash
./start.sh
./stop.sh
docker compose logs -f litellm
```

无法使用镜像仓库时，`build-image.sh` 仍可在本机导出完整包，包里同时有网关和音视频探测镜像，上传并用 `docker load -i` 导入。此时把服务器 `.env` 中的 `LITELLM_IMAGE` 设为 `litellm-local:zh-cn-amd64`，再运行 `./start.sh`

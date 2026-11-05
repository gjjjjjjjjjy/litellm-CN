# LiteLLM 中文前端

中文词库、术语规则和构建脚本随 Fork 一起维护。构建时在临时源码副本中应用译文，并把 Fork 的后端代码（如新增的 Moark / Gitee AI 服务商）一起打包，生成镜像 `litellm-local:zh-cn`

`litellm_zh_cn` 分支当前基于 `v1.108.0` 稳定版维护 QosLLM 功能，后续先维护 `1.108.x`。`origin` 指向自己的 Fork，`upstream` 指向 `BerriAI/litellm`。上游版本的维护方式见下文

## 构建和启动

在仓库根目录操作。本机需要 Docker、Bash 和 tar，Node 与 npm 在构建容器内运行。依赖按上游 `package-lock.json` 安装，npm 缓存保存在 Docker 卷 `litellm-zh-cn-npm-cache` 中，重复构建时复用

首次部署时，将 `local-dev/.env.example` 复制为根目录 `.env`，填写管理员凭据、数据库密码和内网 IP。将 `local-dev/config.example.yaml` 复制为 `local-dev/config.yaml`。已有部署继续使用原配置

构建脚本读取 `pyproject.toml` 的版本号，选择同版本官方后端镜像。源码和基础镜像的版本不一致时构建直接报错

```bash
./localization/zh-CN/build.sh "$PWD"
./local-dev/start.sh
```

管理界面为 `http://127.0.0.1:4000/ui/`，内网地址由 `.env` 的 `LITELLM_LAN_IP` 决定。启动脚本复用根目录 `.env`、`local-dev/config.yaml` 和原有 PostgreSQL 数据卷

在 Windows 上使用仓库根目录的 Compose 文件时，把本机镜像覆盖文件放在最后，避免修改仓库默认的 `docker-compose.yml`。已构建中文镜像后运行：

```bash
docker compose -p litellm-cn -f docker-compose.yml -f docker-compose.local-zh.yml up -d --no-build
```

如果还使用仓库根目录的异步图片适配器，先在 `.env` 中填写 `MOARK_API_KEY` 和独立的 `IMAGE_ADAPTER_KEY`，再在本机镜像覆盖文件前加入 `-f docker-compose.image-adapter.yml`。覆盖文件只选择本机中文镜像，不改变已有 `.env` 和数据卷

代理需要使用容器可访问的地址，例如

```bash
HTTPS_PROXY=http://host.docker.internal:7897 \
HTTP_PROXY=http://host.docker.internal:7897 \
./localization/zh-CN/build.sh "$PWD"
```

构建执行补丁测试、TypeScript 检查和 Next.js 静态页面生成。构建结束后自动删除临时源码，依赖和 npm 下载缓存保存在 Docker 卷中，供后续构建复用

`build.sh` 依次调用 `build-ui.sh`（编译中文前端）和 `stage-backend.sh`（整理后端代码并换上 QosLLM 标志），再打包镜像。本机启动和公网发布都使用这些构建步骤。需要指定镜像或目标平台时，仍可运行 `./localization/zh-CN/build.sh "$PWD" 后端基础镜像 [目标平台 镜像名称]`

每次构建都以同版本官方镜像为基础，Docker 复用相同的基础层和构建缓存，应用层包含本次的 Fork 后端和中文前端。更新时继续使用上面的构建命令，镜像按层增量传输

部署到 x86 云服务器时，在本机运行 `./deploy/qosllm/publish.sh <仓库域名>/<命名空间>/qosllm`，将当前 Git 提交构建为 `linux/amd64` 镜像并推送到仓库。服务器拉取指定版本后由 Compose 启动，镜像包含前后端代码。完整步骤见 [公网部署说明](../../deploy/qosllm/README.md)

## 界面名称

界面显示名称为 QosLLM，图标由 Q 字母与 AI 星芒组成，使用蓝色渐变底。侧边栏展开时显示图标与名称，收起时只显示图标，深浅主题使用对应的 `branding/logo*.png`。矢量字标源文件在 `branding/`，独立图标位于 `ui/litellm-dashboard/public/assets/logos/qosllm.svg`，浏览器图标位于 `ui/litellm-dashboard/src/app/favicon.ico`，构建时同时更新前后端的默认图标。浏览器标题和登录页文字在 `zh-CN.json` 中修改。代码、包名和 API 保持 litellm 不变，并保留上游的 MIT 许可证与版权声明

## 精简菜单

QosLLM 页头保留面包屑、页面搜索和主题切换，关闭“网关工具”、LiteAdmin 面板和 LiteLLM 产品推广通知。其他视图使用的旧导航栏按需加载，避免它们的依赖进入首页的初始加载。本地和服务器 Compose 均显式设置 `LITELLM_ENABLE_ADMIN_MCP=false`，关闭托管管理 MCP 服务

`hidden-menus.json` 列出镜像中隐藏的菜单，键名对应 `ui/litellm-dashboard/src/components/leftnav.tsx` 中菜单项的 `key`。隐藏后侧边栏和 Ctrl K 搜索都不再显示，直接访问页面地址仍可打开。上游重命名或删除其中的菜单时构建直接报错，按报错更新列表即可。本地开发和测试不读取该列表，显示完整菜单

## 维护译文

`zh-CN.json` 是唯一的词库，键为英文原文，值为中文译文。`context-overrides.json` 按源文件区分同词异义，例如产品名 Linear 与图表的线性刻度

被行内标签或模板变量拆开的句子按整句提取，用编号占位符表示代码部分，译文可以按中文语序调整占位符位置

- `{0}`：运行时的值或表达式，例如 `已选择 {0} 个模型`
- `<1/>`：整体保留的元素，例如图标、`<code>` 代码片段或组件
- `<2>文字</2>`：包裹文字的行内元素，例如加粗或链接，只翻译其中的文字

译文中的占位符必须与原文一一对应，不能增删、重复或改变形式，否则构建直接报错。译文中不要写 `&quot;` 等 HTML 实体，直接使用实际字符

`terminology.json` 列出保留英文的术语，包括 Token、Prompt、Embedding、Completion、Reasoning、Agent 等。构建时检查译文，出现这些术语的中文译法即报错，不会自动改写。服务商名称、模型 ID、API 字段、表单取值、URL、代码示例和用户实际数据保持原值。后端动态内容与远程文章沿用上游内容

前端出现词库中没有的文案时构建直接报错，列出上游新增或改写的文案及源文件位置。将译文添加到 `zh-CN.json` 后重新构建。构建成功后生成的 `translation-report.json` 记录扫描和翻译的数量，属于本地生成文件，由 Git 忽略

同步上游后删除词库中不再使用的条目，TypeScript 版本与前端 `package.json` 保持一致

```bash
docker run --rm --mount "type=bind,source=$PWD,target=/repo" \
  --mount "type=volume,source=litellm-zh-cn-npm-cache,target=/root/.npm" \
  --env HTTPS_PROXY --env HTTP_PROXY node:24.19-alpine3.24 sh -ec '
    npm install --no-save --no-audit --no-fund --prefix /tmp/ts typescript@5.9.3
    node /repo/localization/zh-CN/localize.mjs prune --source /repo/ui/litellm-dashboard \
      --typescript /tmp/ts/node_modules/typescript --catalog /repo/localization/zh-CN/zh-CN.json
  '
```

## 维护上游版本

日常开发在 `litellm_zh_cn` 上进行，当前以 `1.108.x` 为基础。按修复需要合入该系列的正式补丁版。跨系列升级集中评估上游变更、依赖和数据库迁移后再进行。官方稳定版使用 `vX.Y.Z` 标签，补丁版用于修复问题，版本命名见[官方说明](https://docs.litellm.ai/blog/cleaner-release-versions)

`main` 可作为上游参考分支独立同步。QosLLM 的日常开发和发布都使用当前选定的正式版本，升级时直接合并对应标签

更新时，将下面的 `vX.Y.Z` 替换为选定的正式版本标签。先完成合并，有冲突时解决后运行 `git merge --continue`，再构建并启动本机预览

```bash
git switch litellm_zh_cn
git pull --ff-only origin litellm_zh_cn
git fetch upstream tag vX.Y.Z
git merge --no-edit vX.Y.Z
./localization/zh-CN/build.sh "$PWD"
./local-dev/start.sh
```

检查翻译报告、构建结果、相关测试和实际页面后，推送分支并按[公网部署说明](../../deploy/qosllm/README.md)发布镜像。手动运行的 QosLLM workflow 会检查并发布所选分支的镜像

```bash
git push origin litellm_zh_cn
```

浅克隆缺少共同历史时，先用 `git fetch --deepen=500 upstream tag vX.Y.Z` 加深历史，再执行正常合并。按需继续加深，直到 Git 能找到共同祖先。新版本改变根布局或构建工具时，根据构建错误调整 `prepare-ui.mjs` 或构建脚本

## 许可证

本目录适用仓库根目录的 [MIT 许可证](../../LICENSE)，保留上游版权与许可声明。`enterprise/` 目录适用其自身许可证，见 [企业版许可证](../../enterprise/LICENSE.md)。离线翻译模型的来源说明见 [NOTICE.md](NOTICE.md)

# LiteLLM 中文前端

中文词库、术语规则和构建脚本随 Fork 一起维护。构建时在临时源码副本中应用译文，并把 Fork 的后端代码（如新增的 Moark / Gitee AI 服务商）一起打包，生成镜像 `litellm-local:zh-cn`

`litellm_zh_cn` 分支基于 `v1.106.2` 稳定版维护中文功能，`main` 分支用于同步官方上游。`origin` 指向自己的 Fork，`upstream` 指向 `BerriAI/litellm`

## 构建和启动

在仓库根目录操作。本机需要 Docker、Bash 和 tar，Node 与 npm 在构建容器内运行。依赖按上游 `package-lock.json` 安装，npm 缓存保存在 Docker 卷 `litellm-zh-cn-npm-cache` 中，重复构建时复用

首次部署时，将 `local-dev/.env.example` 复制为根目录 `.env`，填写管理员凭据、数据库密码和内网 IP。将 `local-dev/config.example.yaml` 复制为 `local-dev/config.yaml`。已有部署继续使用原配置

Fork 源码和后端基础镜像需使用同一版本，版本不一致时构建直接报错。当前分支的构建命令为

```bash
./localization/zh-CN/build.sh "$PWD" ghcr.io/berriai/litellm:v1.106.2
./local-dev/start.sh
```

管理界面为 `http://127.0.0.1:4000/ui/`，内网地址由 `.env` 的 `LITELLM_LAN_IP` 决定。启动脚本复用根目录 `.env`、`local-dev/config.yaml` 和原有 PostgreSQL 数据卷

代理需要使用容器可访问的地址，例如

```bash
HTTPS_PROXY=http://host.docker.internal:7897 \
HTTP_PROXY=http://host.docker.internal:7897 \
./localization/zh-CN/build.sh "$PWD" ghcr.io/berriai/litellm:v1.106.2
```

构建执行补丁测试、TypeScript 检查和 Next.js 静态页面生成。构建结束后自动删除临时源码与依赖

## 维护译文

`zh-CN.json` 是唯一的词库，键为英文原文，值为中文译文。`context-overrides.json` 按源文件区分同词异义，例如产品名 Linear 与图表的线性刻度

被行内标签或模板变量拆开的句子按整句提取，用编号占位符表示代码部分，译文可以按中文语序调整占位符位置

- `{0}`：运行时的值或表达式，例如 `已选择 {0} 个模型`
- `<1/>`：整体保留的元素，例如图标、`<code>` 代码片段或组件
- `<2>文字</2>`：包裹文字的行内元素，例如加粗或链接，只翻译其中的文字

译文中的占位符必须与原文一一对应，不能增删、重复或改变形式，否则构建直接报错。译文中不要写 `&quot;` 等 HTML 实体，直接使用实际字符

`terminology.json` 列出保留英文的术语，包括 Token、Prompt、Embedding、Completion、Reasoning、Agent 等。构建时检查译文，出现这些术语的中文译法即报错，不会自动改写。服务商名称、模型 ID、API 字段、表单取值、URL、代码示例和用户实际数据保持原值。后端动态内容与远程文章沿用上游内容

构建生成 `translation-report.json`，其中 `missing` 列出上游新增或改写的文案及源文件位置。将译文添加到 `zh-CN.json` 后重新构建。报告属于本地生成文件，由 Git 忽略

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

## 同步上游

保持 `main` 为官方主分支的镜像

```bash
git fetch upstream main --tags
git switch main
git merge --ff-only upstream/main
git push origin main
git switch litellm_zh_cn
```

中文分支更新稳定版本时，先获取并合并目标稳定版标签，再选择同版本后端镜像重新构建。下面的 `vX.Y.Z` 表示所选稳定版标签

```bash
git fetch upstream tag vX.Y.Z
git merge --no-edit vX.Y.Z
./localization/zh-CN/build.sh "$PWD" ghcr.io/berriai/litellm:vX.Y.Z
```

检查翻译报告、构建结果和页面后，提交中文分支并启动新镜像

```bash
git push origin litellm_zh_cn
./local-dev/start.sh
```

浅克隆需要补齐历史后才能可靠计算合并关系，可先执行 `git fetch --unshallow upstream`。新版本改变根布局或构建工具时，按实际错误调整 `prepare-ui.mjs` 或构建脚本

## 许可证

本目录适用仓库根目录的 [MIT 许可证](../../LICENSE)，保留上游版权与许可声明。`enterprise/` 目录适用其自身许可证，见 [企业版许可证](../../enterprise/LICENSE.md)。离线翻译模型的来源说明见 [NOTICE.md](NOTICE.md)

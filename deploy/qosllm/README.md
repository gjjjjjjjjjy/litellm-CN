# QosLLM 公网部署

在本机构建完整的 `linux/amd64` 应用镜像并推送到镜像仓库，服务器拉取指定版本后运行。前后端都包含在镜像中，数据库和证书保存在独立的 Docker 卷中。服务器需要 Docker 和 Docker Compose 插件，Node 与 npm 在本机的构建容器内运行

服务由 PostgreSQL、QosLLM 网关和 Caddy 组成。只有 Caddy 对外开放 80 和 443，网关和数据库使用 Docker 内部网络

## 本机发布

多人合作时，先把经过测试的改动合并到 `litellm_zh_cn`，再从该提交构建一次发布镜像。先用 `docker login` 登录镜像仓库，密码在终端交互输入

```bash
git pull --ff-only origin litellm_zh_cn
docker login <仓库域名> --username <仓库用户名>
./deploy/qosllm/publish.sh <仓库域名>/<命名空间>/qosllm
```

`publish.sh` 使用当前 Git 提交中的文件，镜像标签为该提交的 12 位编号。未提交文件、`.env` 和本机数据库都不会被打包。脚本执行中文翻译检查、TypeScript 检查、前端编译、镜像打包和推送，并打印完整镜像地址

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
docker compose pull --policy always litellm
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

需要同时接入时，用同一个对外模型名分别添加两个部署，各自填写 API Base 和上游模型名称。QoS 会将两个端点都显示为 Moark，并保留各自的部署 ID 和接口地址；压测时可以单独选择一个部署，也可以比较两个部署的结果

## 账号锁定

同一账号每连续输错 3 次密码锁定 15 分钟，锁定期间输入正确密码也无法登录，到时间后自动解锁。累计输错 10 次后永久锁定，只能由管理员解锁。登录成功或管理员解锁都会清零失败次数

管理员在用户页面可以看到“临时锁定”或“已锁定”标记，打开该用户点击“解锁账号”即可立即恢复

任何人都可以对已知账号连续输错密码使其锁定，管理员账号也一样。管理员自己被永久锁定时，在服务器上运行

```bash
./unlock-user.sh admin@example.com
```

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
docker compose pull --policy always litellm
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

无法使用镜像仓库时，`build-image.sh` 仍可在本机导出完整包，上传并用 `docker load -i` 导入。此时把服务器 `.env` 中的 `LITELLM_IMAGE` 设为 `litellm-local:zh-cn-amd64`，再运行 `./start.sh`

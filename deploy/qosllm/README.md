# QosLLM 公网部署

在本机编译并导出 `linux/amd64` 镜像包，上传到 x86 Linux 服务器后运行。服务器需要 Docker 和 Docker Compose 插件，`start.sh` 只启动已导入的镜像。服务由三个容器组成：PostgreSQL、QosLLM 网关和 Caddy。只有 Caddy 对外开放 80 和 443 端口，80 只负责跳转到 HTTPS。网关和数据库只在 Docker 内部网络中可访问，数据库端口不对外开放

## 本机打包和上传

在本机仓库根目录运行，输出目录需要已存在。本机仅需 Docker、Bash、tar 和 gzip，Node 与 npm 在 Docker 容器中运行

```bash
git pull --ff-only origin litellm_zh_cn
./deploy/qosllm/build-image.sh ../qosllm-linux-amd64.tar.gz
scp -i ~/.ssh/aliyun ../qosllm-linux-amd64.tar.gz root@<服务器公网IP>:/root/service/
```

Apple Silicon Mac 在 ARM 容器中编译静态前端，再为 x86 服务器打包 `linux/amd64` 后端镜像。服务器镜像名为 `litellm-local:zh-cn-amd64`，本机开发使用的 `litellm-local:zh-cn` 保持独立

前端依赖需要通过代理下载时，给打包命令传入容器可访问的代理地址，例如

```bash
HTTPS_PROXY=http://host.docker.internal:7897 \
HTTP_PROXY=http://host.docker.internal:7897 \
./deploy/qosllm/build-image.sh ../qosllm-linux-amd64.tar.gz
```

后端基础镜像由 Docker BuildKit 下载，需要单独保证 Docker 的镜像仓库网络可用。打包过程会显示依赖安装、翻译检查、前端编译和镜像导出的日志，结束后删除临时构建文件

## 首次部署

在云服务器的安全组和防火墙中只放行 22、80 和 443。在服务器上导入本机上传的镜像包，再获取部署配置

```bash
docker load -i /root/service/qosllm-linux-amd64.tar.gz
git clone -b litellm_zh_cn <你的 Fork 地址> litellm
cd litellm/deploy/qosllm
./start.sh
```

第一次运行会生成 `.env`，其中的主密钥、加密盐和数据库密码都是随机值。编辑 `.env`，把 `SERVER_IP` 填成服务器公网 IP，然后再次运行 `./start.sh`。镜像缺失或架构错误时脚本会报错，按提示重新导入镜像包

首次启动还需要 `postgres:16` 和 `caddy:2.8.4` 镜像。服务器无法访问 Docker Hub 时，可以在本机拉取对应的 `linux/amd64` 镜像，用 `docker image save --platform linux/amd64` 导出后上传并导入

`.env` 要单独备份。`LITELLM_SALT_KEY` 用来加密保存在数据库中的服务商密钥，丢失或修改后这些密钥将无法解密

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

## 账号锁定

同一账号每连续输错 3 次密码锁定 15 分钟，锁定期间输入正确密码也无法登录，到时间后自动解锁。累计输错 10 次后永久锁定，只能由管理员解锁。登录成功或管理员解锁都会清零失败次数

管理员在用户页面可以看到“临时锁定”或“已锁定”标记，打开该用户点击“解锁账号”即可立即恢复

任何人都可以对已知账号连续输错密码使其锁定，管理员账号也一样。管理员自己被永久锁定时，在服务器上运行

```bash
./unlock-user.sh admin@example.com
```

## 日常操作

更新时先在本机拉取代码、重新打包并上传，再在服务器运行

```bash
git pull --ff-only origin litellm_zh_cn
docker load -i /root/service/qosllm-linux-amd64.tar.gz
./start.sh
```

导入镜像只更新镜像文件，运行 `./start.sh` 才会让服务使用新镜像。启动后确认网关健康和管理界面可用，再删除上传的镜像包

```bash
./start.sh            # 启动
./stop.sh             # 停止，数据保留在 Docker 卷中
docker compose logs -f litellm   # 查看网关日志
```

数据库保存在 `qosllm_postgres_data` 卷中，证书保存在 `qosllm_caddy_data` 卷中。`docker compose down -v` 会删除这些卷，执行前请先备份

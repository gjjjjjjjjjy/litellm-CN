# QosLLM 公网部署

一台装有 Docker 和 Docker Compose 插件的 Linux 服务器即可运行，构建镜像时 Node 需要约 4 GB 内存。服务由三个容器组成：PostgreSQL、QosLLM 网关和 Caddy。只有 Caddy 对外开放 80 和 443 端口，网关和数据库只在 Docker 内部网络中可访问

## 首次部署

准备一个域名并把 A 记录解析到服务器，防火墙只放行 80 和 443。Caddy 会自动申请 HTTPS 证书

```bash
git clone -b litellm_zh_cn <你的 Fork 地址> litellm
cd litellm/deploy/qosllm
./start.sh
```

第一次运行会生成 `.env`，其中的主密钥、加密盐和数据库密码都是随机值。编辑 `.env`，把 `SITE_ADDRESS` 填成你的域名，然后再次运行 `./start.sh`。没有本地镜像时脚本会先构建 `litellm-local:zh-cn`，首次约 10~20 分钟，之后启动只需几十秒

`.env` 要单独备份。`LITELLM_SALT_KEY` 用来加密保存在数据库中的服务商密钥，丢失或修改后这些密钥将无法解密

没有域名时可以把 `SITE_ADDRESS` 设为 `:80` 临时试用，这时登录密码通过未加密的 HTTP 传输

## 管理员和用户

启动后创建第一个管理员，脚本会打印一次随机强密码，首次登录时系统会要求修改

```bash
./create-admin.sh admin@example.com
```

用管理员登录 `https://<域名>/ui/` 后，在用户页面创建其他账号。所有人只能使用管理员创建的账号登录：环境变量账号和主密钥登录已关闭，也没有配置 SSO 或自助注册

密码至少 12 位，必须同时包含大写字母、小写字母、数字和特殊字符，并且不能出现在已泄露密码库中

## 账号锁定

同一账号连续 3 次输入错误密码后被锁定，锁定后即使输入正确密码也无法登录，登录成功会清零失败次数。管理员在用户页面可以看到“已锁定”标记，打开该用户点击“解锁账号”即可恢复

任何人都可以对已知账号连续输错密码使其锁定，管理员账号也一样。管理员自己被锁时，在服务器上运行

```bash
./unlock-user.sh admin@example.com
```

## 日常操作

```bash
./start.sh            # 启动
./stop.sh             # 停止，数据保留在 Docker 卷中
git pull && ./start.sh --build   # 更新代码后重新构建并启动
docker compose logs -f litellm   # 查看网关日志
```

数据库保存在 `qosllm_postgres_data` 卷中，证书保存在 `qosllm_caddy_data` 卷中。`docker compose down -v` 会删除这些卷，执行前请先备份

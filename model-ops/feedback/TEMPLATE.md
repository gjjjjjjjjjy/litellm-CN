# 问题反馈：<模型> — <一句话现象>

- **日期**：YYYY-MM-DD
- **发给**：Gitee.AI / 框架组（vLLM-metax）/ 模型方
- **环境**：endpoint（模力方舟 / 自部署 IP:端口）、served model id、卡型（C500 / C600）× 卡数、框架 + 版本、权重（BF16 / FP8 / 仓库 + sha）
- **严重程度**：阻塞上线 / 功能缺失 / 体验问题

## 复现

```bash
curl -s https://ai.gitee.com/v1/chat/completions -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" -d '{...}'
```

## 期望 vs 实际

| | 内容 |
|---|---|
| 期望 | |
| 实际 | （原样贴返回，别转述） |

## 证据

- `results/<stamp>_<model>/result.json` 里第 N 项
- 对照：同一请求在官方 API / NVIDIA 参考部署上的返回

## 状态

- [ ] 已发出（日期、渠道、对方联系人）
- [ ] 对方确认
- [ ] 已修复，复测通过（复测的 results 目录）

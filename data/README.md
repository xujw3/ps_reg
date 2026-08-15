# 运行数据目录

此目录只存放 Web 注册服务产生的本地数据，不存放前端或后端源码。

- `accounts/`：账号文件、邮箱凭证、汇总 accounts.txt 和 SQLite 结果库。
- `proxy_lists/`：各账号下载的 ProxyScrape 代理列表。
- `screenshots/`：注册失败现场截图。
- `web_auth.json`：Web 唯一管理员的哈希认证信息。
- 其他子目录：历史备份或运行缓存。

除本说明文件外，`data/` 内容均已由 `.gitignore` 忽略。

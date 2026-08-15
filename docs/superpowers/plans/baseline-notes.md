# 改造基线记录

日期：2026-08-15
项目：grok-register → ProxyScrape 注册链路改造起点

## 后端测试

- 命令：`.venv/Scripts/python.exe -m unittest discover -s backend/tests`
- 结果：**201 tests, 1 error**
- 已知失败：`test_browser_lifecycle.CamoufoxProcessMatchTests.test_kill_all_targets_camoufox_tree_only`
  - 原因：`automation/session.kill_all_camoufox_processes` 在 Windows 上抛 `RuntimeError("当前系统暂不支持批量终止 Camoufox")`（Linux/macOS 专属功能）
  - 性质：环境性既有失败，与本次改造无关；不修复
- 依赖：`.venv` 新建（Python 3.13.7），`pip install -r requirements.txt` 成功（curl_cffi 0.13.0 / camoufox 0.5.4 / playwright 1.60.0 / fastapi 0.141.1）

## 前端构建

- 命令：`cd front && npm ci && npm run build`
- 结果：成功（1657 modules，dist/index.html + assets 产出）
- 基线产物：`front/dist/assets/index-BQcM3mzB.js`（409 KB）、`index-ai_Pj3qQ.css`（40.8 KB）

## 回归线

后续任务验收以「不劣于基线」为准：200+ 测试通过（除上述环境性失败）、前端构建成功。

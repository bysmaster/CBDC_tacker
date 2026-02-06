# GitHub Actions 部署与 Secrets 配置指南

本文档旨在帮助您将 CBDC 监测系统安全地部署到 GitHub，并配置自动化运行所需的密钥。

---

## 1. 部署前准备 (项目清理)

在将代码上传到 GitHub 之前，请确保以下文件已被清理或忽略，以防止敏感信息泄露：

1.  **删除本地配置文件**：
    *   删除项目根目录下的 `.env` 文件（包含您的本地测试密钥）。
2.  **检查 `.gitignore`**：
    *   确保 `.gitignore` 文件中包含 `.env`、`__pycache__/`、`*.pyc`、`data/reports/` 等规则。
    *   本项目的 `.gitignore` 已配置完毕，通常无需修改。

---

## 2. GitHub Secrets 配置指南 (核心步骤)

为了让 GitHub Actions 能够运行您的代码并发送邮件，您必须在 GitHub 仓库中配置“Secrets”（机密变量）。

**注意**：Secrets 一旦保存，您将无法再次查看其内容（只能覆盖），请务必在输入时核对准确。

### 操作步骤

1.  打开您的 GitHub 仓库页面。
2.  点击顶部导航栏的 **Settings** (设置)。
3.  在左侧菜单栏中，找到 **Secrets and variables** -> 点击 **Actions**。
4.  点击右侧绿色的 **New repository secret** 按钮。
5.  依次添加以下 5 个变量（请严格按照下表填写）：

### 变量清单

| Secret Name (变量名) | 说明 | 获取方式 / 示例 |
| :--- | :--- | :--- |
| **`ZAI_API_KEY`** | Z.AI 智能分析服务的 API Key | 登录 Z.AI 平台获取 |
| **`OPENROUTER_API_KEY`** | OpenRouter 服务的 API Key | 登录 OpenRouter 平台获取 |
| **`EMAIL_USER`** | 发送日报的邮箱地址 | 例如：`your_name@qq.com` |
| **`EMAIL_PASS`** | 邮箱 SMTP 授权码 | **注意**：这不是登录密码！<br>请在邮箱设置 -> 账户 -> SMTP 服务中开启并生成授权码。 |
| **`EMAIL_TO`** | 接收日报的邮箱地址 | 接收者的邮箱 |

---

## 3. 验证部署

配置完成后，您可以手动触发一次工作流来验证部署是否成功：

1.  点击仓库顶部的 **Actions** 标签。
2.  在左侧列表中选择 **Daily CBDC Monitor**。
3.  点击右侧的 **Run workflow** 按钮，再次点击绿色的 **Run workflow** 确认。
4.  等待运行完成：
    *   ✅ **绿色打钩**：表示运行成功，日报已发送。
    *   ❌ **红色叉号**：表示运行失败，请点击进去查看日志，通常是 Secrets 填错或网络问题。

---

## 4. 常见问题

*   **Q: 为什么日志里显示 `ZAI_API_KEY not found`？**
    *   A: 请检查 Secrets 中的变量名是否拼写正确（必须是全大写，下划线连接），或者是否不小心在 Value 中多复制了空格。
*   **Q: 邮件发送失败？**
    *   A: 请确保 `EMAIL_PASS` 填的是**授权码**而不是邮箱登录密码。如果您使用的是 QQ 邮箱，请确保 SMTP 服务已开启。


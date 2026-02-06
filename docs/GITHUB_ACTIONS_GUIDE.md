# GitHub Actions 自动化部署指南

本文档详细说明如何配置 GitHub Actions 以实现 CBDC 监测系统的每日自动运行。

## 1. 工作流配置文件

配置文件位于：`.github/workflows/run_daily.yml`

### 核心配置解析

```yaml
on:
  schedule:
    # cron 表达式：分 时 日 月 周
    # 北京时间 (UTC+8) 16:00 = UTC 08:00
    - cron: '0 8 * * *'
```

### 任务步骤说明

1.  **Checkout code**: 拉取最新代码。
2.  **Set up Python**: 安装 Python 3.11 环境。
3.  **Install dependencies**: 安装 `requirements.txt` 中的依赖。
4.  **Install Playwright**: 安装爬虫所需的 Chromium 浏览器内核。
5.  **Run Pipeline**: 执行 `src/main.py` 主程序。
6.  **Upload Artifacts**: 将生成的 Word 报告和 CSV 数据打包保存，可在 Actions 页面下载。

---

## 2. 部署步骤

### 第一步：提交配置文件

确保 `.github/workflows/run_daily.yml` 文件已提交到仓库的默认分支（通常是 `main` 或 `master`）。

```bash
git add .github/workflows/run_daily.yml
git commit -m "Add daily schedule workflow"
git push
```

### 第二步：验证运行

1.  打开 GitHub 仓库页面。
2.  点击顶部导航栏的 **"Actions"**。
3.  在左侧列表中点击 **"Daily CBDC Monitor"**。
4.  点击右侧的 **"Run workflow"** 按钮 -> **"Run workflow"** 进行手动测试。

### 第三步：查看结果

1.  运行完成后（显示绿色对勾），点击该次运行记录。
2.  在页面底部的 **"Artifacts"** 区域，可以下载 `cbdc-reports` 压缩包，内含生成的日报和数据文件。
3.  点击 **"Run CBDC Monitor"** 任务卡片，可以查看详细的执行日志。

---

## 3. 常见问题与解决方案 (FAQ)

### Q1: 自动运行时间不准？
**A**: GitHub Actions 使用 **UTC 时间**。我们配置的 `0 3,8 * * *` 对应 UTC 3:00 和 8:00，即北京时间 11:00 和 16:00。注意：GitHub 的调度可能会有 5-10 分钟的延迟，这是正常现象。

### Q2: 浏览器启动失败 (Headless Mode)？
**A**: 脚本已配置 `--headless` 模式。如果遇到 `DevToolsActivePort file doesn't exist` 错误，通常是因为内存不足。我们在工作流中使用了标准 Ubuntu 运行环境，通常能满足需求。如果涉及 `undetected-chromedriver`，偶尔会因为 GitHub IP 被风控而失败，脚本已内置重试机制。

### Q3: 如何保护 API Key 和邮箱密码？
**A**: 项目已改为通过环境变量读取密钥，建议在 GitHub 仓库设置中配置 **Secrets**（不要把密钥写进代码或提交到仓库）：
1.  进入 Settings -> Secrets and variables -> Actions。
2.  点击 "New repository secret"。
3.  依次添加以下变量（**Name** 必须完全一致）：

    | Name (Secret 名称) | Value (填写说明) |
    | :--- | :--- |
    | `ZAI_API_KEY` | Z.AI 提供的 API Key (用于智能分析) |
    | `OPENROUTER_API_KEY` | OpenRouter 提供的 API Key (备用/辅助模型) |
    | `EMAIL_USER` | 发送日报的邮箱地址 (如 `xxx@qq.com`) |
    | `EMAIL_PASS` | 邮箱 SMTP 授权码 (注意：不是登录密码) |
    | `EMAIL_TO` | 接收日报的邮箱地址 |

4.  工作流文件已在 `env:` 中引用这些 Secrets（见 [.github/workflows/run_daily.yml](file:///d:/Users/bys/Documents/GitHub/cbdc_tracker_work-secret/.github/workflows/run_daily.yml)）。

本地运行建议使用 `.env` 文件（不要提交）：
1.  复制 `.env.example` 为 `.env`
2.  填入上述同名变量
3.  运行 `python src/main.py`

### Q4: 邮件发送失败？
**A**: 
- 检查 `src/processor.py` 中的邮箱配置。
- 确保 SMTP 服务（如 QQ 邮箱）已开启并使用了正确的授权码（非登录密码）。
- GitHub Actions 的 IP 可能被部分邮件服务商（如 Outlook）列入黑名单，建议使用 QQ 或 Gmail SMTP。

---

## 4. 本地测试方法

在提交前，可在本地运行以下命令模拟：

```bash
# 1. 安装依赖
pip install -r requirements.txt
playwright install chromium

# 2. 运行脚本
python src/main.py
```

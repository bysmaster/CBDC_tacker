# CBDC Tracker (全球央行数字货币监测系统)

这是一个用于监测全球央行数字货币（CBDC）发展的智能系统，具有双路径 AI 分析和自动报告生成功能。

## 功能特性

- **多源数据采集**：监测包括欧洲央行 (ECB)、国际清算银行 (BIS)、国际货币基金组织 (IMF) 及各国央行在内的 15+ 个权威数据源。
- **双路径 AI 分析**：并行使用 **Z.AI (GLM-4.7-Flash)** 和 **OpenRouter** 模型，确保服务的高可用性和判断的准确性。
- **自动化报告**：每日自动生成 Word 格式的简报并通过邮件发送摘要。
- **故障报警系统**：如果 API 连接失败，系统会自动发送邮件报警。
- **详细审计记录**：在 CSV 文件中详细记录每个模型的独立判断结果和推理依据，确保透明度。

## GitHub 部署指南

### 1. 仓库设置
1. Fork 或 Clone 本仓库。
2. 在仓库设置 (Settings) 中启用 **GitHub Actions**。

### 2. 配置密钥 (Secrets)
进入 **Settings** > **Secrets and variables** > **Actions** > **New repository secret**。

添加以下密钥：

| 密钥名称 | 说明 | 示例 |
|---|---|---|
| `ZAI_API_KEY` | Z.AI (智谱 GLM) 的 API Key | `a28d...` |
| `OPENROUTER_API_KEY` | OpenRouter 的 API Key | `sk-or...` |
| `EMAIL_USER` | 发件人邮箱地址 (如 QQ 邮箱) | `example@qq.com` |
| `EMAIL_PASS` | SMTP 密码 / 应用授权码 | `abcdefghijklmnop` |
| `EMAIL_TO` | 收件人邮箱地址 | `admin@example.com` |
| `SILICON_KEY` | (可选) 备用翻译服务 Key | `sk-...` |

### 3. 工作流
系统将通过 `.github/workflows/run_daily.yml` 在每天 UTC 时间 08:00 (北京时间 16:00) 自动运行。
您也可以在 **Actions** 选项卡中手动触发运行。

## 本地开发指南

1. 安装依赖：
   ```bash
   pip install -r requirements.txt
   ```
2. 配置环境变量：复制 `.env.example` 为 `.env` 并填入相应的 Key。
3. 运行流水线：
   ```bash
   python -m src.main
   ```

## 项目结构
- `src/scrapers/`: 各个数据源的独立爬虫。
- `src/services/`: AI 相关性分析逻辑。
- `src/clients/`: Z.AI 和 OpenRouter 的 API 客户端。
- `src/processor.py`: 数据处理主程序。
- `data/`: 存储 CSV 数据和生成的报告文件。

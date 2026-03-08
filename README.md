# AI Stock Trading Agent

这是一个基于 AI (LLM) 和技术指标分析的自动化股票交易监控系统。

## 功能特性

- **多模型支持**: 支持 OpenAI (Qwen, DeepSeek 等) API。
- **自动故障切换**: 当首选模型调用失败时，自动切换到备用模型 (如 Qwen-Plus -> Qwen-Max)。
- **技术分析**: 集成 MA, MACD, RSI, CCI, VWAP, ATR 等多种技术指标。
- **实时监控**: 通过 Streamlit 界面实时展示行情、持仓状态和 AI 决策。
- **风控管理**: 内置 1% 风险模型、ATR 动态止损、趋势跟踪与均值回归策略。
- **消息通知**: 支持企业微信 Webhook 通知交易信号。

## 安装与配置

1.  **克隆仓库**

    ```bash
    git clone https://github.com/yourusername/stock-agent.git
    cd stock-agent
    ```

2.  **安装依赖**

    ```bash
    pip install -r requirements.txt
    ```

3.  **配置环境变量**

    在项目根目录下创建一个 `.env` 文件 (请勿上传到 GitHub)，填入您的 API Key：

    ```ini
    ALIYUN_KEY=sk-xxxxxxxxxxxxxxxx
    ALIYUN_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
    
    DEEPSEEK_KEY=sk-xxxxxxxxxxxxxxxx
    
    OPENAI_KEY=sk-xxxxxxxxxxxxxxxx
    OPENAI_URL=https://api.openai.com/v1

    WECOM_WEBHOOK=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxxxxxx
    ```
    
    或者在您的服务器/部署环境中直接设置这些环境变量。

## 运行

启动 Streamlit 界面：

```bash
streamlit run gui.py
```

## 注意事项

- 本项目仅供学习和研究使用，不构成投资建议。
- 股市有风险，入市需谨慎。
- 请妥善保管您的 API Key，不要泄露给他人。

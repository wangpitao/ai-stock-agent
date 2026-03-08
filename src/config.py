import os

# 尝试从环境变量读取
# 部署后可以在服务器上设置这些变量，或者创建一个 .env 文件 (不要上传到 GitHub)

ALIYUN_KEY = os.getenv("ALIYUN_KEY", "")
ALIYUN_URL = os.getenv("ALIYUN_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")

DEEPSEEK_KEY = os.getenv("DEEPSEEK_KEY", "")
DEEPSEEK_URL = os.getenv("DEEPSEEK_URL", "https://api.deepseek.com")

OPENAI_KEY = os.getenv("OPENAI_KEY", "")
OPENAI_URL = os.getenv("OPENAI_URL", "https://api.openai.com/v1")

WECOM_WEBHOOK = os.getenv("WECOM_WEBHOOK", "")

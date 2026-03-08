import requests
import json
import logging
import datetime
import time

logger = logging.getLogger(__name__)

class WeComNotifier:
    """群机器人模式"""
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send_text(self, content: str, mentioned_mobile_list=None):
        if not self.webhook_url: return
        headers = {"Content-Type": "application/json"}
        data = {"msgtype": "text", "text": {"content": content, "mentioned_mobile_list": mentioned_mobile_list or []}}
        try:
            requests.post(self.webhook_url, headers=headers, json=data, timeout=5)
        except Exception: pass

    def send_markdown(self, markdown_content: str):
        if not self.webhook_url: return
        headers = {"Content-Type": "application/json"}
        # 确保 markdown_content 不为空
        if not markdown_content:
            markdown_content = "通知: 内容为空"
        data = {"msgtype": "markdown", "markdown": {"content": markdown_content}}
        try:
            resp = requests.post(self.webhook_url, headers=headers, json=data, timeout=5).json()
            if resp.get('errcode') != 0:
                logger.error(f"Webhook 发送失败: {resp}")
        except Exception as e:
            logger.error(f"Webhook 请求异常: {e}")


class WeComAppNotifier:
    """自建应用模式 (AgentId + Secret)"""
    def __init__(self, corp_id, agent_id, secret):
        self.corp_id = corp_id
        self.agent_id = agent_id
        self.secret = secret
        self.token = None
        self.token_expires_at = 0

    def _get_token(self):
        """获取 Access Token (带缓存)"""
        if self.token and time.time() < self.token_expires_at:
            return self.token
        
        url = f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={self.corp_id}&corpsecret={self.secret}"
        try:
            resp = requests.get(url, timeout=5).json()
            if resp.get('errcode') == 0:
                self.token = resp.get('access_token')
                self.token_expires_at = time.time() + resp.get('expires_in', 7200) - 60
                return self.token
            else:
                logger.error(f"获取 Access Token 失败: {resp}")
                return None
        except Exception as e:
            logger.error(f"请求 Access Token 异常: {e}")
            return None

    def send_text(self, content: str, to_user="@all"):
        token = self._get_token()
        if not token: return
        
        url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}"
        data = {
            "touser": to_user,
            "msgtype": "text",
            "agentid": self.agent_id,
            "text": {
                "content": content
            },
            "safe": 0
        }
        try:
            requests.post(url, json=data, timeout=5)
        except Exception: pass

    def send_markdown(self, markdown_content: str, to_user="@all"):
        """发送 Markdown 消息"""
        token = self._get_token()
        if not token: return

        url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}"
        data = {
            "touser": to_user,
            "msgtype": "markdown",
            "agentid": self.agent_id,
            "markdown": {
                "content": markdown_content
            }
        }
        try:
            resp = requests.post(url, json=data, timeout=5).json()
            if resp.get('errcode') != 0:
                logger.error(f"发送消息失败: {resp}")
        except Exception as e:
            logger.error(f"发送消息异常: {e}")

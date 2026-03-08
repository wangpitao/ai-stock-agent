import uiautomation as auto
import time
import pyperclip
import logging

logger = logging.getLogger(__name__)

class WeComPCAuto:
    def __init__(self):
        self.window = auto.WindowControl(searchDepth=1, Name="企业微信")
    
    def send_msg(self, target_name, msg):
        """
        :param target_name: 微信客户昵称/备注/群名
        :param msg: 消息内容
        """
        try:
            if not self.window.Exists(0, 0):
                logger.error("未找到企业微信窗口，请确保PC端已登录")
                return False

            # 1. 激活窗口
            self.window.SetActive()
            # self.window.SetTopmost(True) # 可选：强制置顶
            time.sleep(0.2)

            # 2. Ctrl+F 搜索
            self.window.SendKeys('{Ctrl}f')
            time.sleep(0.3)
            
            # 3. 输入名字
            pyperclip.copy(target_name)
            self.window.SendKeys('{Ctrl}v')
            time.sleep(0.8) # 等待搜索
            self.window.SendKeys('{Enter}') # 选中
            time.sleep(0.2)

            # 4. 发送消息
            pyperclip.copy(msg)
            self.window.SendKeys('{Ctrl}v')
            time.sleep(0.2)
            self.window.SendKeys('{Enter}')
            
            logger.info(f"RPA发送给 [{target_name}] 成功")
            return True

        except Exception as e:
            logger.error(f"RPA发送异常: {e}")
            return False



import time
import json
import os
import pandas as pd
from datetime import datetime
from src.data_loader import MarketDataLoader
from src.analyzer import TechnicalAnalyzer
from src.agent import TradingAgent
from src.notifier import WeComNotifier
from src.config import ALIYUN_KEY, ALIYUN_URL, WECOM_WEBHOOK

def is_trading_time():
    from datetime import time as dt_time
    now = datetime.now()
    if now.weekday() >= 5: return False
    current_time = now.time()
    return (dt_time(9, 25) <= current_time <= dt_time(11, 32)) or \
           (dt_time(12, 58) <= current_time <= dt_time(15, 5))

def load_portfolio():
    """从配置文件加载真实持仓信息"""
    config_path = "positions.json"
    if os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"cash": 100000.0, "holdings": {}}

def run_daemon():
    print(f"🚀 [职业版] 后台监控启动...")
    
    loader = MarketDataLoader()
    analyzer = TechnicalAnalyzer()
    notifier = WeComNotifier(WECOM_WEBHOOK)
    
    # 初始化 AI 代理
    agent = TradingAgent(strategy_type="llm", model="qwen-plus", api_key=ALIYUN_KEY, base_url=ALIYUN_URL)
    
    while True:
        if not is_trading_time():
            time.sleep(60)
            continue
            
        portfolio = load_portfolio()
        # 监控列表就是持仓列表 + 你额外想看的
        symbols = list(portfolio['holdings'].keys())
        # 如果你还有没买但想盯着的，可以手动加在这里：
        # if "600036" not in symbols: symbols.append("600036")
        
        for s in symbols:
            try:
                snap = loader.get_realtime_snapshot(s)
                if not snap: continue
                
                df_hist = loader.fetch_history(s, period="1y")
                df_eval = analyzer.add_indicators(df_hist)
                
                # 获取该股的具体持仓
                holding = portfolio['holdings'].get(s, {'quantity': 0, 'avg_cost': 0.0})
                
                decision = agent.decide(
                    symbol=s, 
                    market_data=df_eval.iloc[-1].to_dict(), 
                    current_position=holding['quantity'], 
                    cash_balance=portfolio['cash'], 
                    avg_cost=holding['avg_cost'],
                    history_df=df_eval.iloc[-11:-1]
                )
                
                if decision['action'] != 'HOLD':
                    stock_name = loader.get_stock_name(s)
                    profit_pct = ((snap['price'] / holding['avg_cost']) - 1) * 100 if holding['avg_cost'] > 0 else 0
                    
                    msg = f"🔔【实盘预警】{stock_name} ({s})\n"
                    msg += f"信号: {decision['action']}\n"
                    msg += f"当前价: {snap['price']:.3f}\n"
                    if holding['quantity'] > 0:
                        msg += f"持仓成本: {holding['avg_cost']:.3f}\n"
                        msg += f"当前盈亏: {profit_pct:+.2f}%\n"
                    msg += f"AI建议: {decision['reason']}"
                    
                    if notifier:
                        notifier.send_markdown(msg.replace('\n', '\n\n'))
                    print(f"[{datetime.now()}] 信号已发出: {s}")
            except Exception as e:
                print(f"监控异常 ({s}): {e}")
        
        time.sleep(60)

if __name__ == "__main__":
    run_daemon()

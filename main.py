import sys
import os
import logging
import time
import pandas as pd
from datetime import datetime

# 将 src 目录添加到路径中
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from src.data_loader import MarketDataLoader
from src.analyzer import TechnicalAnalyzer
from src.agent import TradingAgent
from src.trader import PaperTrader
from src.notifier import WeComNotifier, WeComAppNotifier
try:
    from src.wecom_auto import WeComPCAuto
    HAS_RPA = True
except ImportError:
    HAS_RPA = False

logger = logging.getLogger(__name__)

# 预设的阿里云 KEY
ALIYUN_KEY = os.getenv("ALIYUN_KEY", "")
ALIYUN_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEEPSEEK_URL = "https://api.deepseek.com"
OPENAI_URL = "https://api.openai.com/v1"

def run_backtest(symbol="AAPL", initial_cash=100000.0, use_llm=False, model_name="qwen-plus", api_key=None, base_url=None):
    loader = MarketDataLoader()
    stock_name = loader.get_stock_name(symbol)
    
    print(f"\n启动回测: {stock_name} ({symbol})")
    print(f"策略: {'LLM ('+model_name+')' if use_llm else '规则基'}")
    
    analyzer = TechnicalAnalyzer()
    agent = TradingAgent(strategy_type="llm" if use_llm else "technical", model=model_name, api_key=api_key, base_url=base_url) 
    trader = PaperTrader(initial_cash=initial_cash)

    print("1. 获取数据...")
    df = loader.fetch_history(symbol, period="2y")
    if df is None: return
    df = analyzer.add_indicators(df)
    
    print("2. 模拟中...")
    days = 30 if use_llm else 300
    start_idx = max(60, len(df) - days)
    
    for i in range(start_idx, len(df)):
        current_data = df.iloc[i].to_dict()
        p_item = trader.portfolio.get(symbol, {})
        current_pos = p_item.get('quantity', 0) if isinstance(p_item, dict) else 0
        avg_c = p_item.get('avg_cost', 0.0) if isinstance(p_item, dict) else 0.0
        
        decision = agent.decide(symbol=symbol, market_data=current_data, current_position=current_pos, cash_balance=trader.cash, avg_cost=avg_c, history_df=df.iloc[i-5:i])
        if decision['action'] != 'HOLD':
            print(f"[{df.index[i].strftime('%Y-%m-%d')}] {decision['action']} @ {current_data['Close']:.2f} | {decision['reason']}")
        trader.execute(symbol, decision)

    final_v = trader.get_portfolio_value({symbol: df.iloc[-1]['Close']})
    print(f"\n报告: 最终资产 {final_v:.2f} | 收益 {((final_v-initial_cash)/initial_cash)*100:.2f}%")

def run_live_monitor(symbol, use_llm=False, model_name="qwen-plus", api_key=None, base_url=None, webhook_url=None, app_config=None):
    loader = MarketDataLoader()
    stock_name = loader.get_stock_name(symbol)
    notifier = None
    if webhook_url: notifier = WeComNotifier(webhook_url)
    elif app_config: notifier = WeComAppNotifier(app_config['corp_id'], app_config['agent_id'], app_config['secret'])
    
    print(f"\n=== 实时盯盘: {stock_name} ({symbol}) ===")
    agent = TradingAgent(strategy_type="llm" if use_llm else "technical", model=model_name, api_key=api_key, base_url=base_url)
    analyzer = TechnicalAnalyzer()
    df_history = loader.fetch_history(symbol, period="1y")
    if df_history is None: return

    try:
        while True:
            now_str = datetime.now().strftime("%H:%M:%S")
            snap = loader.get_realtime_snapshot(symbol)
            if not snap: 
                time.sleep(10); continue
            
            new_row = pd.DataFrame([{'Open':snap['open'],'High':snap['high'],'Low':snap['low'],'Close':snap['price'],'Volume':snap['volume']}], index=[pd.Timestamp.now().normalize()])
            df_all = pd.concat([df_history, new_row])
            df_all = df_all[~df_all.index.duplicated(keep='last')]
            df_ind = analyzer.add_indicators(df_all)
            curr = df_ind.iloc[-1].to_dict()
            
            decision = agent.decide(symbol=symbol, market_data=curr, current_position=0, cash_balance=100000, history_df=df_ind.iloc[-6:-1])
            action = decision['action']
            print(f"[{now_str}] {stock_name} {curr['Close']:.2f} | RSI:{curr.get('RSI',0):.1f} | 信号:{action}", end="\r")
            
            if action in ['BUY', 'SELL']:
                msg = f"【AI预警】{action}\n标的: {stock_name}\n价格: {curr['Close']:.2f}\n原因: {decision['reason']}"
                print(f"\n{msg}\n")
                if notifier: 
                    target = app_config.get('to_user','@all') if app_config else None
                    if app_config: notifier.send_markdown(msg.replace('\n','\n\n'), to_user=target)
                    else: notifier.send_markdown(msg.replace('\n','\n\n'))
                import winsound
                winsound.Beep(1000, 800)
            time.sleep(60)
    except KeyboardInterrupt: print("\n停止")

def main():
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        print("模式: 1.回测 2.盯盘")
        choice = input("选: ").strip()
        symbol = input("代码: ").strip() or "600519"
        use_llm = input("LLM? (y/n): ").strip().lower() == 'y'
        
        model_n = "qwen-plus"; api_k = ALIYUN_KEY; base_u = ALIYUN_URL
        if use_llm:
            print("\n模型: 1.DeepSeek 2.GPT-4o 3.阿里云Plus 4.阿里云Max")
            m_c = input("选: ").strip()
            if m_c == '1': model_n = "deepseek-chat"; base_u = DEEPSEEK_URL; api_k = None
            elif m_c == '2': model_n = "gpt-4o"; base_u = OPENAI_URL; api_k = None
            elif m_c == '4': model_n = "qwen-max"
            
            if not api_k: # 非预设阿里云，需要输入
                api_k = os.getenv("OPENAI_API_KEY") or input(f"输入 {model_n} KEY: ").strip()
        
        webhook = None; app_c = None
        if choice == '2':
            print("\n通知: 1.不通 2.Webhook 3.自建应用")
            n_c = input("选: ").strip()
            if n_c == '2': webhook = input("URL: ").strip()
            elif n_c == '3': app_c = {'corp_id':input("CorpId: ").strip(),'agent_id':input("AgentId: ").strip(),'secret':input("Secret: ").strip(),'to_user':input("接收人: ").strip() or "@all"}
        
        if choice == '2': run_live_monitor(symbol, use_llm, model_n, api_k, base_u, webhook, app_c)
        else: run_backtest(symbol, 100000, use_llm, model_n, api_k, base_u)
    except Exception as e: logger.exception("发生错误")

if __name__ == "__main__":
    main()

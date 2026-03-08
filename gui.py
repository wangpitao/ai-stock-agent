import streamlit as st
import pandas as pd
import plotly.graph_objects as fgo
from plotly.subplots import make_subplots
import time
import os
import sys
from datetime import datetime, timedelta, time as dt_time
import threading
from collections import deque
import json
import importlib

# 将 src 目录添加到路径中
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

import src.data_loader
import src.analyzer
import src.agent
import src.trader
import src.notifier
import src.config

# 强制重载模块，确保修改后的 data_loader 生效
importlib.reload(src.data_loader)

from src.data_loader import MarketDataLoader
from src.analyzer import TechnicalAnalyzer
from src.agent import TradingAgent
from src.trader import PaperTrader
from src.notifier import WeComNotifier
from src.config import ALIYUN_KEY, ALIYUN_URL, DEEPSEEK_KEY, DEEPSEEK_URL, OPENAI_KEY, OPENAI_URL, WECOM_WEBHOOK

# 页面配置
st.set_page_config(page_title="AI 智能交易助手", layout="wide", page_icon="🤖")

# --- 全局辅助函数 ---

def get_beijing_time():
    """获取北京时间 (UTC+8)，解决云服务器时区问题"""
    return datetime.utcnow() + timedelta(hours=8)

def is_trading_time():
    """判定当前是否为A股交易时间"""
    now = get_beijing_time()
    if now.weekday() >= 5: # 周六日不交易
        return False
    
    current_time = now.time()
    # 上午 9:25 - 11:32
    morning_start = dt_time(9, 25)
    morning_end = dt_time(11, 32)
    # 下午 12:58 - 15:05
    afternoon_start = dt_time(12, 58)
    afternoon_end = dt_time(15, 5)
    
    return (morning_start <= current_time <= morning_end) or \
           (afternoon_start <= current_time <= afternoon_end)

def load_portfolio_from_file():
    """从服务器文件加载持仓配置"""
    config_path = "positions.json"
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {"cash": 100000.0, "holdings": {}}

def save_portfolio_to_file(cash, holdings_dict):
    """保存配置到服务器文件 (实现多端同步)"""
    data = {
        "cash": cash,
        "holdings": holdings_dict
    }
    with open("positions.json", 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)
    return True

def plot_stock_data(df, symbol, stock_name):
    """绘制专业的 K 线图"""
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                       vertical_spacing=0.03, subplot_titles=(f'{stock_name} ({symbol})', 'RSI & 趋势强度'), 
                       row_width=[0.3, 0.7])

    fig.add_trace(fgo.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='K线'), row=1, col=1)
    
    if 'SMA_20' in df.columns:
        fig.add_trace(fgo.Scatter(x=df.index, y=df['SMA_20'], line=dict(color='blue', width=1), name='MA20 (趋势线)'), row=1, col=1)
    
    if 'RSI' in df.columns:
        fig.add_trace(fgo.Scatter(x=df.index, y=df['RSI'], line=dict(color='purple', width=1.5), name='RSI'), row=2, col=1)
        fig.add_hline(y=70, line_dash="dash", line_color="red", row=2, col=1)
        fig.add_hline(y=30, line_dash="dash", line_color="green", row=2, col=1)

    fig.update_layout(xaxis_rangeslider_visible=False, height=600, template="plotly_dark", margin=dict(l=10, r=10, t=50, b=10))
    return fig

# --- 后台监控核心类 ---
class BackgroundMonitor:
    def __init__(self):
        self.is_running = False
        self.logs = deque(maxlen=50)  # 增加日志容量
        self.latest_decisions = {} # {symbol: {action, reason, time, confidence}}
        self.decision_history = deque(maxlen=15) # 保留最近15次决策记录
        self.thread = None
        self.lock = threading.Lock()
        self.last_check_time = "未启动"
        self.first_run_done = False # 标记是否已执行过首次扫描
        self.allow_off_market_notify = False # 默认只在交易时间通知

    def log(self, message):
        timestamp = get_beijing_time().strftime("%H:%M:%S")
        self.logs.append(f"[{timestamp}] {message}")

    def start(self, model_config):
        with self.lock:
            if self.is_running: return
            self.is_running = True
            # 将配置存入实例变量
            self.model_config = model_config
            self.thread = threading.Thread(target=self._run_loop, daemon=True)
            self.thread.start()
            self.log(f"🚀 后台监控已启动 | 模型: {model_config.get('model_name')}")

    def stop(self):
        with self.lock:
            self.is_running = False
            self.log("🛑 后台监控服务正在停止...")

    def _run_loop(self):
        # 初始化组件
        loader = MarketDataLoader()
        analyzer = TechnicalAnalyzer()
        
        webhook_url = WECOM_WEBHOOK
        notifier = WeComNotifier(webhook_url) if webhook_url else None
        
        # 使用传入的配置初始化 AI (动态配置)
        cfg = getattr(self, 'model_config', {})
        agent = TradingAgent(
            strategy_type="llm", 
            model=cfg.get('model_name', 'qwen-plus'), 
            api_key=cfg.get('api_key', ALIYUN_KEY), 
            base_url=cfg.get('base_url', ALIYUN_URL)
        )
        
        # 状态记录，防止重复报警 {symbol: {'last_action': 'BUY', 'last_time': timestamp}}
        last_signals = {} 

        while self.is_running:
            try:
                self.last_check_time = get_beijing_time().strftime("%Y-%m-%d %H:%M:%S")
                
                is_market_open = is_trading_time()
                
                # 逻辑优化：如果是刚启动，即使休市也强制扫描一次，以便更新看板
                if not is_market_open and self.first_run_done:
                    # 降低非交易时间的休眠频率，但保持活跃以防需要操作
                    self.log("💤 休市中... (等待开盘)")
                    time.sleep(300) 
                    continue
                elif not is_market_open:
                    self.log("💤 休市中，执行静态盘面分析...")
                
                # 每次循环都重新读取文件，保证配置实时生效
                # 增加简单的重试机制防止文件读写冲突
                portfolio = {"cash": 100000.0, "holdings": {}}
                for _ in range(3):
                    try:
                        portfolio = load_portfolio_from_file()
                        break
                    except Exception:
                        time.sleep(0.5)

                monitor_list = list(portfolio.get('holdings', {}).keys())
                
                if not monitor_list:
                    self.log("⚠️ 监控列表为空")
                    time.sleep(300)
                    continue

                self.log(f"🔍 扫描中: {len(monitor_list)} 只标的 (批量模式)...")
                
                # 批量获取实时行情 (极大提升速度)
                try:
                    snapshots = loader.get_realtime_snapshot(monitor_list)
                    # 如果只有一只股票，get_realtime_snapshot 可能返回单个 dict，统一转为 dict of dicts
                    if isinstance(snapshots, dict) and 'price' in snapshots:
                        snapshots = {monitor_list[0]: snapshots}
                    elif snapshots is None:
                        snapshots = {}
                except Exception as e:
                    self.log(f"❌ 批量获取行情失败: {e}")
                    snapshots = {}

                for s in monitor_list:
                    if not self.is_running: break 
                    
                    # 1. 获取数据
                    snap = snapshots.get(s)
                    if not snap: 
                        self.log(f"⚠️ 无法获取 {s} 的实时行情")
                        continue
                        
                    try:
                        df_hist = loader.fetch_history(s, period="1y")
                        if df_hist is None or df_hist.empty: continue
                        
                        # 确保历史数据包含最新的实时价格(做一个简单的拼接，保证指标计算包含当前一刻)
                        # 注意：这里简化处理，仅用于计算指标
                        # 构造一行新数据
                        new_row = pd.DataFrame([{
                            'Open': snap['open'],
                            'High': snap['high'],
                            'Low': snap['low'],
                            'Close': snap['price'],
                            'Volume': snap['volume']
                        }], index=[pd.Timestamp.now()])
                        
                        # 确保不重复添加当天数据
                        if not df_hist.empty and df_hist.index[-1].date() == pd.Timestamp.now().date():
                            df_hist = df_hist.iloc[:-1] # 移除旧的最后一行
                        
                        df_hist = pd.concat([df_hist, new_row])
                        
                        df_eval = analyzer.add_indicators(df_hist)
                        
                        # 准备传给 AI 的数据包 (合并技术指标 + 实时盘口)
                        market_data_packet = df_eval.iloc[-1].to_dict()
                        # 注入盘口深度数据
                        if 'bid1_vol' in snap:
                            market_data_packet.update({
                                'bid1_vol': snap['bid1_vol'],
                                'ask1_vol': snap['ask1_vol'],
                                'bid1_price': snap['bid1_price'],
                                'ask1_price': snap['ask1_price']
                            })

                    except Exception as e:
                        self.log(f"❌ 数据预处理失败 {s}: {e}")
                        continue
                    
                    # 2. 获取持仓
                    holding = portfolio['holdings'].get(s, {'quantity': 0, 'avg_cost': 0.0})
                    
                    # 3. AI 决策
                    try:
                        decision = agent.decide(
                            symbol=s, 
                            market_data=market_data_packet, 
                            current_position=holding['quantity'], 
                            cash_balance=portfolio.get('cash', 100000), 
                            avg_cost=holding['avg_cost'],
                            history_df=df_eval.iloc[-11:-1]
                        )
                        # 记录最新决策结果 (无论是否 HOLD)
                        timestamp = get_beijing_time().strftime("%H:%M:%S")
                        record = {
                            "symbol": s,
                            "time": timestamp,
                            "action": decision['action'],
                            "reason": decision['reason'],
                            "price": snap['price']
                        }
                        with self.lock:
                            # 更新单股最新状态
                            self.latest_decisions[s] = record
                            # 追加到历史记录 (去重：如果是同一只股票且决策相同且时间极短，不重复添加，避免刷屏)
                            # 但为了简单，直接添加，因为扫描频率本身就低
                            self.decision_history.appendleft(record) # 最新的在左边/前面

                    except Exception as e:
                        self.log(f"❌ AI决策失败 {s}: {e}")
                        continue
                    
                    current_action = decision['action']

                    # 4. 信号冷却过滤 (核心优化)
                    # 只有当信号改变，或者距离上次同类信号超过 1小时，或者价格波动超过 2% 时才再次通知
                    last_info = last_signals.get(s, {'last_action': 'NONE', 'last_time': 0, 'last_price': 0})
                    
                    should_notify = False
                    now_ts = time.time()
                    price_change = abs(snap['price'] - last_info.get('last_price', snap['price'])) / snap['price']

                    if current_action != 'HOLD':
                        if current_action != last_info['last_action']:
                            should_notify = True # 信号改变 (HOLD -> BUY)
                        elif (now_ts - last_info['last_time'] > 600): 
                            should_notify = True # 超过1小时再次提醒
                        elif price_change > 0.02:
                            should_notify = True # 价格大幅波动再次提醒
                    
                    if should_notify:
                        # 更新状态
                        last_signals[s] = {
                            'last_action': current_action, 
                            'last_time': now_ts, 
                            'last_price': snap['price']
                        }

                        stock_name = loader.get_stock_name(s)
                        log_msg = f"🔔 {stock_name}: {current_action} @ {snap['price']}"
                        self.log(log_msg)
                        
                        msg = f"【AI监控】{stock_name} ({s})\n信号: {current_action}\n价格: {snap['price']:.2f}\n原因: {decision['reason']}"
                        
                        # 判断是否发送通知: 交易时间 OR 用户强制开启非交易时间通知
                        should_send = is_market_open or getattr(self, 'allow_off_market_notify', False)
                        
                        if notifier and should_send:
                            try:
                                notifier.send_markdown(msg.replace('\n', '\n\n'))
                            except Exception as e:
                                self.log(f"❌ 发送消息失败: {e}")
                
                self.first_run_done = True
                time.sleep(300) # 300秒(5分钟)轮询一次
                
            except Exception as e:
                # 这一层捕获是整个线程的最后防线，绝对不能让线程死掉
                self.log(f"💥 严重: 监控主循环异常 {str(e)}")
                time.sleep(300)

@st.cache_resource
def get_monitor():
    return BackgroundMonitor()

def main():
    st.sidebar.title("🤖 智能交易系统 (Web服务端)")
    
    # 0. 加载服务端数据 (实现刷新不重置)
    server_data = load_portfolio_from_file()

    monitor = get_monitor()
    
    # --- 热修复补丁：防止旧缓存对象缺失属性报错 ---
    if not hasattr(monitor, 'latest_decisions'):
        monitor.latest_decisions = {}
    if not hasattr(monitor, 'logs'):
        monitor.logs = deque(maxlen=50)
    if not hasattr(monitor, 'decision_history'):
        monitor.decision_history = deque(maxlen=15)
    # ----------------------------------------
    
    # 将 JSON 数据转换为文本框的默认显示格式
    default_holdings_str = ""
    for code, info in server_data.get('holdings', {}).items():
        default_holdings_str += f"{code},{info['quantity']},{info['avg_cost']}\n"
    default_holdings_str = default_holdings_str.strip()
    
    # 1. 全局配置
    with st.sidebar.expander("🌍 全局设置", expanded=True):

        symbols_input = st.text_input("股票代码 (支持逗号分隔)", value="")
        symbols = [s.strip() for s in symbols_input.replace('，', ',').split(',') if s.strip()]
        
        use_llm = st.toggle("开启 AI 增强决策", value=True)
        # 允许用户输入或选择，并明确指定 qwen3.5-plus
        model_option = st.sidebar.selectbox(
            "分析模型 (Model)", 
            ["qwen-plus", "qwen-max", "qwen3.5-plus", "deepseek-chat", "gpt-4o", "qwen2.5-72b-instruct"], 
            index=0
        )
        
        # 自动关联配置文件中的 KEY
        if "qwen" in model_option:
            api_key = ALIYUN_KEY
            base_url = ALIYUN_URL
            model_name = model_option # 直接使用选项值作为模型名
        elif "deepseek" in model_option:
            api_key = DEEPSEEK_KEY
            base_url = DEEPSEEK_URL
            model_name = "deepseek-chat"
        elif "OpenAI" in model_option:
            api_key = OPENAI_KEY
            base_url = OPENAI_URL
            model_name = "gpt-4o"
        
        # 只有当配置文件里没有Key时才显示输入框 (防止界面太乱)
        if not api_key:
             api_key = st.sidebar.text_input("请输入API KEY", type="password")

        st.sidebar.markdown("---")
        allow_off_market_notify = st.sidebar.toggle("🔔 允许非交易时间发送通知", value=False, help="开启后，即使在休市时间，AI 产生的信号也会推送到企业微信。")
        # 将开关状态传递给 monitor (通过一种简单的方式，比如写入全局变量或者作为参数，这里为了简单直接 patch monitor)
        if hasattr(monitor, 'allow_off_market_notify'):
            monitor.allow_off_market_notify = allow_off_market_notify
        else:
            # 动态添加属性
            monitor.allow_off_market_notify = allow_off_market_notify

    # 1.5 实盘持仓设置
    with st.sidebar.expander("💰 实盘持仓录入 (服务端同步)", expanded=False):
        st.caption("录入后 AI 将根据你的成本计算止损和建议")
        portfolio_input = st.text_area("格式: 代码,数量,成本 (每行一个)", 
                                     value=default_holdings_str,
                                     help="例如: 600519,100,1750.5")
        
        # 解析持仓
        real_portfolio = {}
        for line in portfolio_input.strip().split('\n'):
            if ',' in line:
                parts = line.split(',')
                if len(parts) == 3:
                    sym, qty, cost = parts
                    real_portfolio[sym.strip()] = {
                        'quantity': int(qty.strip()),
                        'avg_cost': float(cost.strip())
                    }
        
        available_cash = st.number_input("账户可用现金", value=server_data.get('cash', 100000.0))
        
        if st.button("💾 保存配置到服务器"):
            if save_portfolio_to_file(available_cash, real_portfolio):
                st.success("✅ 已保存！多端同步生效，后台监控已更新。")
                time.sleep(1)
                st.rerun()

    # 自动合并监控列表：手动输入的 + 持仓中的
    monitor_symbols = list(set(symbols + list(real_portfolio.keys())))

    # 2. 市场环境参考 (简化模拟)
    st.sidebar.markdown("---")
    
    # 自动刷新逻辑
    auto_refresh = st.sidebar.toggle("⚡ 开启页面自动刷新 (30s)", value=False)
    # 将状态存入 session_state，供 main 函数末尾使用
    st.session_state['auto_refresh_running'] = auto_refresh

    st.sidebar.subheader("📊 市场环境")
    st.sidebar.caption("建议：当大盘 RSI > 70 时减仓，RSI < 30 时分批买入")

    tab1, tab2 = st.tabs(["📉 深度回测", "📺 多股实时监控"])
    loader = MarketDataLoader()
    analyzer = TechnicalAnalyzer()

    with tab1:
        st.header("量化回测 (含 T+1 与滑点模拟)")
        col1, col2, col3 = st.columns(3)
        with col1: initial_cash = st.number_input("初始资金", value=100000)
        with col2: days = st.slider("分析深度(天)", 10, 365, 30)
        with col3: slippage = st.slider("模拟滑点 (%)", 0.0, 0.5, 0.1, step=0.05) / 100

        if st.button("开始全量化回测"):
            # 回测时可以使用 monitor_symbols，也可以只用 symbols。
            # 为了方便，这里也用 monitor_symbols，或者让用户自己选。
            # 保持 symbols 主要是为了让回测更聚焦于用户手动输入的。
            for symbol in symbols:
                stock_name = loader.get_stock_name(symbol)
                st.subheader(f"分析标的: {stock_name} ({symbol})")
                
                with st.spinner(f"正在模拟 {symbol} 真实交易环境..."):
                    df = loader.fetch_history(symbol, period="2y")
                    if df is None: continue
                    df = analyzer.add_indicators(df)
                    
                    agent = TradingAgent(strategy_type="llm" if use_llm else "technical", 
                                        model=model_name, api_key=api_key, base_url=base_url)
                    trader = PaperTrader(initial_cash=initial_cash, slippage=slippage)
                    
                    status_bar = st.empty()
                    progress_bar = st.progress(0)
                    start_idx = max(60, len(df) - days)
                    
                    for i in range(start_idx, len(df)):
                        current_date = df.index[i]
                        current_data = df.iloc[i].to_dict()
                        
                        status_bar.caption(f"📅 模拟日期: {current_date.strftime('%Y-%m-%d')} | 当前价: {current_data['Close']:.3f}")
                        
                        # 获取持仓信息
                        holding = trader.portfolio.get(symbol, {'quantity': 0, 'avg_cost': 0.0})
                        
                        decision = agent.decide(symbol=symbol, market_data=current_data, 
                                              current_position=holding['quantity'], 
                                              cash_balance=trader.cash, 
                                              avg_cost=holding['avg_cost'], 
                                              history_df=df.iloc[i-10:i])
                        
                        # 传入日期以强制执行 T+1
                        trader.execute(symbol, decision, current_date=current_date.date())
                        progress_bar.progress((i - start_idx + 1) / (len(df) - start_idx))
                        if use_llm: time.sleep(0.05)
                    
                    # 结果
                    final_v = trader.get_portfolio_value({symbol: df.iloc[-1]['Close']})
                    profit = final_v - initial_cash
                    st.metric("最终资产", f"{final_v:.2f}", f"{profit:.2f} ({(profit/initial_cash)*100:.2f}%)")
                    
                    st.plotly_chart(plot_stock_data(df.iloc[start_idx-20:], symbol, stock_name), use_container_width=True)
                    if trader.history:
                        st.dataframe(pd.DataFrame(trader.history), use_container_width=True)

    with tab2:
        st.header("📡 智能监控中心 (7x24小时)")
        
        # 使用全局监控对象的状态
        col_m1, col_m2 = st.columns([1, 3])
        with col_m1:
            if st.button("▶️ 启动后台监控" if not monitor.is_running else "⏹️ 停止后台监控"):
                if not monitor.is_running:
                    # 启动时，把当前侧边栏选择的配置传进去
                    cfg = {
                        "model_name": model_name,
                        "api_key": api_key,
                        "base_url": base_url
                    }
                    monitor.start(cfg)
                else:
                    monitor.stop()
                st.rerun()
        
        with col_m2:
            # 获取当前运行的模型名称
            current_model = getattr(monitor, 'model_config', {}).get('model_name', '未启动') if monitor.is_running else '未启动'
            status_text = f"🟢 运行中 ({current_model})" if monitor.is_running else "🔴 已停止"
            st.info(f"状态: {status_text} | 上次扫描: {monitor.last_check_time}")

        # --- 新增：实时决策透视看板 ---
        st.subheader("🧠 AI 实时决策透视 (最近 15 次)")
        if hasattr(monitor, 'decision_history') and monitor.decision_history:
            decision_data = []
            # 遍历历史记录
            for info in list(monitor.decision_history):
                s = info.get('symbol', 'N/A')
                stock_name = loader.get_stock_name(s) if s != 'N/A' else 'N/A'
                
                # 提取置信度 (如果有的话)
                reason_clean = info.get('reason', '')
                confidence = "N/A"
                if "[AI" in reason_clean:
                    try:
                        confidence = reason_clean.split("]")[0].split("AI")[1].strip()
                    except:
                        pass
                
                decision_data.append({
                    "股票名称": f"{stock_name} ({s})",
                    "最新时间": info.get('time', 'N/A'),
                    "当前价格": info.get('price', 0),
                    "AI建议": info.get('action', 'N/A'),
                    "置信度": confidence,
                    "详细理由": reason_clean
                })
            
            # 使用 pd.DataFrame 直接展示列表
            st.dataframe(
                pd.DataFrame(decision_data), # 不设置index，显示序号 0,1,2...
                use_container_width=True,
                column_config={
                    "AI建议": st.column_config.TextColumn(
                        "AI建议",
                        help="BUY=买入, SELL=卖出, HOLD=持有",
                        validate="^(BUY|SELL|HOLD)$"
                    ),
                    "详细理由": st.column_config.TextColumn("详细理由", width="large")
                },
                height=400 # 固定高度防止太长
            )
        elif monitor.latest_decisions:
             # 兼容旧逻辑
             st.caption("暂无最新历史记录，显示最近快照...")
             pass # 原代码逻辑已删除，因为 decision_history 会被自动 patch
        else:
            st.caption("等待第一次扫描结果...")

        st.subheader("📜 实时运行日志")
        # 显示日志区域
        log_container = st.empty()
        with log_container.container():
            if hasattr(monitor, 'logs') and monitor.logs:
                for log in reversed(monitor.logs):
                    st.text(log)
            else:
                st.text("暂无日志...")

        st.divider()
        
        # 下面是只读的实时看板 (手动刷新查看)
        if st.button("🔄 刷新最新行情 (手动)"):
            st.rerun()

        monitor_symbols = list(set(symbols + list(real_portfolio.keys())))
        if monitor_symbols:
            cols = st.columns(len(monitor_symbols)) if len(monitor_symbols) <= 4 else st.columns(4)
            for idx, s in enumerate(monitor_symbols):
                with cols[idx % 4]:
                    snap = loader.get_realtime_snapshot(s)
                    if snap:
                        is_holding = " (持仓)" if s in real_portfolio else ""
                        st.metric(f"{loader.get_stock_name(s)}{is_holding}", 
                                f"{snap['price']:.3f}", 
                                f"{snap['price']-snap['open']:.3f}")

    # 底部说明
    st.sidebar.markdown("---")
    st.sidebar.info("💡 提示：后台监控服务独立于网页，关闭浏览器后依然会持续运行。")
    
    # 自动刷新逻辑执行
    if st.session_state.get('auto_refresh_running', False):
        # 简单的 sleep + rerun 会阻塞交互
        # 为了让用户有感觉，可以加个小提示
        time.sleep(30)
        st.rerun()

if __name__ == "__main__":
    main()
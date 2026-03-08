import logging
import json
import os
from openai import OpenAI
import pandas as pd
import numpy as np
from datetime import datetime

logger = logging.getLogger(__name__)

class TradingAgent:
    def __init__(self, strategy_type="technical", model="qwen-plus", api_key=None, base_url=None):
        self.strategy_type = strategy_type
        self.model = model
        self.log_file = "llm_logs.txt"
        
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL")
        
        # 定义 Qwen 系列模型的自动轮询池 (按优先级排序)
        # 包含了标准名和特定版本名，优先使用性能较好的 Plus/Max，然后是 Flash/Turbo
        self.qwen_fallback_pool = [
            "qwen-plus", 
            "qwen-max", 
            "qwen3.5-plus",
            "qwen3.5-plus-2026-02-15",
            "qwen3.5-max",
            "qwen3.5-flash", 
            "qwen3.5-flash-2026-02-23",
            "qwen-turbo",
            "qwen3.5-397b-a17b", # 备用特定版本
            "qwen3.5-122b-a10b",
        ]
        
        if strategy_type == "llm":
            try:
                self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
                logger.info(f"AI 量化 Agent 初始化 | 模型: {model}")
                if not os.path.exists(self.log_file):
                    with open(self.log_file, "w", encoding='utf-8') as f:
                        f.write(f"=== AI Quant Strategy Logs ===\n")
            except Exception as e:
                logger.error(f"OpenAI 初始化失败: {e}")
                self.strategy_type = "technical" 

    def decide(self, symbol: str, market_data: dict, current_position: int = 0, cash_balance: float = 0.0, avg_cost: float = 0.0, history_df: pd.DataFrame = None):
        """
        主决策入口：整合量化管理原则
        """
        if self.strategy_type == "llm":
            return self._decide_by_llm_quant(symbol, market_data, current_position, cash_balance, avg_cost, history_df)
        else:
            return self._decide_by_rules_quant(symbol, market_data, current_position, cash_balance, avg_cost, history_df)

    def _decide_by_rules_quant(self, symbol, market_data, current_position, cash_balance, avg_cost, history_df):
        """
        量化规则版：趋势追踪 + 波动率止损
        """
        price = market_data.get('Close', 0)
        atr = market_data.get('ATR', price * 0.02)
        adx = market_data.get('ADX', 0)
        rsi = market_data.get('RSI', 50)
        sma20 = market_data.get('SMA_20', price)
        
        action = 'HOLD'; quantity = 0; reason = "等待量化确认"
        
        # 1. 持仓管理 (量化风控优先)
        if current_position > 0:
            # 动态止损：价格跌破 成本 - 2*ATR
            stop_loss_price = avg_cost - 2 * atr
            # 移动止盈：价格跌破 20日均线
            if price < stop_loss_price:
                action = 'SELL'; reason = f"量化止损：跌破ATR保护位({stop_loss_price:.2f})"
            elif price < sma20 and adx > 20:
                action = 'SELL'; reason = "趋势反转：跌破20日均线"
            elif rsi > 85:
                action = 'SELL'; reason = "超买预警：RSI过高"
            
            if action == 'SELL': quantity = current_position

        # 2. 买入管理 (多重确认，谨慎买入)
        elif current_position == 0:
            # 条件A：趋势初显 (Price > SMA20 且 MACD金叉)
            # 条件B：趋势强度 (ADX > 20)
            # 条件C：风险收益比 (当前价距离SMA20不远)
            macd_h = market_data.get('MACDh_12_26_9', 0)
            
            # 主流趋势跟随策略
            if price > sma20 and macd_h > 0 and adx > 25:
                # 计算头寸：单笔风险不超过总资产的 1% (1% Risk Rule)
                total_assets = cash_balance
                risk_per_share = 2 * atr # 止损距离
                if risk_per_share > 0:
                    target_qty = int((total_assets * 0.01) // risk_per_share)
                    # 再次限制：最高投入可用资金的 50%
                    max_qty = int((cash_balance * 0.5) // price)
                    quantity = (min(target_qty, max_qty) // 100) * 100
                    
                    if quantity >= 100:
                        action = 'BUY'; reason = "量化确认：趋势强度达标，量价配合买入"

        return {'action': action, 'quantity': quantity, 'reason': reason, 'price': price}

    def _decide_by_llm_quant(self, symbol, market_data, current_position, cash_balance, avg_cost, history_df):
        """
        AI量化版：赋予AI主流量化投资哲学
        """
        price = market_data.get('Close')
        atr = market_data.get('ATR', price * 0.02)
        sma20 = market_data.get('SMA_20', price)
        
        # 构建专业的量化分析上下文
        history_summary = ""
        if history_df is not None:
            # 计算最近5日的波动率和平均成交量
            vol_mean = history_df['Volume'].mean()
            curr_vol = market_data.get('Volume', 0)
            vol_ratio = curr_vol / vol_mean if vol_mean > 0 else 1.0
            
            # 盘口力度 (如有)
            bid_ask_info = ""
            if 'bid1_vol' in market_data and 'ask1_vol' in market_data:
                bid_v = market_data.get('bid1_vol', 0)
                ask_v = market_data.get('ask1_vol', 0)
                if ask_v > 0:
                    ba_ratio = bid_v / ask_v
                    bid_ask_info = f" | 买一/卖一比: {ba_ratio:.2f} ({'买盘强' if ba_ratio > 1.2 else '卖压大' if ba_ratio < 0.8 else '均衡'})"

            history_summary = f"量比(Vol/MA5): {vol_ratio:.2f}{bid_ask_info} | 波动率(ATR): {atr:.3f}"

        # 过滤掉非数值类型的干扰项
        indicators_text = "\n".join([f"{k}: {v:.3f}" for k, v in market_data.items() 
                                   if isinstance(v, (int, float)) and k not in ['date', 'time', 'bid1_vol', 'ask1_vol', 'bid1_price', 'ask1_price']])

        # 计算关键点位
        stop_loss_level = avg_cost - (2 * atr) if current_position > 0 else 0
        profit_pct = ((price - avg_cost) / avg_cost * 100) if current_position > 0 and avg_cost > 0 else 0
        
        # 针对 0 持仓的特殊提示
        position_status_prompt = ""
        if current_position == 0:
            position_status_prompt = "🔴 **当前为空仓状态 (Watch List)**。请重点评估是否出现**建仓买点** (如趋势突破、回踩支撑、超跌反弹)。"
        else:
            position_status_prompt = f"🔵 **当前持仓: {current_position} 股**。请重点评估是否需要**止盈止损**。"

        # 获取 CCI, VWAP 等新指标
        cci = market_data.get('CCI', 0)
        vwap = market_data.get('VWAP', price)

        system_prompt = f"""你是一名拥有20年经验的华尔街资深基金经理，擅长结合 **趋势跟踪(Trend Following)** 与 **均值回归(Mean Reversion)** 策略。
你的交易系统包含以下核心原则：

1. **趋势研判 (Trend)**:
   - 价格 > MA20 或 MACD 金叉，视为多头信号。
   - 价格 < MA20 且 MACD 死叉，视为空头趋势。
   - 允许在趋势初期 (MA20拐头向上) 提前布局，不必死板等待所有指标完美。

2. **机构视角 (Smart Money)**:
   - 关注 VWAP。价格在 VWAP 附近企稳是良好的低吸点。
   - 关注量比。底部放量是主力建仓信号。

3. **极值交易 (Mean Reversion)**:
   - 当 CCI < -100 或 RSI < 30 时，关注**超跌反弹**机会，可尝试左侧交易。
   - 当 CCI > 150 或 RSI > 80 时，警惕回调风险。

4. **风控铁律 (Risk Control)**:
   - 亏损达到 2ATR 必须止损。
   - 任何买入建议必须有明确的止损位逻辑。

请基于提供的数据，敏锐捕捉交易机会。
- **对于空仓标的**：寻找买入机会（趋势共振、突破、超跌）。
- **对于持仓标的**：保护利润，截断亏损。
输出 JSON，reason 字段用中文解释逻辑。"""

        user_prompt = f"""【资产概况】
- 标的: {symbol}
- 当前价: {price:.3f}
- {position_status_prompt}
- 持仓均价: {avg_cost:.2f} (浮动盈亏: {profit_pct:.2f}%)
- 建议止损位 (成本-2ATR): {stop_loss_level:.3f}

【深度技术面】
{history_summary}
- 趋势指标: MA20={sma20:.3f}, ADX={market_data.get('ADX', 0):.1f}
- 震荡指标: RSI={market_data.get('RSI', 50):.1f}, CCI={cci:.1f}, KDJ_J={market_data.get('J', 0):.1f}
- 机构指标: VWAP={vwap:.3f} (现价在VWAP之{"上" if price > vwap else "下"})
{indicators_text}

【当前状态自检】
1. 趋势健康度: {"多头排列" if price > sma20 else "空头排列/震荡"}
2. 筹码状态: {"获利盘主导" if price > vwap else "套牢盘主导"}
3. 风险系数: ATR={atr:.3f} ({"高波动" if atr/price > 0.03 else "正常波动"})

请给出决策。
输出格式: {{"action": "BUY"|"SELL"|"HOLD", "reason": "简短分析...", "confidence": 0-100}}"""

        output_format = f"""
输出格式: {{"action": "BUY"|"SELL"|"HOLD", "reason": "简短分析...", "confidence": 0-100}}"""

        # 构造待尝试的模型列表
        models_to_try = [self.model]
        
        # 如果当前模型是 Qwen 系列，启用自动切换机制
        is_qwen = "qwen" in self.model.lower()
        if is_qwen:
            # 将池子里的模型加入待尝试列表 (去重 + 排除已在队首的当前模型)
            for m in self.qwen_fallback_pool:
                if m != self.model and m not in models_to_try:
                    models_to_try.append(m)

        last_error = None
        
        # 循环尝试模型
        for current_model in models_to_try:
            try:
                # 只有当切换模型时才打印日志
                if current_model != self.model:
                     logger.info(f"⚠️ 正在尝试切换模型: {current_model} ...")

                response = self.client.chat.completions.create(
                    model=current_model,
                    messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                    temperature=0.3, 
                    response_format={"type": "json_object"}
                )
                content = response.choices[0].message.content
                
                # 记录日志 (标记实际使用的模型)
                log_tag = f"[{current_model}]" if current_model != self.model else ""
                with open(self.log_file, "a", encoding='utf-8') as f:
                    f.write(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {symbol} {log_tag} -> {content}\n")
                
                result = json.loads(content)
                action = result.get('action', 'HOLD').upper()
                confidence = int(result.get('confidence', 50))
                reason = result.get('reason', 'AI量化')
                
                # 如果成功获取结果，更新 reason 里的标识，方便前端看到
                if current_model != self.model:
                    reason = f"(转{current_model}) {reason}"

                quantity = 0
                # 放宽置信度门槛到 65 (原75)，让 AI 更容易出手
                if action == 'BUY' and confidence >= 65: 
                    risk_per_share = 2 * atr if atr > 0 else price * 0.05
                    target_qty = int((cash_balance * 0.02) // risk_per_share)
                    max_allowable = int((cash_balance * 0.6) // price)
                    quantity = (min(target_qty, max_allowable) // 100) * 100
                elif action == 'SELL':
                    quantity = current_position
                
                # 双重保险：如果 AI 说卖，但价格其实还在成本之上且趋势没坏，强制 HOLD (防止 AI 幻觉)
                if action == 'SELL' and current_position > 0:
                     if price > sma20 and price > stop_loss_level and confidence < 80:
                         action = 'HOLD'
                         reason += " [系统修正: 趋势仍健康，驳回轻率卖出建议]"

                return {
                    'action': action if quantity > 0 or action == 'SELL' else 'HOLD', 
                    'quantity': quantity, 
                    'reason': f"[AI {confidence}%] {reason}", 
                    'price': price
                }

            except Exception as e:
                logger.warning(f"模型 {current_model} 调用失败: {e}")
                last_error = e
                continue # 尝试下一个模型

        # 如果所有模型都失败
        logger.error(f"所有模型尝试均失败，最后错误: {last_error}")
        return {'action': 'HOLD', 'quantity': 0, 'reason': f"系统繁忙/模型额度耗尽", 'price': price}

import logging
import datetime
import math
import random

logger = logging.getLogger(__name__)

class PaperTrader:
    def __init__(self, initial_cash=100000.0, commission=0.0003, stamp_duty=0.001, slippage=0.001):
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.portfolio = {} # {symbol: {'quantity': int, 'avg_cost': float, 'entry_date': date}}
        self.history = []
        self.commission_rate = commission
        self.stamp_duty_rate = stamp_duty
        self.slippage_rate = slippage # 滑点系数

    def execute(self, symbol: str, decision: dict, current_date: datetime.date = None):
        """
        执行交易指令 (严格执行 A 股 T+1 和滑点模拟)
        """
        action = decision.get('action')
        raw_quantity = decision.get('quantity', 0)
        price = decision.get('price')
        reason = decision.get('reason', '')
        
        if not current_date:
            current_date = datetime.date.today()

        if not price or price <= 0:
            return False

        # 模拟滑点：买入价偏高，卖出价偏低
        if action == 'BUY':
            exec_price = price * (1 + self.slippage_rate)
            quantity = math.floor(raw_quantity / 100) * 100
            if quantity == 0: return False

            trade_amount = exec_price * quantity
            fee = max(5.0, trade_amount * self.commission_rate)
            total_cost = trade_amount + fee

            if self.cash >= total_cost:
                self.cash -= total_cost
                if symbol not in self.portfolio:
                    self.portfolio[symbol] = {'quantity': 0, 'avg_cost': 0.0, 'entry_date': current_date}
                
                old_qty = self.portfolio[symbol]['quantity']
                old_cost = self.portfolio[symbol]['avg_cost']
                new_qty = old_qty + quantity
                # 更新平均成本
                self.portfolio[symbol]['avg_cost'] = ((old_qty * old_cost) + total_cost) / new_qty
                self.portfolio[symbol]['quantity'] = new_qty
                # 重要：记录最后买入日期用于 T+1 检查
                self.portfolio[symbol]['entry_date'] = current_date
                
                self._log_trade(symbol, 'BUY', exec_price, quantity, fee, 0, reason, current_date)
                return True
            return False

        elif action == 'SELL':
            holding = self.portfolio.get(symbol)
            if not holding or holding['quantity'] <= 0: return False
            
            # --- T+1 规则检查 ---
            # 如果买入日期和当前交易日期是同一天，不允许卖出
            if holding['entry_date'] == current_date:
                # logger.info(f"T+1 限制: {symbol} 今日买入，不可卖出")
                return False

            exec_price = price * (1 - self.slippage_rate)
            quantity = min(raw_quantity, holding['quantity'])
            if quantity == 0: return False

            trade_amount = exec_price * quantity
            fee = max(5.0, trade_amount * self.commission_rate)
            tax = trade_amount * self.stamp_duty_rate
            total_income = trade_amount - fee - tax
            
            self.cash += total_income
            self.portfolio[symbol]['quantity'] -= quantity
            if self.portfolio[symbol]['quantity'] == 0:
                del self.portfolio[symbol]
                
            self._log_trade(symbol, 'SELL', exec_price, quantity, fee, tax, reason, current_date)
            return True
        
        return False

    def _log_trade(self, symbol, action, price, quantity, commission, tax, reason, trade_date):
        record = {
            'date': trade_date.strftime('%Y-%m-%d') if hasattr(trade_date, 'strftime') else str(trade_date),
            'symbol': symbol,
            'action': action,
            'price': price,
            'quantity': quantity,
            'fees': commission + tax,
            'reason': reason,
            'cash_after': self.cash
        }
        self.history.append(record)
        logger.info(f"[{record['date']}] 成交: {action} {symbol} {quantity}股 @ {price:.3f}")

    def get_portfolio_value(self, current_prices: dict):
        market_value = 0.0
        for symbol, data in self.portfolio.items():
            price = current_prices.get(symbol, 0)
            market_value += data['quantity'] * price
        return self.cash + market_value

    def status_report(self):
        report = f"\n=== 账户快照 ===\n现金: {self.cash:.2f}\n"
        for sym, data in self.portfolio.items():
            report += f"持仓: {sym} {data['quantity']}股 | 成本: {data['avg_cost']:.3f}\n"
        return report

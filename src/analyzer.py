import pandas as pd
import ta
import logging

logger = logging.getLogger(__name__)

class TechnicalAnalyzer:
    def __init__(self):
        pass

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        添加技术分析指标到DataFrame
        """
        if df is None or df.empty:
            logger.warning("DataFrame为空，无法计算指标")
            return df

        df = df.copy()

        try:
            # 1. 移动平均线 (Simple Moving Average)
            # 使用 ta 库的 trend 模块
            df['SMA_5'] = ta.trend.SMAIndicator(close=df['Close'], window=5).sma_indicator()
            df['SMA_10'] = ta.trend.SMAIndicator(close=df['Close'], window=10).sma_indicator()
            df['SMA_20'] = ta.trend.SMAIndicator(close=df['Close'], window=20).sma_indicator()
            df['SMA_60'] = ta.trend.SMAIndicator(close=df['Close'], window=60).sma_indicator()

            # 2. 相对强弱指数 (RSI)
            df['RSI'] = ta.momentum.RSIIndicator(close=df['Close'], window=14).rsi()

            # 3. MACD
            macd = ta.trend.MACD(close=df['Close'])
            df['MACD_12_26_9'] = macd.macd()
            df['MACDh_12_26_9'] = macd.macd_diff()
            df['MACDs_12_26_9'] = macd.macd_signal()
            
            # 4. 布林带 (Bollinger Bands)
            bb = ta.volatility.BollingerBands(close=df['Close'], window=20, window_dev=2)
            df['BBL_20_2.0'] = bb.bollinger_lband()
            df['BBM_20_2.0'] = bb.bollinger_mavg()
            df['BBU_20_2.0'] = bb.bollinger_hband()

            # 5. ATR (用于计算止损)
            df['ATR'] = ta.volatility.AverageTrueRange(high=df['High'], low=df['Low'], close=df['Close'], window=14).average_true_range()
            
            # 6. ADX (趋势强度，用于过滤震荡)
            adx = ta.trend.ADXIndicator(high=df['High'], low=df['Low'], close=df['Close'], window=14)
            df['ADX'] = adx.adx()
            
            # 7. CCI (顺势指标) - 捕捉极端超买超卖
            cci = ta.trend.CCIIndicator(high=df['High'], low=df['Low'], close=df['Close'], window=20)
            df['CCI'] = cci.cci()

            # 8. VWAP (成交量加权平均价) - 机构交易核心参考
            # 简单近似: (High + Low + Close) / 3 * Volume 的累加 / Volume 的累加
            # 注意: 标准 VWAP 是日内指标，这里我们计算一个“滚动周期 VWAP”作为参考，例如 20日
            v = df['Volume']
            tp = (df['High'] + df['Low'] + df['Close']) / 3
            df['VWAP'] = (tp * v).rolling(window=20).sum() / v.rolling(window=20).sum()

            # 9. KDJ (随机指标) - 使用 Stochastic Oscillator
            stoch = ta.momentum.StochasticOscillator(high=df['High'], low=df['Low'], close=df['Close'], window=9, smooth_window=3)
            df['K'] = stoch.stoch()
            df['D'] = stoch.stoch_signal()
            # J线通常是 3K - 2D
            df['J'] = 3 * df['K'] - 2 * df['D']
            
            # 清理无效值
            df.fillna(method='bfill', inplace=True)
            df.fillna(method='ffill', inplace=True)
            
            logger.info("技术指标计算完成")
            return df

        except Exception as e:
            logger.error(f"计算技术指标时出错: {e}")
            return df
    
    def get_latest_signals(self, df: pd.DataFrame):
        """
        提取最后一行的信号用于决策
        """
        if df is None or df.empty:
            return None
        
        return df.iloc[-1].to_dict()

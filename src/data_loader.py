import akshare as ak
import pandas as pd
import logging
import os
import requests
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class MarketDataLoader:
    def __init__(self, data_dir="data"):
        self.data_dir = data_dir
        if not os.path.exists(data_dir):
            os.makedirs(data_dir)

    def get_stock_name(self, symbol: str) -> str:
        """
        获取股票中文名称 (使用新浪接口加速)
        """
        try:
            # 优先尝试新浪实时接口解析名称，速度最快
            sina_code = f"sh{symbol}" if symbol.startswith(('6', '5', '7')) else f"sz{symbol}"
            try:
                url = f"http://hq.sinajs.cn/list={sina_code}"
                resp = requests.get(url, headers={'Referer': 'http://finance.sina.com.cn'}, timeout=2)
                if resp.status_code == 200 and "=\"" in resp.text:
                    # 解析 var hq_str_sh600519="贵州茅台,..."
                    data_str = resp.text.split('="')[1].split('";')[0]
                    if data_str:
                        return data_str.split(',')[0]
            except:
                pass

            # 回退到 AkShare
            df = ak.stock_individual_info_em(symbol=symbol)
            if not df.empty:
                name_row = df[df['item'] == '股票名称']
                if not name_row.empty:
                    return name_row.iloc[0]['value']
            
            return symbol
        except Exception as e:
            logger.error(f"获取股票名称失败: {e}")
            return symbol

    def fetch_history(self, symbol: str, period="2y", interval="1d"):
        """
        获取历史数据 (增强版：AkShare -> 腾讯财经备用)
        """
        # 1. 优先尝试 AkShare (为了保持数据格式一致性)
        try:
            logger.info(f"正在使用 AkShare 获取 {symbol} 的数据...")
            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=730)).strftime("%Y%m%d") 
            
            df = None
            if symbol.startswith(('51', '56', '58', '15')): # ETF
                try:
                    df = ak.fund_etf_hist_em(symbol=symbol, period="daily", start_date=start_date, end_date=end_date, adjust="qfq")
                    rename_map = {'日期': 'Date', '开盘': 'Open', '收盘': 'Close', '最高': 'High', '最低': 'Low', '成交量': 'Volume'}
                    df = df.rename(columns=rename_map)
                except:
                    pass

            if df is None: # A股
                try:
                    df = ak.stock_zh_a_hist(symbol=symbol, period="daily", start_date=start_date, end_date=end_date, adjust="qfq")
                    rename_map = {'日期': 'Date', '开盘': 'Open', '收盘': 'Close', '最高': 'High', '最低': 'Low', '成交量': 'Volume'}
                    df = df.rename(columns=rename_map)
                except:
                    pass

            if df is not None and not df.empty:
                df['Date'] = pd.to_datetime(df['Date'])
                df.set_index('Date', inplace=True)
                cols = ['Open', 'High', 'Low', 'Close', 'Volume']
                for col in cols:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col])
                return df
                
        except Exception as e:
            logger.warning(f"AkShare 获取历史数据失败: {e}")

        # 2. 备用方案：腾讯财经 (极速且稳定)
        logger.info(f"切换至腾讯财经接口获取 {symbol} 历史数据...")
        try:
            # 构造代码 sh/sz
            prefix = "sh" if symbol.startswith(('6', '5', '900')) else "sz"
            code = f"{prefix}{symbol}"
            # 腾讯接口: get?param={code},day,,,{count},qfq
            # 获取最近 640 天 (约2年)
            url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,640,qfq"
            
            resp = requests.get(url, timeout=3)
            if resp.status_code != 200:
                return None
                
            data = resp.json()
            # 解析路径: data -> {code} -> day
            # 数据格式: [date, open, close, high, low, volume, ...]
            # 腾讯返回的 day 列表里可能包含前复权的额外信息，我们只取前6个
            if 'data' not in data or code not in data['data']:
                return None
                
            k_data = data['data'][code].get('day', [])
            if not k_data:
                return None
                
            records = []
            for item in k_data:
                if len(item) < 6: continue
                records.append({
                    'Date': pd.to_datetime(item[0]),
                    'Open': float(item[1]),
                    'Close': float(item[2]),
                    'High': float(item[3]),
                    'Low': float(item[4]),
                    'Volume': float(item[5])
                })
                
            if not records:
                return None
                
            df = pd.DataFrame(records)
            df.set_index('Date', inplace=True)
            return df
            
        except Exception as e:
            logger.error(f"腾讯接口获取历史数据失败: {e}")
            return None

    def get_realtime_snapshot(self, symbols):
        """
        获取实时行情快照 (支持单只或批量，推荐批量)
        返回字典: {symbol: {price, open, high, low, volume, bid1_vol, ask1_vol}}
        """
        if isinstance(symbols, str):
            symbols = [symbols]
            
        results = {}
        
        # 新浪接口一次最多支持约 80-100 个代码，这里分批处理
        chunk_size = 50
        for i in range(0, len(symbols), chunk_size):
            chunk = symbols[i:i+chunk_size]
            sina_codes = []
            code_map = {} # sina_code -> original_symbol
            
            for sym in chunk:
                prefix = "sh" if sym.startswith(('6', '5', '900')) else "sz"
                s_code = f"{prefix}{sym}"
                sina_codes.append(s_code)
                code_map[s_code] = sym
                
            try:
                url = f"http://hq.sinajs.cn/list={','.join(sina_codes)}"
                headers = {'Referer': 'http://finance.sina.com.cn'}
                
                resp = requests.get(url, headers=headers, timeout=3)
                if resp.status_code != 200:
                    continue
                
                content = resp.text
                lines = content.split('\n')
                
                for line in lines:
                    if '="' not in line: continue
                    
                    # var hq_str_sh600519="xxx"
                    left, right = line.split('="')
                    s_code = left.split('hq_str_')[-1]
                    data_str = right.split('";')[0]
                    
                    if not data_str or s_code not in code_map: continue
                    
                    fields = data_str.split(',')
                    if len(fields) < 30: continue
                    
                    symbol = code_map[s_code]
                    
                    try:
                        price = float(fields[3])
                        pre_close = float(fields[2])
                        open_p = float(fields[1])
                        
                        # 停牌或集合竞价处理
                        if price == 0: price = pre_close
                        if open_p == 0: open_p = pre_close
                        
                        results[symbol] = {
                            'price': price,
                            'open': open_p,
                            'high': float(fields[4]) or price,
                            'low': float(fields[5]) or price,
                            'volume': float(fields[8]),
                            'amount': float(fields[9]),
                            # 盘口数据 (买一量/卖一量，单位：股)
                            'bid1_vol': float(fields[10]),
                            'bid1_price': float(fields[11]),
                            'ask1_vol': float(fields[20]),
                            'ask1_price': float(fields[21]),
                            'date': fields[30],
                            'time': fields[31]
                        }
                    except (ValueError, IndexError):
                        continue
                        
            except Exception as e:
                logger.error(f"批量获取行情失败: {e}")
                
        return results if len(symbols) > 1 else results.get(symbols[0])

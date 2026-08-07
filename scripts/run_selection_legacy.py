import os
import sys
import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import akshare as ak
import warnings
warnings.filterwarnings('ignore')

# ==================== 配置参数（可调） ====================
TARGET_RETURN = 0.05      # 目标收益率 5%
STOP_LOSS_PCT = 0.02     # 止损线 2%
HOLD_DAYS = 5            # 持有天数
MIN_MARKET_CAP = 50      # 最小市值（亿）
MIN_VOLUME = 5000        # 最小成交额（万元）
MIN_PRICE = 3            # 最低价格
MAX_PRICE = 100          # 最高价格
MAX_CONSECUTIVE_DOWN = 3 # 最大连续下跌天数
MAX_AMPLITUDE = 0.08     # 最大振幅 8%
MAX_DAILY_CHANGE = 0.05  # 当日最大涨幅 5%
MIN_CHANGE_5D = 0.0      # 5日最小涨幅 0%
MIN_CHANGE_20D = 0.03    # 20日最小涨幅 3%
MIN_ATR = 0.01           # 最小ATR比率 1%
MAX_ATR = 0.05           # 最大ATR比率 5%（原3%放宽至5%）
MAX_MA20_DEVIATION = 0.03 # MA20最大偏离 3%

# ==================== 路径处理 ====================
def get_project_root():
    """获取项目根目录（无论从哪里执行）"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def ensure_results_dir():
    """确保results目录存在"""
    results_dir = os.path.join(get_project_root(), "results")
    os.makedirs(results_dir, exist_ok=True)
    return results_dir

# ==================== 数据获取（增强容错） ====================
def get_stock_list():
    """获取股票列表，过滤科创板(688)、北交所(8/4开头)"""
    try:
        # 尝试获取A股列表
        stock_info = ak.stock_info_a_code_name()
        # 过滤：剔除科创板(688)、北交所(8/4开头)
        stock_info = stock_info[~stock_info['code'].str.startswith(('688', '8', '4'))]
        return stock_info['code'].tolist()
    except Exception as e:
        print(f"获取股票列表失败: {e}")
        # 备用方案：使用本地缓存或手动指定沪深300等
        return get_fallback_stock_list()

def get_fallback_stock_list():
    """备用股票列表（沪深300成分股）"""
    try:
        df = ak.index_stock_cons_csindex("000300")
        return df['成分券代码'].tolist()
    except:
        print("备用列表也失败了，请检查网络")
        sys.exit(1)

def get_stock_data(code, start_date, end_date):
    """获取单只股票历史数据，带重试"""
    for attempt in range(3):
        try:
            df = ak.stock_zh_a_hist(
                symbol=code,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust="qfq"  # 前复权
            )
            if df is not None and not df.empty:
                # 标准化列名
                df.columns = ['日期', '开盘', '收盘', '最高', '最低', '成交量', '成交额', '振幅', 
                              '涨跌幅', '涨跌额', '换手率']
                return df
        except Exception as e:
            print(f"获取 {code} 数据失败 (尝试 {attempt+1}/3): {e}")
            continue
    return None

# ==================== 核心选股逻辑 ====================
def calculate_metrics(df):
    """计算技术指标"""
    if df is None or len(df) < 20:
        return None
    
    df = df.copy()
    
    # 计算均线
    df['MA20'] = df['收盘'].rolling(window=20).mean()
    df['MA30'] = df['收盘'].rolling(window=30).mean()
    
    # 计算ATR (平均真实波幅)
    df['TR'] = np.maximum(
        df['最高'] - df['最低'],
        np.maximum(
            abs(df['最高'] - df['收盘'].shift()),
            abs(df['最低'] - df['收盘'].shift())
        )
    )
    df['ATR'] = df['TR'].rolling(window=5).mean()
    
    # 计算涨跌幅
    df['change_5d'] = (df['收盘'] - df['收盘'].shift(5)) / df['收盘'].shift(5)
    df['change_20d'] = (df['收盘'] - df['收盘'].shift(20)) / df['收盘'].shift(20)
    
    # 量比（5日均量/20日均量）
    df['volume_ma5'] = df['成交量'].rolling(window=5).mean()
    df['volume_ma20'] = df['成交量'].rolling(window=20).mean()
    df['volume_ratio'] = df['volume_ma5'] / df['volume_ma20']
    
    return df

def check_criteria(df, idx):
    """检查单日是否符合所有筛选条件"""
    if idx < 20:
        return False, {}
    
    row = df.iloc[idx]
    prev_row = df.iloc[idx-1] if idx > 0 else row
    
    # 1. 基础筛选（价格、成交额）
    if not (MIN_PRICE <= row['收盘'] <= MAX_PRICE):
        return False, {}
    if row['成交额'] < MIN_VOLUME * 10000:  # 转为元
        return False, {}
    
    # 2. 排除规则
    # 连续下跌
    down_days = 0
    for i in range(idx-1, max(idx-5, -1), -1):
        if df.iloc[i]['涨跌幅'] < 0:
            down_days += 1
        else:
            break
    if down_days >= MAX_CONSECUTIVE_DOWN:
        return False, {}
    
    # 涨停/跌停（简化判断）
    if row['涨跌幅'] >= 0.095 or row['涨跌幅'] <= -0.095:
        return False, {}
    if row['振幅'] > MAX_AMPLITUDE * 100:  # akshare振幅单位是%
        return False, {}
    if row['涨跌幅'] > MAX_DAILY_CHANGE * 100:
        return False, {}
    
    # 3. 动量确认
    if row['change_5d'] < MIN_CHANGE_5D:
        return False, {}
    if row['change_20d'] < MIN_CHANGE_20D:
        return False, {}
    if row['volume_ratio'] < 1.0:  # 量能不萎缩
        return False, {}
    
    # 4. 波动率适配（ATR相对于价格）
    atr_ratio = row['ATR'] / row['收盘']
    if not (MIN_ATR <= atr_ratio <= MAX_ATR):
        return False, {}
    
    # 5. 趋势支撑
    if row['收盘'] < row['MA20']:
        return False, {}
    if abs(row['收盘'] / row['MA20'] - 1) > MAX_MA20_DEVIATION:
        return False, {}
    if row['MA30'] <= df.iloc[idx-5]['MA30']:  # MA30斜率向上
        return False, {}
    
    # 6. 综合评分
    score = 0
    score += min(row['change_5d'] * 50, 20)  # 5日涨幅
    score += min(row['change_20d'] * 30, 15)  # 20日涨幅
    score += min(row['volume_ratio'] * 5, 10)  # 量比
    score += min((atr_ratio - MIN_ATR) * 200, 10)  # ATR适中
    score += 10 if row['收盘'] > row['MA30'] else 0  # 站上MA30
    score += (1 - abs(row['收盘']/row['MA20'] - 1) * 50) * 5  # MA20偏离
    score = max(0, min(100, score))
    
    return True, {
        'score': round(score, 2),
        'close': row['收盘'],
        'change_5d': round(row['change_5d'] * 100, 2),
        'change_20d': round(row['change_20d'] * 100, 2),
        'atr_ratio': round(atr_ratio * 100, 2),
        'volume_ratio': round(row['volume_ratio'], 2),
        'ma20': round(row['MA20'], 2),
        'ma30': round(row['MA30'], 2),
        'amplitude': round(row['振幅'], 2)
    }

def run_selection():
    """主选股流程"""
    print(f"开始选股: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 确保目录存在
    ensure_results_dir()
    
    # 设置日期范围（获取最近60天数据用于计算）
    end_date = datetime.now().strftime('%Y%m%d')
    start_date = (datetime.now() - timedelta(days=90)).strftime('%Y%m%d')
    
    # 获取股票列表
    print("获取股票列表...")
    stock_codes = get_stock_list()
    print(f"共 {len(stock_codes)} 只股票待筛选")
    
    results = []
    failed_count = 0
    
    for i, code in enumerate(stock_codes):
        if i % 100 == 0:
            print(f"进度: {i}/{len(stock_codes)}")
        
        # 获取数据
        df = get_stock_data(code, start_date, end_date)
        if df is None or len(df) < 20:
            failed_count += 1
            continue
        
        # 计算指标
        df = calculate_metrics(df)
        if df is None:
            continue
        
        # 最新交易日
        idx = len(df) - 1
        
        # 检查条件
        passed, metrics = check_criteria(df, idx)
        if not passed:
            continue
        
        # 获取股票名称
        try:
            name = ak.stock_individual_info_em(symbol=code)['股票名称'].values[0]
        except:
            name = code
        
        # 计算买卖价
        buy_price = round(metrics['close'] * (1 - STOP_LOSS_PCT), 2)  # 低吸挂单（注意：原策略是-0.5%，这里我改成-2%与止损对应，你可以改回）
        sell_price = round(buy_price * (1 + TARGET_RETURN), 2)
        stop_price = round(buy_price * (1 - STOP_LOSS_PCT), 2)
        
        results.append({
            'code': code,
            'name': name,
            'buy_price': buy_price,
            'sell_price': sell_price,
            'stop_price': stop_price,
            'hold_days': HOLD_DAYS,
            'score': metrics['score'],
            'metrics': {
                '5日涨幅': f"{metrics['change_5d']}%",
                '20日涨幅': f"{metrics['change_20d']}%",
                'ATR比率': f"{metrics['atr_ratio']}%",
                '量比': metrics['volume_ratio'],
                'MA20': metrics['ma20'],
                'MA30': metrics['ma30'],
                '振幅': f"{metrics['amplitude']}%",
                '收盘价': metrics['close']
            },
            'detail': f"站上MA20, MA30向上, 5日{metrics['change_5d']}%, 20日{metrics['change_20d']}%, ATR{metrics['atr_ratio']}%"
        })
        
        # 只取前10只
        if len(results) >= 10:
            break
    
    # 按分数排序
    results = sorted(results, key=lambda x: x['score'], reverse=True)[:10]
    
    print(f"筛选完成: 成功分析 {len(stock_codes) - failed_count} 只, 选出 {len(results)} 只")
    print(f"失败/无数据: {failed_count} 只")
    
    # 保存结果
    output_file = os.path.join(
        get_project_root(), 
        "results", 
        f"selection_{datetime.now().strftime('%Y%m%d')}.json"
    )
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump({
            'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'total_analyzed': len(stock_codes) - failed_count,
            'selected_count': len(results),
            'stocks': results
        }, f, ensure_ascii=False, indent=2)
    
    print(f"结果已保存至: {output_file}")
    
    # 打印结果摘要
    if results:
        print("\n=== 选股结果 ===")
        for r in results:
            print(f"{r['code']} {r['name']} | 评分: {r['score']} | 买入: {r['buy_price']} 卖出: {r['sell_price']}")
    else:
        print("\n今日无符合条件的股票（空仓等待）")
    
    return results

# ==================== 入口 ====================
if __name__ == "__main__":
    try:
        run_selection()
    except Exception as e:
        print(f"程序运行出错: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

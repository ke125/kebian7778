import requests
import pandas as pd
import matplotlib.pyplot as plt
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# ----------------------
# 微信推送配置（Server酱）
# ----------------------
def send_wechat_notification(symbol, price, reason):
    """发送微信提醒（Server酱）"""
    url = "https://sctapi.ftqq.com/SCT32178TyIsGaxv6UsK7LUndka8fjg5.send"
    content = (
        f"📈 **检测到震荡突破信号！**\n\n"
        f"💰 币种: {symbol}\n"
        f"💎 价格: {price:.6f}\n"
        f"📊 信号原因: {reason}\n"
        f"⏰ 时间: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        f"✅ 状态：33日均线附近震荡 | 未跌破前低 | 放量突破阻力"
    )
    try:
        resp = requests.get(url, params={"title": f"【震荡突破】{symbol}", "desp": content}, timeout=8)
        resp.raise_for_status()
        print(f"✅ 微信提醒发送成功: {symbol}")
    except Exception as e:
        print(f"❌ 微信发送失败: {e}")

# ----------------------
# 1. 获取全部U本位永续合约
# ----------------------
def get_perpetual_symbols():
    url = "https://fapi.binance.com/fapi/v1/exchangeInfo"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        symbols = [
            s["symbol"] for s in data["symbols"]
            if s["contractType"] == "PERPETUAL"
            and s["status"] == "TRADING"
            and s["quoteAsset"] == "USDT"
        ]
        print(f"✅ 扫描范围: {len(symbols)} 个U本位合约")
        return symbols
    except Exception as e:
        print(f"❌ 获取合约失败: {e}")
        return []

# ----------------------
# 2. 获取4小时K线 + 2次重试（共3次）
# ----------------------
def get_4h_klines(symbol, limit=100):
    url = "https://fapi.binance.com/fapi/v1/klines"
    params = {"symbol": symbol, "interval": "4h", "limit": limit}
    for retry in range(3):
        try:
            resp = requests.get(url, params=params, timeout=12)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            if retry < 2:
                time.sleep(1.5)
                continue
            print(f"⚠️ {symbol} 获取K线失败（已重试3次）")
            return []

# ----------------------
# 3. 计算指标
# ----------------------
def calc_indicators(df):
    df["close"] = pd.to_numeric(df["close"])
    df["high"] = pd.to_numeric(df["high"])
    df["low"] = pd.to_numeric(df["low"])
    df["volume"] = pd.to_numeric(df["volume"])

    df["MA5"] = df["close"].rolling(5).mean()
    df["MA10"] = df["close"].rolling(10).mean()
    df["MA33"] = df["close"].rolling(33).mean()
    df["VOL_MA5"] = df["volume"].rolling(5).mean()

    exp1 = df["close"].ewm(span=12, adjust=False).mean()
    exp2 = df["close"].ewm(span=26, adjust=False).mean()
    df["DIF"] = exp1 - exp2
    df["DEA"] = df["DIF"].ewm(span=9, adjust=False).mean()
    df["MACD"] = (df["DIF"] - df["DEA"]) * 2
    return df

# ----------------------
# 4. ✅ 核心新形态：33日均线震荡 + 未跌破前低 + 放量突破阻力
# 核心逻辑：
# 1. 价格在MA33附近震荡（收盘价在MA33的±15%区间内）
# 2. 最近未跌破前期重要低点（最近30根K线的最低价 ≥ 前期低点的98%）
# 3. 放量突破关键阻力（突破前20根K线高点，且成交量≥5日均量的1.3倍）
# 4. 过滤暴涨：MA5 ≤ MA10×1.1（防止像PIXEL这种已经涨太多的）
# ----------------------
def match_oscillation_breakout(df):
    if len(df) < 33:
        return False

    last = df.iloc[-1]
    # 最近30根K线数据
    recent_30 = df.iloc[-30:]

    # 1. 价格在MA33附近震荡（±15%）
    near_ma33 = (last["close"] >= last["MA33"] * 0.85) and (last["close"] <= last["MA33"] * 1.15)

    # 2. 未跌破前期低点：最近30根K线的最低价 ≥ 前期低点（最近100根）的98%
    all_time_low = df["low"].min()
    recent_low = recent_30["low"].min()
    not_broke_low = (recent_low >= all_time_low * 0.98)

    # 3. 突破关键阻力：突破前20根K线高点
    key_resistance = df["high"].iloc[-20:-1].max()
    break_resistance = (last["close"] > key_resistance)

    # 4. 明显放量：成交量 ≥ 5日均量的1.3倍
    strong_volume = (last["volume"] >= last["VOL_MA5"] * 1.3)

    # 5. 过滤暴涨：MA5 不高于 MA10 的1.1倍（避免追高）
    ma_not_too_far = (last["MA5"] <= last["MA10"] * 1.1)

    # ✅ 综合判定
    return near_ma33 and not_broke_low and break_resistance and strong_volume and ma_not_too_far

# ----------------------
# 5. 画图函数
# ----------------------
def plot_chart(symbol, df, filename):
    try:
        fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(12, 10), sharex=True)
        
        # 价格与均线
        ax1.plot(df["close"], label="价格", color="#1f77b4", linewidth=1.5)
        ax1.plot(df["MA5"], label="MA5", color="#ff7f0e", linewidth=1.2)
        ax1.plot(df["MA10"], label="MA10", color="#2ca02c", linewidth=1.2)
        ax1.plot(df["MA33"], label="MA33", color="#d62728", linewidth=1.2)
        ax1.set_title(f"{symbol} 4H 震荡突破分析", fontsize=14)
        ax1.legend(loc="upper left")
        ax1.grid(alpha=0.3)

        # MACD
        ax2.bar(df.index, df["MACD"], label="MACD", color=df["MACD"].apply(lambda x: "#2ca02c" if x>0 else "#d62728"), alpha=0.6)
        ax2.plot(df["DIF"], label="DIF", color="#1f77b4")
        ax2.plot(df["DEA"], label="DEA", color="#ff7f0e")
        ax2.legend(loc="upper left")
        ax2.grid(alpha=0.3)

        # 成交量
        ax3.bar(df.index, df["volume"], label="成交量", color="#1f77b4", alpha=0.7)
        ax3.plot(df["VOL_MA5"], label="VOL_MA5", color="#ff7f0e")
        ax3.legend(loc="upper left")
        ax3.grid(alpha=0.3)

        plt.tight_layout()
        plt.savefig(filename, dpi=150, bbox_inches="tight")
        plt.close()
    except Exception as e:
        print(f"⚠️ 画图失败: {e}")

# ----------------------
# 6. 主程序入口（15线程 + 收盘后5分钟 + 匹配上限10）
# ----------------------
if __name__ == "__main__":
    symbols = get_perpetual_symbols()
    if not symbols:
        print("❌ 未获取到合约列表，退出任务")
        exit()

    count = 0
    matched_symbols = []
    print(f"\n开始扫描全市场 U 本位合约...\n")

    # 15线程并行扫描
    with ThreadPoolExecutor(max_workers=15) as executor:
        future_to_symbol = {executor.submit(get_4h_klines, s): s for s in symbols}
        
        for future in as_completed(future_to_symbol):
            symbol = future_to_symbol[future]
            klines = future.result()
            
            if not klines:
                continue
            
            try:
                df = pd.DataFrame(klines, columns=[
                    "t","o","h","l","c","v","1","2","3","4","5","6"
                ])
                df = calc_indicators(df)
                
                # 只检测新形态：33日均线震荡 + 未跌破前低 + 放量突破
                if match_oscillation_breakout(df):
                    last_price = float(df["close"].iloc[-1])
                    reason = "✅ 33日均线震荡 | 未跌破前低 | 放量突破阻力"
                    
                    plot_chart(symbol, df, f"match_{symbol}.png")
                    send_wechat_notification(symbol, last_price, reason)
                    
                    matched_symbols.append(symbol)
                    count += 1
                    if count >= 10: # 上限10个
                        break
            except Exception as e:
                # 容错：防止单个币种数据错误导致整个任务挂掉
                continue

    print(f"\n扫描结束！本次匹配到 {count} 个震荡突破币种: {matched_symbols}")

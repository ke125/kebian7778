import requests
import pandas as pd
import matplotlib.pyplot
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# ----------------------
# 微信推送配置（Server酱）
# ----------------------
def send_wechat_notification(symbol, price):
    """发送微信提醒（Server酱）"""
    url = "https://sctapi.ftqq.com/SCT321178TyIsGaxv6Us5K7LUndka8fjg5.send"
    content = f"📈 发现匹配币种！\n币种: {symbol}\n当前价格: {price:.4f}\n时间: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}"
    try:
        resp = requests.get(url, params={"title": "币安4H形态提醒", "desp": content}, timeout=5)
        resp.raise_for_status()
        print(f"✅ 微信提醒已发送: {symbol}")
    except Exception as e:
        print(f"❌ 微信提醒发送失败: {e}")

# ----------------------
# 1. 币安 API 工具函数（获取全部U本位永续合约）
# ----------------------
def get_perpetual_symbols():
    """获取所有U本位永续合约币种列表"""
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
        print(f"✅ 成功获取 {len(symbols)} 个 USDT 永续合约")
        return symbols
    except Exception as e:
        print(f"❌ 获取合约列表失败: {e}")
        return []

def get_4h_klines(symbol, limit=100):
    """获取币种4小时K线数据"""
    url = "https://fapi.binance.com/fapi/v1/klines"
    params = {
        "symbol": symbol,
        "interval": "4h",
        "limit": limit
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"⚠️ {symbol} 获取K线失败: {e}")
        return []

# ----------------------
# 2. 指标计算函数
# ----------------------
def calc_indicators(df):
    """计算 MA5/MA10/MA33、MACD 等指标"""
    df["MA5"] = df["close"].rolling(5).mean()
    df["MA10"] = df["close"].rolling(10).mean()
    df["MA33"] = df["close"].rolling(33).mean()
    
    exp1 = df["close"].ewm(span=12, adjust=False).mean()
    exp2 = df["close"].ewm(span=26, adjust=False).mean()
    df["DIF"] = exp1 - exp2
    df["DEA"] = df["DIF"].ewm(span=9, adjust=False).mean()
    df["MACD"] = (df["DIF"] - df["DEA"]) * 2
    
    df["VOL_MA5"] = df["volume"].rolling(5).mean()
    return df

# ----------------------
# 3. 形态匹配函数（你原来的 1 或 2 条件）
# ----------------------
def match_all_patterns(df):
    """判断是否符合形态1或形态2"""
    if len(df) < 33:
        return False
    
    last = df.iloc[-1]
    prev = df.iloc[-2]
    
    ma_bull = (last["MA5"] >= last["MA10"] * 0.995) and (last["MA10"] > last["MA33"])
    price_above_ma = (last["close"] > last["MA5"]) or (last["close"] > last["MA10"])
    macd_bull = (last["DIF"] > last["DEA"]) or (prev["DIF"] < prev["DEA"] and last["DIF"] > last["DEA"])
    volume_break = (last["volume"] > last["VOL_MA5"] * 1.2)
    price_break = (last["close"] > df["high"].iloc[-10:-1].max())
    
    pattern1 = ma_bull and price_above_ma and macd_bull and volume_break and price_break
    pattern2 = (last["close"] < prev["close"]) and (last["DIF"] > prev["DIF"]) and price_break
    
    return pattern1 or pattern2

# ----------------------
# 4. 画图函数
# ----------------------
def plot_chart(symbol, df, filename):
    """生成匹配币种的K线图"""
    fig, (ax_price, ax_macd, ax_vol) = plt.subplots(3, 1, figsize=(12, 10), sharex=True)
    
    ax_price.plot(df.index, df["close"], label="Close", color="#1e90ff")
    ax_price.plot(df.index, df["MA5"], label="MA5", color="#32cd32")
    ax_price.plot(df.index, df["MA10"], label="MA10", color="#ff69b4")
    ax_price.plot(df.index, df["MA33"], label="MA33", color="#ffd700")
    ax_price.set_title(f"{symbol} 4H Chart", fontsize=14)
    ax_price.legend(loc="upper left")
    ax_price.grid(alpha=0.3)
    
    ax_macd.bar(df.index, df["MACD"], label="MACD", color=df["MACD"].apply(lambda x: "#32cd32" if x>0 else "#ff6347"))
    ax_macd.plot(df.index, df["DIF"], label="DIF", color="#00ffff")
    ax_macd.plot(df.index, df["DEA"], label="DEA", color="#ff1493")
    ax_macd.legend(loc="upper left")
    ax_macd.grid(alpha=0.3)
    
    ax_vol.bar(df.index, df["volume"], label="Volume", color="#87ceeb")
    ax_vol.plot(df.index, df["VOL_MA5"], label="VOL_MA5", color="#ff4500")
    ax_vol.legend(loc="upper left")
    ax_vol.grid(alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(filename, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"✅ 匹配成功: {symbol} → 已保存为 {filename}")

# ----------------------
# 5. 主程序（15线程 + 扫全部U本位 + 准确性第一）
# ----------------------
if __name__ == "__main__":
    symbols = get_perpetual_symbols()
    if not symbols:
        print("❌ 无法继续，未获取到合约列表")
        exit()

    count = 0
    matched_symbols = []
    print(f"\n开始扫描全部 {len(symbols)} 个 USDT 永续合约...\n")

    # ======================
    # 你要的：15 线程
    # ======================
    with ThreadPoolExecutor(max_workers=15) as executor:
        future_to_symbol = {executor.submit(get_4h_klines, s): s for s in symbols}
        
        for future in as_completed(future_to_symbol):
            symbol = future_to_symbol[future]
            klines = future.result()
            
            if not klines:
                continue
            
            df = pd.DataFrame(klines, columns=[
                "timestamp", "open", "high", "low", "close", "volume",
                "ignore1", "ignore2", "ignore3", "ignore4", "ignore5", "ignore6"
            ])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            for col in ["open", "high", "low", "close", "volume"]:
                df[col] = pd.to_numeric(df[col])
            df = df.set_index("timestamp")
            df = calc_indicators(df)
            
            if match_all_patterns(df):
                last_price = df["close"].iloc[-1]
                plot_chart(symbol, df, f"match_{symbol}_4h.png")
                send_wechat_notification(symbol, last_price)
                matched_symbols.append(symbol)
                count += 1
                if count >= 10:
                    break

    print(f"\n扫描结束！共匹配 {count} 个币种: {matched_symbols}")

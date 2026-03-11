import requests
import pandas as pd
import matplotlib.pyplot as plt
import time

# ----------------------
# 1. 币安 API 工具函数
# ----------------------
def get_perpetual_symbols():
    """获取所有永续合约币种列表"""
    url = "https://fapi.binance.com/fapi/v1/exchangeInfo"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        symbols = [s["symbol"] for s in data["symbols"] if s["contractType"] == "PERPETUAL" and s["status"] == "TRADING"]
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
    # 计算均线
    df["MA5"] = df["close"].rolling(5).mean()
    df["MA10"] = df["close"].rolling(10).mean()
    df["MA33"] = df["close"].rolling(33).mean()
    
    # 计算 MACD
    exp1 = df["close"].ewm(span=12, adjust=False).mean()
    exp2 = df["close"].ewm(span=26, adjust=False).mean()
    df["DIF"] = exp1 - exp2
    df["DEA"] = df["DIF"].ewm(span=9, adjust=False).mean()
    df["MACD"] = (df["DIF"] - df["DEA"]) * 2
    
    # 计算成交量均线
    df["VOL_MA5"] = df["volume"].rolling(5).mean()
    return df

# ----------------------
# 3. 形态匹配函数（放宽版）
# ----------------------
def match_all_patterns(df):
    """判断是否符合形态1或形态2（放宽条件版）"""
    if len(df) < 33:
        return False  # 数据不足
    
    last = df.iloc[-1]
    prev = df.iloc[-2]
    
    # --- 基础条件（放宽版） ---
    # 1. 均线多头排列（允许 MA5 略低于 MA10，但整体向上）
    ma_bull = (last["MA5"] >= last["MA10"] * 0.995) and (last["MA10"] > last["MA33"])
    # 2. 价格站在 MA5 或 MA10 上方
    price_above_ma = (last["close"] > last["MA5"]) or (last["close"] > last["MA10"])
    # 3. MACD 多头或刚金叉
    macd_bull = (last["DIF"] > last["DEA"]) or (prev["DIF"] < prev["DEA"] and last["DIF"] > last["DEA"])
    # 4. 放量突破（从 1.5 倍放宽到 1.2 倍）
    volume_break = (last["volume"] > last["VOL_MA5"] * 1.2)
    # 5. 价格突破近期高点（从 20 根放宽到 10 根）
    price_break = (last["close"] > df["high"].iloc[-10:-1].max())
    
    # --- 形态判定 ---
    # 形态1：多头突破（放宽版）
    pattern1 = ma_bull and price_above_ma and macd_bull and volume_break and price_break
    # 形态2：底背离 + 突破（简化版）
    pattern2 = (last["close"] < prev["close"]) and (last["DIF"] > prev["DIF"]) and price_break
    
    return pattern1 or pattern2

# ----------------------
# 4. 画图函数
# ----------------------
def plot_chart(symbol, df, filename):
    """生成匹配币种的K线图"""
    fig, (ax_price, ax_macd, ax_vol) = plt.subplots(3, 1, figsize=(12, 10), sharex=True)
    
    # 画价格和均线
    ax_price.plot(df.index, df["close"], label="Close", color="#1e90ff")
    ax_price.plot(df.index, df["MA5"], label="MA5", color="#32cd32")
    ax_price.plot(df.index, df["MA10"], label="MA10", color="#ff69b4")
    ax_price.plot(df.index, df["MA33"], label="MA33", color="#ffd700")
    ax_price.set_title(f"{symbol} 4H Chart", fontsize=14)
    ax_price.legend(loc="upper left")
    ax_price.grid(alpha=0.3)
    
    # 画 MACD
    ax_macd.bar(df.index, df["MACD"], label="MACD", color=df["MACD"].apply(lambda x: "#32cd32" if x>0 else "#ff6347"))
    ax_macd.plot(df.index, df["DIF"], label="DIF", color="#00ffff")
    ax_macd.plot(df.index, df["DEA"], label="DEA", color="#ff1493")
    ax_macd.legend(loc="upper left")
    ax_macd.grid(alpha=0.3)
    
    # 画成交量
    ax_vol.bar(df.index, df["volume"], label="Volume", color="#87ceeb")
    ax_vol.plot(df.index, df["VOL_MA5"], label="VOL_MA5", color="#ff4500")
    ax_vol.legend(loc="upper left")
    ax_vol.grid(alpha=0.3)
    
    # 保存图片
    plt.tight_layout()
    plt.savefig(filename, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"✅ 匹配成功: {symbol} → 已保存为 {filename}")

# ----------------------
# 5. 主程序入口（扫描前700个币种）
# ----------------------
if __name__ == "__main__":
    symbols = get_perpetual_symbols()
    if not symbols:
        print("❌ 无法继续，未获取到合约列表")
        exit()

    count = 0
    matched_symbols = []
    print(f"\n开始扫描 {len(symbols)} 个永续合约，扫描前 700 个...\n")

    # 🔔 这里改成了 symbols[:700]
    for i, symbol in enumerate(symbols[:700]):
        print(f"[{i+1}/700] 正在扫描: {symbol}")
        klines = get_4h_klines(symbol)
        if not klines:
            print(f"⚠️ {symbol} 无K线数据，跳过\n")
            continue
        
        # 整理数据
        df = pd.DataFrame(klines, columns=[
            "timestamp", "open", "high", "low", "close", "volume",
            "ignore1", "ignore2", "ignore3", "ignore4", "ignore5", "ignore6"
        ])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col])
        df = df.set_index("timestamp")
        df = calc_indicators(df)
        
        # 形态匹配
        if match_all_patterns(df):
            plot_chart(symbol, df, f"match_{symbol}_4h.png")
            matched_symbols.append(symbol)
            count += 1
            if count >= 10:
                break
        time.sleep(0.1)  # 避免请求过快被限制

    print(f"\n扫描结束！共匹配 {count} 个币种: {matched_symbols}")

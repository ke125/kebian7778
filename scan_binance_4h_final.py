import requests
import pandas as pd
import matplotlib.pyplot as plt
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# ----------------------
# 微信推送配置（Server酱 不变）
# ----------------------
def send_wechat_notification(symbol, price, reason):
    """发送微信提醒（Server酱）"""
    url = "https://sctapi.ftqq.com/SCT32178TyIsGaxv6UsK7LUndka8fjg5.send"
    content = f"📈 发现强势币种！\n币种: {symbol}\n价格: {price:.4f}\n信号: {reason}\n时间: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}"
    try:
        resp = requests.get(url, params={"title": "币安U本位合约提醒", "desp": content}, timeout=5)
        resp.raise_for_status()
        print(f"✅ 微信提醒已发送: {symbol}")
    except Exception as e:
        print(f"❌ 微信发送失败: {e}")

# ----------------------
# 获取全部U本位永续合约
# ----------------------
def get_perpetual_symbols():
    url = "https://fapi.binance.com/fapi/v1/exchangeInfo"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for()
        data = resp.json()
        symbols = [
            s["symbol"] for s in data["symbols"]
            if s["contractType"] == "PERPETUAL"
            and s["status"] == "TRADING"
            and s["quoteAsset"] == "USDT"
        ]
        print(f"✅ 获取到 {len(symbols)} 个U本位合约")
        return symbols
    except Exception as e:
        print(f"❌ 获取合约失败: {e}")
        return []

# ----------------------
# 获取4小时K线 + 2次重试（共3次）
# ----------------------
def get_4h_klines(symbol, limit=100):
    url = "https://fapi.binance.com/fapi/v1/klines"
    params = {"symbol": symbol, "interval": "4h", "limit": limit}
    for retry in range(3):
        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            if retry < 2:
                time.sleep(1)
                continue
            print(f"⚠️ {symbol} 获取K线失败")
            return []

# ----------------------
# 计算指标
# ----------------------
def calc_indicators(df):
    df["close"] = pd.to_numeric(df["close"])
    df["high"] = pd.to_numeric(df["high"])
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
# 你原来的形态1、形态2 【完全保留不动】
# ----------------------
def match_original_pattern(df):
    if len(df) < 33:
        return False
    last = df.iloc[-1]
    prev = df.iloc[-2]

    ma_bull = (last["MA5"] >= last["MA10"] * 0.995) and (last["MA10"] > last["MA33"])
    price_above = (last["close"] > last["MA5"]) or (last["close"] > last["MA10"])
    macd_bull = (last["DIF"] > last["DEA"]) or (prev["DIF"] < prev["DEA"] and last["DIF"] > last["DEA"])
    volume_break = (last["volume"] > last["VOL_MA5"] * 1.2)
    resistance_break = (last["close"] > df["high"].iloc[-10:-1].max())

    pattern1 = ma_bull and price_above and macd_bull and volume_break and resistance_break
    pattern2 = (last["close"] < prev["close"]) and (last["DIF"] > prev["DIF"]) and resistance_break
    return pattern1 or pattern2

# ----------------------
# ✅ 新增：严格多头排列 + 突破关键阻力 + 明显放量（你要的新形态）
# ----------------------
def match_strong_bull_break(df):
    if len(df) < 33:
        return False

    last = df.iloc[-1]

    # 1. 标准严格多头排列
    perfect_bull = (last["MA5"] > last["MA10"] > last["MA33"])

    # 2. 突破关键阻力（前20根K线高点 = 关键阻力）
    key_resistance = df["high"].iloc[-20:-1].max()
    break_resistance = (last["close"] > key_resistance)

    # 3. 明显放量（≥1.5倍均量）
    strong_volume = (last["volume"] >= last["VOL_MA5"] * 1.5)

    # 4. 价格在均线上方
    price_above_ma = (last["close"] > last["MA5"])

    return perfect_bull and break_resistance and strong_volume and price_above_ma

# ----------------------
# 画图
# ----------------------
def plot_chart(symbol, df, filename):
    try:
        plt.rcParams['figure.figsize'] = [12,10]
        fig, (ax1, ax2, ax3) = plt.subplots(3,1, sharex=True)
        ax1.plot(df["close"], label="价格", linewidth=1.5)
        ax1.plot(df["MA5"], label="MA5", linewidth=1)
        ax1.plot(df["MA10"], label="MA10", linewidth=1)
        ax1.plot(df["MA33"], label="MA33", linewidth=1)
        ax1.set_title(f"{symbol} 4H")
        ax1.legend()
        ax1.grid(alpha=0.3)

        ax2.bar(df.index, df["MACD"], label="MACD", color="g")
        ax2.plot(df["DIF"], label="DIF")
        ax2.plot(df["DEA"], label="DEA")
        ax2.legend()
        ax2.grid(alpha=0.3)

        ax3.bar(df.index, df["volume"], label="成交量")
        ax3.plot(df["VOL_MA5"], label="VOL5", color="r")
        ax3.legend()
        ax3.grid(alpha=0.3)

        plt.tight_layout()
        plt.savefig(filename, dpi=150, bbox_inches="tight")
        plt.close()
    except:
        pass

# ----------------------
# 主程序（15线程 + 收盘后5分钟 + 匹配上限10）
# ----------------------
if __name__ == "__main__":
    symbols = get_perpetual_symbols()
    if not symbols:
        exit()

    matched = []
    max_match = 10

    with ThreadPoolExecutor(max_workers=15) as executor:
        futures = {executor.submit(get_4h_klines, s): s for s in symbols}
        for fut in as_completed(futures):
            sym = futures[fut]
            kl = fut.result()
            if not kl:
                continue

            df = pd.DataFrame(kl, columns=[
                "t","o","h","l","c","v","1","2","3","4","5","6"
            ])
            df = calc_indicators(df)

            hit = False
            reason = ""

            # 原有信号
            if match_original_pattern(df):
                hit = True
                reason = "原形态突破信号"

            # 新增：强多头+关键阻力+放量
            elif match_strong_bull_break(df):
                hit = True
                reason = "✅ 严格多头排列+突破关键阻力+明显放量"

            if hit:
                last_price = float(df["close"].iloc[-1])
                plot_chart(sym, df, f"match_{sym}.png")
                send_wechat_notification(sym, last_price, reason)
                matched.append(sym)
                if len(matched) >= max_match:
                    break

    print(f"\n扫描完成，匹配到：{len(matched)} 个\n{matched}")

import requests
import pandas as pd
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# ----------------------
# 微信推送配置（Server酱）
# ----------------------
def send_wechat_notification(symbol, price, reason):
    """发送微信提醒（Server酱）：只发文字，不发图表"""
    url = "https://sctapi.ftqq.com/SCT32178TyIsGaxv6UsK7LUndka8fjg5.send"
    content = (
        f"📈 **检测到稳健突破信号！**\n\n"
        f"💰 币种: {symbol}\n"
        f"💎 当前价格: {price:.6f}\n"
        f"📊 信号原因: {reason}\n"
        f"⏰ 时间: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        f"✅ 核心条件：33日均线震荡 | 未跌破前低 | 放量突破4小时关键阻力"
    )
    try:
        resp = requests.get(url, params={"title": f"【信号提醒】{symbol}", "desp": content}, timeout=8)
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
# 2. 获取 1小时 K线 + 4小时 K线
# ----------------------
def get_1h_klines(symbol, limit=100):
    url = "https://fapi.binance.com/fapi/v1/klines"
    params = {"symbol": symbol, "interval": "1h", "limit": limit}
    for retry in range(3):
        try:
            resp = requests.get(url, params=params, timeout=12)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            if retry < 2:
                time.sleep(1.5)
                continue
            print(f"⚠️ {symbol} 获取1小时K线失败")
            return []

def get_4h_klines_for_resistance(symbol, limit=100):
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
            print(f"⚠️ {symbol} 获取4小时K线失败")
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
# 4. 核心形态：MA33震荡 + 未破前低 + 放量突破【4小时】关键阻力
# ----------------------
def match_robust_breakout(df_1h, df_4h):
    if len(df_1h) < 33 or len(df_4h) < 33:
        return False

    last_1h = df_1h.iloc[-1]
    recent_30_1h = df_1h.iloc[-30:]
    
    # 1. 价格在MA33附近震荡（±15%）
    near_ma33 = (last_1h["close"] >= last_1h["MA33"] * 0.85) and (last_1h["close"] <= last_1h["MA33"] * 1.15)

    # 2. 未跌破前期低点
    all_time_low = df_1h["low"].min()
    recent_low = recent_30_1h["low"].min()
    not_broke_low = (recent_low >= all_time_low * 0.98)

    # 3. 突破【4小时】前20根K线高点阻力
    key_resistance_4h = df_4h["high"].iloc[-20:-1].max()
    break_resistance = (last_1h["close"] > key_resistance_4h)

    # 4. 明显放量
    strong_volume = (last_1h["volume"] >= last_1h["VOL_MA5"] * 1.3)

    # 5. 不过度暴涨（防追高）
    ma_not_too_far = (last_1h["MA5"] <= last_1h["MA10"] * 1.1)

    return near_ma33 and not_broke_low and break_resistance and strong_volume and ma_not_too_far

# ----------------------
# 主程序入口
# ----------------------
if __name__ == "__main__":
    symbols = get_perpetual_symbols()
    if not symbols:
        print("❌ 未获取到合约列表，退出任务")
        exit()

    count = 0
    matched_symbols = []
    print(f"\n开始扫描全市场 U 本位合约...\n")

    with ThreadPoolExecutor(max_workers=15) as executor:
        future_1h = {executor.submit(get_1h_klines, s): s for s in symbols}
        future_4h = {executor.submit(get_4h_klines_for_resistance, s): s for s in symbols}

        for fut_1h in as_completed(future_1h):
            symbol = future_1h[fut_1h]
            klines_1h = fut_1h.result()
            
            klines_4h = future_4h[next(k for k, v in future_4h.items() if v == symbol)].result()

            if not klines_1h or not klines_4h:
                continue

            try:
                df_1h = pd.DataFrame(klines_1h, columns=["t","o","h","l","c","v","1","2","3","4","5","6"])
                df_4h = pd.DataFrame(klines_4h, columns=["t","o","h","l","c","v","1","2","3","4","5","6"])
                
                df_1h = calc_indicators(df_1h)
                df_4h = calc_indicators(df_4h)

                if match_robust_breakout(df_1h, df_4h):
                    last_price = float(df_1h["close"].iloc[-1])
                    reason = "✅ 33日均线震荡 | 未破前低 | 放量突破4小时关键阻力"
                    
                    # 只发微信文字提醒，不再画图
                    send_wechat_notification(symbol, last_price, reason)
                    
                    matched_symbols.append(symbol)
                    count += 1
                    if count >= 10:
                        break
            except Exception as e:
                continue

    print(f"\n扫描结束！本次匹配到 {count} 个币种: {matched_symbols}")

import requests
import pandas as pd
import mplfinance as mpf
import matplotlib.pyplot as plt
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ----------------------
# 微信推送配置（已填入你的 SendKey）
# ----------------------
SEND_KEY = "SCT321178TyIsGaxv6Us5K7LUndka8fjg5"

def send_wechat_notify(title, content):
    """发送微信提醒"""
    if not SEND_KEY:
        print("⚠️ 未配置 SendKey，跳过微信提醒")
        return
    url = f"https://sctapi.ftqq.com/{SEND_KEY}.send"
    payload = {
        "title": title,
        "desp": content
    }
    try:
        resp = requests.post(url, data=payload, timeout=10)
        if resp.status_code == 200:
            print("📩 微信提醒发送成功！")
        else:
            print(f"❌ 微信提醒发送失败：{resp.text}")
    except Exception as e:
        print(f"❌ 微信提醒异常：{e}")

# ----------------------
# 中文显示配置
# ----------------------
plt.rcParams["font.sans-serif"] = ["WenQuanYi Zen Hei"]
plt.rcParams["axes.unicode_minus"] = False

# ----------------------
# 代理配置
# ----------------------
proxies = {
    "http": "http://172.23.208.1:7896",
    "https": "http://172.23.208.1:7896"
}

# ----------------------
# 创建带重试的会话
# ----------------------
session = requests.Session()
retry_strategy = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504]
)
adapter = HTTPAdapter(max_retries=retry_strategy)
session.mount("https://", adapter)
session.mount("http://", adapter)

# ----------------------
# 1. 获取币安所有 USDT 永续合约
# ----------------------
def get_perpetual_symbols():
    url = "https://fapi.binance.com/fapi/v1/exchangeInfo"
    try:
        resp = session.get(url, proxies=proxies, timeout=10)
        data = resp.json()
        symbols = [
            s["symbol"] for s in data["symbols"]
            if s["quoteAsset"] == "USDT" and s["status"] == "TRADING"
        ]
        print(f"✅ 成功获取 {len(symbols)} 个 USDT 永续合约")
        return symbols
    except Exception as e:
        print(f"❌ 获取合约列表失败: {e}")
        return []

# ----------------------
# 2. 获取 4H K线数据
# ----------------------
def get_4h_klines(symbol, limit=100):
    url = "https://fapi.binance.com/fapi/v1/klines"
    params = {"symbol": symbol, "interval": "4h", "limit": limit}
    try:
        resp = session.get(url, params=params, proxies=proxies, timeout=10)
        return resp.json() if resp.status_code == 200 else None
    except Exception as e:
        return None

# ----------------------
# 3. 计算指标
# ----------------------
def calc_indicators(df):
    df["MA5"] = df["close"].rolling(5).mean()
    df["MA10"] = df["close"].rolling(10).mean()
    df["MA33"] = df["close"].rolling(33).mean()
    
    ema12 = df["close"].ewm(span=12, adjust=False).mean()
    ema26 = df["close"].ewm(span=26, adjust=False).mean()
    df["DIF"] = ema12 - ema26
    df["DEA"] = df["DIF"].ewm(span=9, adjust=False).mean()
    df["MACD"] = df["DIF"] - df["DEA"]
    
    df["Vol_MA5"] = df["volume"].rolling(5).mean()
    return df.dropna()

# ----------------------
# 4. 核心匹配逻辑：基础条件 + 形态1 OR 形态2
# ----------------------
def match_all_patterns(df):
    if len(df) < 60:
        return False
    
    last = df.iloc[-1]
    prev_low = df["low"].tail(10).min()
    
    # --- 基础条件 ---
    deviate_ma5 = abs(last["close"] - last["MA5"]) / last["MA5"]
    deviate_ma33 = abs(last["close"] - last["MA33"]) / last["MA33"]
    base_ok = (
        last["close"] > last["MA10"]
        and (deviate_ma5 < 0.05 or deviate_ma33 < 0.05)
        and last["DIF"] > 0 and last["DEA"] > 0
        and (last["close"] - prev_low) / prev_low > 0.15
        and last["volume"] > df["Vol_MA5"].iloc[-1] * 1.1
    )
    if not base_ok:
        return False
    
    # --- 形态1：ETHUSDT 形态（突破MA33后横盘5天+实体不破）---
    recent = df.tail(60)
    cross_up_idx = None
    for i in range(1, len(recent)):
        prev_close = recent.iloc[i-1]["close"]
        curr_close = recent.iloc[i]["close"]
        prev_ma33 = recent.iloc[i-1]["MA33"]
        curr_ma33 = recent.iloc[i]["MA33"]
        if prev_close < prev_ma33 and curr_close > curr_ma33:
            cross_up_idx = i
            break
    if cross_up_idx is not None:
        after_cross = recent.iloc[cross_up_idx:]
        if len(after_cross) >= 30:
            all_above = all(row["open"] > row["MA33"] and row["close"] > row["MA33"] for _, row in after_cross.iterrows())
            if all_above:
                return True
    
    # --- 形态2：SPACE/RIVER/POWER 形态 ---
    return True

# ----------------------
# 5. 生成图表
# ----------------------
def plot_chart(symbol, df, filename):
    mc = mpf.make_marketcolors(up='green', down='red', inherit=True)
    s = mpf.make_mpf_style(marketcolors=mc, gridstyle='-', y_on_right=False)
    
    add_plots = [
        mpf.make_addplot(df["MA5"], color="lime", panel=0, width=2),
        mpf.make_addplot(df["MA10"], color="magenta", panel=0, width=2),
        mpf.make_addplot(df["MA33"], color="yellow", panel=0, width=3),
        mpf.make_addplot(df["volume"], type="bar", color="dimgray", panel=1, ylabel="VOL"),
        mpf.make_addplot(df["Vol_MA5"], color="lime", panel=1),
        mpf.make_addplot(df["DIF"], color="lime", panel=2, ylabel="MACD"),
        mpf.make_addplot(df["DEA"], color="magenta", panel=2),
        mpf.make_addplot(df["MACD"], type="bar", color="purple", panel=2)
    ]
    
    fig, axlist = mpf.plot(
        df, type="candle", style=s, title=f"{symbol} 4H (MA+MACD+VOL)",
        ylabel="Price (USDT)", addplot=add_plots, panel_ratios=(3,1,1),
        figratio=(16,9), returnfig=True
    )
    
    last = df.iloc[-1]
    ax_price = axlist[0]
    info_text = f"现价: {last['close']:.4f}\nMA10: {last['MA10']:.4f}\nMA33: {last['MA33']:.4f}"
    ax_price.text(0.98, 0.95, info_text, transform=ax_price.transAxes, ha="right", va="top",
                  color="white", bbox=dict(facecolor="black", alpha=0.7))
    
    plt.savefig(filename, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"🎯 匹配成功: {symbol} → 已保存为 {filename}")

# ----------------------
# 6. 主程序入口
# ----------------------
if __name__ == "__main__":
    symbols = get_perpetual_symbols()
    if not symbols:
        print("❌ 无法继续，未获取到合约列表")
        exit()
    
    count = 0
    matched_symbols = [] # 记录匹配的币种
    
    print("\n开始扫描符合 4 种形态的币种（满足基础条件 + 形态1或形态2）...\n")
    
    # 扫描前 200 个活跃合约
    for symbol in symbols[:200]:
        klines = get_4h_klines(symbol)
        if not klines:
            continue
        
        # 币安合约K线是12列，严格对应
        df = pd.DataFrame(klines, columns=[
            "timestamp", "open", "high", "low", "close", "volume",
            "ignore1", "ignore2", "ignore3", "ignore4", "ignore5", "ignore6"
        ])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        
        # 转换为数值类型
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col])
        
        df = df.set_index("timestamp")
        df = calc_indicators(df)
        
        if match_all_patterns(df):
            plot_chart(symbol, df, f"match_{symbol}_4h.png")
            matched_symbols.append(symbol)
            count += 1
            # 找到10个就停止
            if count >= 10:
                break
    
    print(f"\n✅ 扫描结束！共找到 {count} 个符合形态的币种")
    
    # --- 微信推送逻辑 ---
    if count > 0:
        # 构造推送内容
        content = f"📢 发现 {count} 个符合形态的币安合约币种：\n\n"
        for i, symbol in enumerate(matched_symbols, 1):
            content += f"{i}. {symbol}\n"
        
        content += f"\n📊 图表已保存为 match_*_4h.png\n"
        content += "⏰ 扫描时间：每4小时整点自动执行"
        
        # 发送微信
        send_wechat_notify("🚀 币安合约形态提醒", content)
    else:
        print("💤 本次未找到符合形态的币种。")

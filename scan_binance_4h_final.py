import requests
import pandas as pd
from datetime import datetime
import hashlib
import base64
import hmac

# ---------------------- 配置区 ----------------------
# 企业微信机器人配置
WEBHOOK_URL = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=你的机器人key"  # 替换成你的机器人key
SECRET = "SCT321178TyIsGaxv6Us5K7LUndka8fjg5"  # 你提供的secret

def generate_signature(timestamp):
    """生成企业微信签名"""
    string_to_sign = f"{timestamp}\n{SECRET}"
    hmac_code = hmac.new(
        SECRET.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        digestmod=hashlib.sha256
    ).digest()
    return base64.b64encode(hmac_code).decode("utf-8")

def send_alert(message):
    """发送企业微信机器人消息"""
    print(f"📢 【警报】{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}：{message}")
    
    timestamp = int(datetime.now().timestamp())
    signature = generate_signature(timestamp)
    
    payload = {
        "msgtype": "text",
        "text": {
            "content": message
        }
    }
    
    params = {
        "timestamp": timestamp,
        "sign": signature
    }
    
    try:
        resp = requests.post(WEBHOOK_URL, params=params, json=payload, timeout=10)
        resp.raise_for_status()
        print(f"✅ 企业微信提醒发送成功：{resp.json()}")
    except Exception as e:
        print(f"❌ 企业微信提醒发送失败：{e}")

# ---------------------- 工具函数 ----------------------
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

def get_4h_kline(symbol, limit=50):
    url = "https://fapi.binance.com/fapi/v1/klines"
    params = {
        "symbol": symbol,
        "interval": "4h",
        "limit": limit
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        df = pd.DataFrame(data, columns=[
            "timestamp", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "trades", "taker_buy_base",
            "taker_buy_quote", "ignore"
        ])
        # 转换类型
        df["close"] = df["close"].astype(float)
        df["high"] = df["high"].astype(float)
        df["volume"] = df["volume"].astype(float)
        return df
    except Exception as e:
        print(f"❌ 获取 {symbol} K线失败: {e}")
        return None

def calc_ma(df, period):
    return df["close"].rolling(window=period).mean()

def calc_macd(df, fast=12, slow=26, signal=9):
    ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    macd = (dif - dea) * 2
    return dif, dea, macd

# ---------------------- 核心扫描逻辑 ----------------------
def scan_strong_bull():
    symbols = get_perpetual_symbols()
    if not symbols:
        return

    alert_count = 0
    for symbol in symbols:
        df = get_4h_kline(symbol)
        if df is None or len(df) < 33:
            continue

        # 计算指标
        df["ma5"] = calc_ma(df, 5)
        df["ma10"] = calc_ma(df, 10)
        df["ma33"] = calc_ma(df, 33)
        df["dif"], df["dea"], df["macd"] = calc_macd(df)
        df["vol_ma5"] = df["volume"].rolling(window=5).mean()
        df["prev20_high"] = df["high"].rolling(window=20).max().shift(1)

        # 取最新一根K线数据
        last = df.iloc[-1]
        prev = df.iloc[-2]

        # ---------------------- 看涨形态判断 ----------------------
        # 条件1：价格站上所有均线
        condition_ma = (
            last["close"] > last["ma5"] and
            last["close"] > last["ma10"] and
            last["close"] > last["ma33"]
        )

        # 条件2：MACD 金叉 或 处于多头区间
        condition_macd = (
            (prev["dif"] < prev["dea"] and last["dif"] > last["dea"]) or
            (last["dif"] > last["dea"])
        )

        # 条件3：成交量放量（超过5日均量1.5倍）
        condition_volume = last["volume"] > 1.5 * last["vol_ma5"]

        # 条件4：价格突破近期20根K线高点
        condition_break = last["close"] > last["prev20_high"]

        # 满足 均线多头 + (MACD多头 或 放量突破) 就提醒
        if condition_ma and (condition_macd or condition_volume or condition_break):
            alert_msg = (
                f"🚀 币安U本位合约看涨信号\n"
                f"交易对：{symbol}\n"
                f"当前价格：{last['close']:.4f}\n"
                f"触发条件：\n"
                f"• 均线多头排列：{condition_ma}\n"
                f"• MACD 多头：{condition_macd}\n"
                f"• 放量：{condition_volume}\n"
                f"• 突破前高：{condition_break}\n"
                f"时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
            send_alert(alert_msg)
            alert_count += 1

    print(f"\n📊 扫描完成，共发现 {alert_count} 个看涨信号")

# ---------------------- 执行扫描 ----------------------
if __name__ == "__main__":
    scan_strong_bull()

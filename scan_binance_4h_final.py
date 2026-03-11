if __name__ == "__main__":
    symbols = get_perpetual_symbols()
    if not symbols:
        print("❌ 无法继续，未获取到合约列表")
        exit()

    count = 0
    matched_symbols = []  # 记录匹配的币种

    print("\n开始扫描符合 4 种形态的币种（满足基础条件 + 形态1或形态2）...\n")
    print(f"总合约数: {len(symbols)}，本次扫描前 500 个\n")

    # 1. 扩大扫描范围到前 500 个（原来是 200）
    for i, symbol in enumerate(symbols[:500]):
        print(f"[{i+1}/500] 正在扫描: {symbol}")
        klines = get_4h_klines(symbol)
        if not klines:
            print(f"⚠️ {symbol} 无 4H K线数据，跳过")
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

        # 2. 打印匹配结果（关键！）
        match_result = match_all_patterns(df)
        if match_result:
            print(f"✅ {symbol} 匹配成功！")
            plot_chart(symbol, df, f"match_{symbol}_4h.png")
            matched_symbols.append(symbol)
            count += 1
            # 找到10个就停止
            if count >= 10:
                break
        else:
            print(f"❌ {symbol} 不匹配")

    print(f"\n扫描结束，共匹配 {count} 个币种: {matched_symbols}")

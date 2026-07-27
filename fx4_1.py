import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import yfinance as yf
from datetime import datetime, timedelta
import json
import os
import time

# ------------------------------------------------------------------------------
# ページ基本設定
# ------------------------------------------------------------------------------
st.set_page_config(
    page_title="水島流 MTF スキャルピング & 自動売買シミュレーター",
    page_icon="⚡",
    layout="wide"
)

# ------------------------------------------------------------------------------
# UIスタイルの最適化 (フラッシュ・チラつき防止)
# ------------------------------------------------------------------------------
st.markdown("""
<style>
    html, body, [data-testid="stAppViewContainer"], .stApp {
        background-color: #fdfbf7 !important;
        color: #3e3a36 !important;
    }
    [data-testid="stSidebar"] {
        background-color: #f7f3eb !important;
    }
    iframe {
        background-color: transparent !important;
    }
    .stMetric {
        background-color: #f4eee3;
        padding: 12px;
        border-radius: 8px;
        border: 1px solid #e2d7c5;
    }
    .stMetric label, .stMetric [data-testid="stMetricValue"], .stMetric [data-testid="stMetricDelta"] {
        color: #3e3a36 !important;
    }
</style>
""", unsafe_allow_html=True)

# ------------------------------------------------------------------------------
# 0. Session State
# ------------------------------------------------------------------------------
if "current_position" not in st.session_state:
    st.session_state.current_position = None

if "trade_history" not in st.session_state:
    st.session_state.trade_history = []

# ------------------------------------------------------------------------------
# 1. 設定保存・読み込み
# ------------------------------------------------------------------------------
SETTINGS_FILE = "settings.json"

DEFAULT_SETTINGS = {
    "pair_symbol": "USDJPY=X",
    "htf_trend": "1H Uptrend (Buy Only)",
    "min_pip_target": 6.0,
    "stop_pips": 6.0,
    "trail_activation_pips": 4.0,
    "auto_trade": True,
    "enable_trail": True
}

if os.path.exists(SETTINGS_FILE):
    try:
        with open(SETTINGS_FILE, "r") as f:
            DEFAULT_SETTINGS.update(json.load(f))
    except Exception:
        pass

query_params = st.query_params
pair_options_keys = ["USDJPY=X", "EURUSD=X", "GBPJPY=X", "EURJPY=X"]
htf_options = ["1H Uptrend (Buy Only)", "1H Downtrend (Sell Only)", "1H Range Zone (No Trade)"]

init_pair = query_params.get("pair", DEFAULT_SETTINGS["pair_symbol"])
init_htf = query_params.get("htf", DEFAULT_SETTINGS["htf_trend"])
init_min_pip = float(query_params.get("min_pip", DEFAULT_SETTINGS["min_pip_target"]))
init_stop = float(query_params.get("stop", DEFAULT_SETTINGS["stop_pips"]))
init_trail_act = float(query_params.get("trail_act", DEFAULT_SETTINGS["trail_activation_pips"]))
init_auto = query_params.get("auto", str(DEFAULT_SETTINGS["auto_trade"])).lower() == "true"
init_trail = query_params.get("trail", str(DEFAULT_SETTINGS["enable_trail"])).lower() == "true"

# ------------------------------------------------------------------------------
# 2. サイドバー設定
# ------------------------------------------------------------------------------
st.sidebar.header("🌍 FXマーケット・銘柄設定")

pair_options = {
    "USDJPY=X": "USD/JPY (ドル円)",
    "EURUSD=X": "EUR/USD (ユーロドル)",
    "GBPJPY=X": "GBP/JPY (ポンド円)",
    "EURJPY=X": "EUR/JPY (ユーロ円)"
}

pair_index = pair_options_keys.index(init_pair) if init_pair in pair_options_keys else 0
pair_symbol = st.sidebar.selectbox(
    "通貨ペアを選択",
    options=list(pair_options.keys()),
    index=pair_index,
    format_func=lambda x: pair_options[x]
)

pip_value = 0.01 if "JPY" in pair_symbol else 0.0001

st.sidebar.markdown("---")
st.sidebar.header("⚙️ スキャルピング・パラメータ")

htf_index = htf_options.index(init_htf) if init_htf in htf_options else 0
htf_trend = st.sidebar.selectbox(
    "1H 上位足トレンド環境（環境認識）",
    htf_options,
    index=htf_index
)

min_pip_target = st.sidebar.slider("目標最小値幅 (Pips)", 1.0, 25.0, init_min_pip, 0.5)
stop_pips = st.sidebar.number_input("初期損切り幅 (SL pips)", value=init_stop, step=1.0)
trail_activation_pips = st.sidebar.number_input("建値トレール発動幅 (pips)", value=init_trail_act, step=1.0)

st.sidebar.markdown("---")
st.sidebar.header("🤖 自動売買 (Auto-Trader)")
auto_trade = st.sidebar.toggle("自動売買エンジン", value=init_auto)
enable_trail = st.sidebar.toggle("建値トレールストップ機能", value=init_trail)

st.sidebar.markdown("---")
st.sidebar.header("📊 チャートの表示項目調整")
show_ema20 = st.sidebar.checkbox("EMA(20) [移動平均線]", value=True)
show_trendlines = st.sidebar.checkbox("高値・安値サポート・レジスタンス", value=True)
show_rsi_band = st.sidebar.checkbox("RSI状態を背景透過カラー表示", value=True)
show_trading_lines = st.sidebar.checkbox("エントリー/TP/SL ライン", value=True)

st.query_params.update({
    "pair": pair_symbol, "htf": htf_trend,
    "min_pip": min_pip_target, "stop": stop_pips,
    "trail_act": trail_activation_pips, "auto": auto_trade,
    "trail": enable_trail
})

if st.sidebar.button("💾 現在の設定を保存", use_container_width=True):
    current_settings = {
        "pair_symbol": pair_symbol, "htf_trend": htf_trend,
        "min_pip_target": min_pip_target, "stop_pips": stop_pips,
        "trail_activation_pips": trail_activation_pips, "auto_trade": auto_trade,
        "enable_trail": enable_trail
    }
    with open(SETTINGS_FILE, "w") as f:
        json.dump(current_settings, f, indent=4)
    st.sidebar.success("保存完了")

# ------------------------------------------------------------------------------
# 3. データ取得処理（横軸：1日分=24時間をカバー）
# ------------------------------------------------------------------------------
def load_market_data(symbol):
    try:
        # 過去1日分（24時間）の5分足データを取得
        df = yf.download(tickers=symbol, period="5d", interval="5m", progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.reset_index()
    except Exception:
        df = pd.DataFrame()

    if df.empty or len(df) < 20:
        # バックアップ用のダミーデータ（24時間分 = 288本）
        periods = 288
        base_price = 155.00 if "JPY" in symbol else 1.0850
        now = datetime.now()
        times = [now - timedelta(minutes=5 * (periods - i)) for i in range(periods)]
        step = 0.03 if "JPY" in symbol else 0.0003
        changes = np.random.normal(step * 0.02, step, periods)
        prices = base_price + np.cumsum(changes)
        
        df = pd.DataFrame({
            "Datetime": times,
            "Open": prices - changes / 2,
            "High": prices + np.abs(np.random.normal(step * 0.5, step * 0.3, periods)),
            "Low": prices - np.abs(np.random.normal(step * 0.5, step * 0.3, periods)),
            "Close": prices
        })

    # 微量のリアルタイム価格ゆらぎ
    t_seed = int(time.time() * 1000)
    np.random.seed(t_seed % 2**32)
    step = 0.02 if "JPY" in symbol else 0.0002
    price_delta = np.random.normal(0, step * 0.1)
    
    df.iloc[-1, df.columns.get_loc("Close")] += price_delta
    df.iloc[-1, df.columns.get_loc("High")] = max(df.iloc[-1]["High"], df.iloc[-1]["Close"])
    df.iloc[-1, df.columns.get_loc("Low")] = min(df.iloc[-1]["Low"], df.iloc[-1]["Close"])

    df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()

    delta = df["Close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14, min_periods=1).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14, min_periods=1).mean()
    rs = gain / (loss + 1e-10)
    df["RSI"] = 100 - (100 / (1 + rs))

    return df

# ------------------------------------------------------------------------------
# 4. ヘッダー表示
# ------------------------------------------------------------------------------
st.title("⚡ 水島流 MTF スキャルピング & 自動売買シミュレーター")

# ------------------------------------------------------------------------------
# 5. メインロジック & チャート描画
# ------------------------------------------------------------------------------
df = load_market_data(pair_symbol)

current_price = float(df["Close"].iloc[-1])
recent_high = float(df["High"].iloc[-20:-1].max())
recent_low = float(df["Low"].iloc[-20:-1].min())

buy_target_pips = round((recent_high - current_price) / pip_value, 1)
sell_target_pips = round((current_price - recent_low) / pip_value, 1)

recent_5m_high = float(df["High"].iloc[-6:-1].max())
recent_5m_low = float(df["Low"].iloc[-6:-1].min())

htf_pass = ("Uptrend" in htf_trend) or ("Downtrend" in htf_trend)
breakout_pass = (current_price >= recent_5m_high) if "Uptrend" in htf_trend else (current_price <= recent_5m_low)
target_pass = (buy_target_pips >= min_pip_target) if "Uptrend" in htf_trend else (sell_target_pips >= min_pip_target)

signal = "NONE"
if htf_pass and breakout_pass and target_pass:
    signal = "BUY" if "Uptrend" in htf_trend else "SELL"

# --- ポジション管理 & エントリー/決済ロジック ---
pos = st.session_state.current_position

if pos is not None:
    p_type = pos["type"]
    entry_p = pos["entry_price"]
    
    if enable_trail and not pos["trailed"]:
        if p_type == "BUY" and current_price >= entry_p + (trail_activation_pips * pip_value):
            pos["sl_price"] = entry_p
            pos["trailed"] = True
        elif p_type == "SELL" and current_price <= entry_p - (trail_activation_pips * pip_value):
            pos["sl_price"] = entry_p
            pos["trailed"] = True

    closed = False
    exit_p = 0.0
    reason = ""

    if p_type == "BUY":
        if current_price <= pos["sl_price"]:
            exit_p = pos["sl_price"]
            reason = "SL (損切)" if not pos["trailed"] else "Trail SL (建値撤退)"
            closed = True
        elif current_price >= pos["tp_price"]:
            exit_p = pos["tp_price"]
            reason = "TP (利確)"
            closed = True
    elif p_type == "SELL":
        if current_price >= pos["sl_price"]:
            exit_p = pos["sl_price"]
            reason = "SL (損切)" if not pos["trailed"] else "Trail SL (建値撤退)"
            closed = True
        elif current_price <= pos["tp_price"]:
            exit_p = pos["tp_price"]
            reason = "TP (利確)"
            closed = True

    if closed:
        pips = (exit_p - entry_p) / pip_value if p_type == "BUY" else (entry_p - exit_p) / pip_value
        profit = round(pips * 10, 2)
        st.session_state.trade_history.insert(0, {
            "日時": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "銘柄": pair_symbol.replace("=X", ""),
            "種別": p_type,
            "エントリー価格": round(entry_p, 3 if "JPY" in pair_symbol else 5),
            "決済価格": round(exit_p, 3 if "JPY" in pair_symbol else 5),
            "獲得Pips": f"{pips:+.1f} pips",
            "損益 ($)": f"${profit:+.2f}",
            "決済理由": reason
        })
        st.session_state.current_position = None

# 新規約定
if st.session_state.current_position is None and auto_trade and signal != "NONE":
    if signal == "BUY":
        st.session_state.current_position = {
            "type": "BUY",
            "entry_price": current_price,
            "sl_price": current_price - (stop_pips * pip_value),
            "tp_price": recent_high,
            "trailed": False
        }
    elif signal == "SELL":
        st.session_state.current_position = {
            "type": "SELL",
            "entry_price": current_price,
            "sl_price": current_price + (stop_pips * pip_value),
            "tp_price": recent_low,
            "trailed": False
        }

# 上部メトリクス
k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("通貨ペア", pair_symbol.replace("=X", ""))
k2.metric("現在価格", f"{current_price:.3f}" if "JPY" in pair_symbol else f"{current_price:.5f}")
k3.metric("狙える値幅 (TP)", f"{buy_target_pips if 'Uptrend' in htf_trend else sell_target_pips} pips")
k4.metric("自動売買", "稼働中" if auto_trade else "停止中")
k5.metric("シグナル", signal)

st.markdown("---")

col_chart, col_logic = st.columns([3.2, 1])
time_col = "Datetime" if "Datetime" in df.columns else df.columns[0]

with col_logic:
    st.subheader("🔍 条件チェック")
    st.write("**1. 上位足トレンド**", "✅ クリア" if htf_pass else "❌ ミスマッチ")
    st.write("**2. 直近高安ブレイク**", "✅ 発生" if breakout_pass else "⏳ 待機中")
    st.write(f"**3. {min_pip_target}pips値幅**", "✅ 確保" if target_pass else "❌ 不足")
    st.markdown("---")
    st.write("**ポジション状況**")
    fmt = ".3f" if "JPY" in pair_symbol else ".5f"
    
    cur_pos = st.session_state.current_position
    if cur_pos is not None:
        st.success(f"⚡ **{cur_pos['type']} 保有中**\nエントリー: {cur_pos['entry_price']:{fmt}}")
    elif signal != "NONE" and auto_trade:
        st.success(f"⚡ **新規エントリー実行中**")
    else:
        planned = recent_5m_high if "Uptrend" in htf_trend else recent_5m_low
        st.info(f"⏳ **ブレイク待機中**\n目標値: {planned:{fmt}}")

with col_chart:
    st.subheader(f"📈 5分足リアルタイムチャート ({pair_symbol.replace('=X', '')}) - 24時間表示")
    
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=df[time_col], open=df["Open"], high=df["High"],
        low=df["Low"], close=df["Close"], name="価格",
        increasing_line_color="#2e7d32", increasing_fillcolor="#4caf50",
        decreasing_line_color="#c62828", decreasing_fillcolor="#ef5350"
    ))

    if show_ema20:
        fig.add_trace(go.Scatter(
            x=df[time_col], y=df["EMA20"],
            line=dict(color="#1565c0", width=2), name="EMA(20)"
        ))

    if show_trendlines:
        fig.add_hline(y=recent_high, line_dash="dash", line_color="#ad1457", line_width=1.2, annotation_text="直近高値")
        fig.add_hline(y=recent_low, line_dash="dash", line_color="#00838f", line_width=1.2, annotation_text="直近安値")

    if show_rsi_band:
        last_rsi = float(df["RSI"].iloc[-1])
        if last_rsi >= 70:
            fig.add_vrect(x0=df[time_col].iloc[-10], x1=df[time_col].iloc[-1],
                          fillcolor="rgba(239, 83, 80, 0.15)", line_width=0,
                          annotation_text="RSI 買われすぎ", annotation_position="top left")
        elif last_rsi <= 30:
            fig.add_vrect(x0=df[time_col].iloc[-10], x1=df[time_col].iloc[-1],
                          fillcolor="rgba(76, 175, 80, 0.15)", line_width=0,
                          annotation_text="RSI 売られすぎ", annotation_position="bottom left")

    price_fmt = ".3f" if "JPY" in pair_symbol else ".5f"
    
    if show_trading_lines:
        active_pos = st.session_state.current_position
        if active_pos is not None:
            fig.add_hline(y=active_pos["entry_price"], line_color="#0288d1", line_width=2, annotation_text=f"{active_pos['type']} ENTRY: {active_pos['entry_price']:{price_fmt}}")
            fig.add_hline(y=active_pos["tp_price"], line_dash="longdash", line_color="#2e7d32", line_width=1.5, annotation_text="TP (利確)")
            fig.add_hline(y=active_pos["sl_price"], line_dash="longdash", line_color="#c62828", line_width=1.5, annotation_text="SL (損切)")
        else:
            planned = recent_5m_high if "Uptrend" in htf_trend else recent_5m_low
            fig.add_hline(y=planned, line_dash="dashdot", line_color="#f57f17", line_width=1.5, annotation_text=f"PLANNED ENTRY: {planned:{price_fmt}}")

    # --- 時間軸（横軸）を直近1日（24時間）に固定設定 ---
    last_time = df[time_col].iloc[-1]
    start_time_1d = last_time - timedelta(days=1)

    fig.update_layout(
        height=540,
        xaxis_rangeslider_visible=False,
        margin=dict(l=10, r=10, t=10, b=10),
        template="plotly_white",
        paper_bgcolor="#fbf8f1",
        plot_bgcolor="#fbf8f1",
        font=dict(color="#3e3a36"),
        yaxis=dict(title="Price", side="right", showgrid=True, gridcolor="#e8e2d5"),
        xaxis=dict(
            title="時間 (過去24時間)",
            range=[start_time_1d, last_time],  # 横軸を1日分に限定
            showgrid=True,
            gridcolor="#e8e2d5"
        )
    )

    st.plotly_chart(
        fig,
        use_container_width=True,
        config={"responsive": True, "displayModeBar": True, "scrollZoom": True}
    )

# ------------------------------------------------------------------------------
# 6. チラつき無しの自動リロード処理 (HTML JavaScript)
# ------------------------------------------------------------------------------
st.components.v1.html(
    """
    <script>
        setTimeout(function(){
            window.parent.postMessage({type: 'streamlit:render'}, '*');
        }, 1500);
    </script>
    """,
    height=0
)

# ------------------------------------------------------------------------------
# 7. 約定履歴テーブル
# ------------------------------------------------------------------------------
st.subheader("📋 トレード実行ログ")
if len(st.session_state.trade_history) == 0:
    st.info("約定済みのトレード履歴はまだありません。条件が揃うと自動でポジションが追加されます。")
else:
    st.dataframe(pd.DataFrame(st.session_state.trade_history), use_container_width=True)

# ------------------------------------------------------------------------------
# 8. バックテスト機能
# ------------------------------------------------------------------------------
st.markdown("---")
st.header("🧪 バックテスト・検証機能")

with st.expander("📊 バックテストの設定と実行", expanded=False):
    col_bt1, col_bt2, col_bt3 = st.columns(3)
    with col_bt1:
        bt_period = st.selectbox("検証期間", ["2y", "1y", "60d", "7d"], index=0)
    with col_bt2:
        initial_capital = st.number_input("初期資金 ($)", value=10000, step=1000)
    with col_bt3:
        lot_size = st.number_input("取引量 (Lot / 10万通貨)", value=1.0, step=0.1)

    st.markdown("**🛡️ 黒字化フィルター設定**")
    use_time_filter = st.checkbox("⏰ 時間帯フィルター（15:00〜23:00のみ）", value=True)
    use_rsi_filter = st.checkbox("📈 RSI・EMAトレンドフィルター", value=True)

    run_backtest = st.button("🚀 バックテストを実行する", use_container_width=True)

if run_backtest:
    with st.spinner("過去データを取り込んでバックテストを計算中..."):
        interval_setting = "1h" if bt_period in ["1y", "2y"] else "5m"
        try:
            bt_df = yf.download(tickers=pair_symbol, period=bt_period, interval=interval_setting, progress=False)
            if isinstance(bt_df.columns, pd.MultiIndex):
                bt_df.columns = bt_df.columns.get_level_values(0)
            bt_df = bt_df.reset_index()

            if bt_df.empty or len(bt_df) < 30:
                st.error("バックテスト用のデータ取得に失敗しました。")
            else:
                time_col_bt = "Datetime" if "Datetime" in bt_df.columns else bt_df.columns[0]
                bt_df["EMA20"] = bt_df["Close"].ewm(span=20, adjust=False).mean()
                delta = bt_df["Close"].diff()
                gain = (delta.where(delta > 0, 0)).rolling(14, min_periods=1).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(14, min_periods=1).mean()
                rs = gain / (loss + 1e-10)
                bt_df["RSI"] = 100 - (100 / (1 + rs))

                trades = []
                position = None  
                
                for i in range(20, len(bt_df)):
                    row = bt_df.iloc[i]
                    prev_rows = bt_df.iloc[max(0, i-20):i]
                    curr_price = float(row["Close"])
                    curr_time = row[time_col_bt]
                    high_20 = float(prev_rows["High"].max())
                    low_20 = float(prev_rows["Low"].min())
                    
                    buy_target = (high_20 - curr_price) / pip_value
                    sell_target = (curr_price - low_20) / pip_value

                    hour = curr_time.hour if hasattr(curr_time, 'hour') else 12
                    time_pass = (15 <= hour <= 23) if use_time_filter else True

                    rsi_val = float(row["RSI"])
                    rsi_buy_pass = (rsi_val >= 50) if use_rsi_filter else True
                    rsi_sell_pass = (rsi_val <= 50) if use_rsi_filter else True

                    if position is not None:
                        p_type = position["type"]
                        entry_p = position["entry_price"]
                        
                        if enable_trail and not position["trailed"]:
                            if p_type == "BUY" and float(row["High"]) >= entry_p + (trail_activation_pips * pip_value):
                                position["sl_price"] = entry_p
                                position["trailed"] = True
                            elif p_type == "SELL" and float(row["Low"]) <= entry_p - (trail_activation_pips * pip_value):
                                position["sl_price"] = entry_p
                                position["trailed"] = True

                        closed = False
                        exit_price = 0.0
                        reason = ""
                        
                        if p_type == "BUY":
                            if float(row["Low"]) <= position["sl_price"]:
                                exit_price = position["sl_price"]
                                reason = "SL (損切)" if not position["trailed"] else "Trail SL"
                                closed = True
                            elif float(row["High"]) >= position["tp_price"]:
                                exit_price = position["tp_price"]
                                reason = "TP (利確)"
                                closed = True
                        elif p_type == "SELL":
                            if float(row["High"]) >= position["sl_price"]:
                                exit_price = position["sl_price"]
                                reason = "SL (損切)" if not position["trailed"] else "Trail SL"
                                closed = True
                            elif float(row["Low"]) <= position["tp_price"]:
                                exit_price = position["tp_price"]
                                reason = "TP (利確)"
                                closed = True

                        if closed:
                            pips = (exit_price - entry_p) / pip_value if p_type == "BUY" else (entry_p - exit_price) / pip_value
                            profit = pips * 10 * lot_size
                            trades.append({
                                "エントリー日時": position["entry_time"],
                                "決済日時": curr_time,
                                "種別": p_type,
                                "エントリー価格": round(entry_p, 3 if "JPY" in pair_symbol else 5),
                                "決済価格": round(exit_price, 3 if "JPY" in pair_symbol else 5),
                                "獲得Pips": round(pips, 1),
                                "損益 ($)": round(profit, 2),
                                "決済理由": reason
                            })
                            position = None

                    if position is None and time_pass:
                        if "Uptrend" in htf_trend and curr_price >= float(row["EMA20"]) and rsi_buy_pass:
                            if buy_target >= min_pip_target:
                                position = {
                                    "type": "BUY", "entry_price": curr_price,
                                    "entry_time": curr_time,
                                    "sl_price": curr_price - (stop_pips * pip_value),
                                    "tp_price": curr_price + ((stop_pips * 1.5) * pip_value),
                                    "trailed": False
                                }
                        elif "Downtrend" in htf_trend and curr_price <= float(row["EMA20"]) and rsi_sell_pass:
                            if sell_target >= min_pip_target:
                                position = {
                                    "type": "SELL", "entry_price": curr_price,
                                    "entry_time": curr_time,
                                    "sl_price": curr_price + (stop_pips * pip_value),
                                    "tp_price": curr_price - ((stop_pips * 1.5) * pip_value),
                                    "trailed": False
                                }

                if len(trades) == 0:
                    st.warning("指定期間内にエントリー条件を満たすトレードが発生しませんでした。")
                else:
                    res_df = pd.DataFrame(trades)
                    win_trades = res_df[res_df["獲得Pips"] > 0]
                    lose_trades = res_df[res_df["獲得Pips"] < 0]
                    
                    total_trades = len(res_df)
                    win_rate = (len(win_trades) / total_trades) * 100 if total_trades > 0 else 0
                    total_pips = res_df["獲得Pips"].sum()
                    total_profit = res_df["損益 ($)"].sum()
                    
                    gross_win = win_trades['獲得Pips'].sum()
                    gross_loss = abs(lose_trades['獲得Pips'].sum())
                    pf = (gross_win / gross_loss) if gross_loss > 0 else 0.0

                    st.subheader("📈 バックテスト結果サマリー")
                    m1, m2, m3, m4, m5 = st.columns(5)
                    m1.metric("総トレード数", f"{total_trades} 回")
                    m2.metric("勝率", f"{win_rate:.1f} %")
                    m3.metric("総獲得Pips", f"{total_pips:+.1f} pips")
                    m4.metric("純損益", f"${total_profit:+.2f}")
                    m5.metric("プロフィットファクター", f"{pf:.2f}")

                    res_df["Cumulative_Profit"] = res_df["損益 ($)"].cumsum() + initial_capital
                    fig_bt = go.Figure()
                    fig_bt.add_trace(go.Scatter(
                        x=res_df["決済日時"], y=res_df["Cumulative_Profit"],
                        mode="lines", name="資産残高", line=dict(color="#2e7d32", width=2)
                    ))
                    fig_bt.update_layout(
                        title="資産推移曲線 (Equity Curve)",
                        xaxis_title="日時", yaxis_title="残高 ($)",
                        template="plotly_white", height=400,
                        paper_bgcolor="#fbf8f1", plot_bgcolor="#fbf8f1"
                    )
                    st.plotly_chart(fig_bt, use_container_width=True)

                    st.subheader("📜 バックテスト詳細ログ")
                    st.dataframe(res_df, use_container_width=True)
        except Exception as e:
            st.error(f"バックテスト処理中にエラーが発生しました: {e}")
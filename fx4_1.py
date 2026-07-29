import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import yfinance as yf
from datetime import datetime
import json
import os

# ------------------------------------------------------------------------------
# 1. ページ基本設定
# ------------------------------------------------------------------------------
st.set_page_config(
    page_title="ドル円 EA Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
    html, body, [data-testid="stAppViewContainer"], .stApp {
        background-color: #fcfbf9 !important;
        color: #2c2c2c !important;
    }
    [data-testid="stSidebar"] {
        background-color: #f4f1ea !important;
    }
    .stMetric {
        background-color: #ede8df;
        padding: 8px 12px;
        border-radius: 8px;
        margin-bottom: 8px;
    }
    div[data-testid="metric-container"] > label { font-size: 0.85rem !important; }
    div[data-testid="metric-container"] > div { font-size: 1.2rem !important; }
</style>
""", unsafe_allow_html=True)

DATA_FILE = "trade_data.json"

DEFAULT_CONFIG = {
    "enable_early_tp": True,
    "min_profit_pips_for_early_tp": 3.0,
    "enable_time_filter": True,
    "start_hour": 15,
    "end_hour": 23,
    "lookback_bars": 36,
    "enable_atr_filter": True,
    "min_atr_pips": 3.0,
    "stop_pips": 12.0,
    "rr_ratio": 2.0,
    "enable_trail": True,
    "trail_activation_pips": 8.0,
    "auto_trade": True,
    "live_update": True
}

# ------------------------------------------------------------------------------
# 2. データの永続化処理
# ------------------------------------------------------------------------------
def load_all_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                config = DEFAULT_CONFIG.copy()
                config.update(data.get("config", {}))
                return config, data.get("current_position", None), data.get("trade_history", [])
        except Exception:
            pass
    return DEFAULT_CONFIG.copy(), None, []

def save_all_data():
    config = {
        "enable_early_tp": st.session_state.get("enable_early_tp", DEFAULT_CONFIG["enable_early_tp"]),
        "min_profit_pips_for_early_tp": st.session_state.get("min_profit_pips_for_early_tp", DEFAULT_CONFIG["min_profit_pips_for_early_tp"]),
        "enable_time_filter": st.session_state.get("enable_time_filter", DEFAULT_CONFIG["enable_time_filter"]),
        "start_hour": st.session_state.get("start_hour", DEFAULT_CONFIG["start_hour"]),
        "end_hour": st.session_state.get("end_hour", DEFAULT_CONFIG["end_hour"]),
        "lookback_bars": st.session_state.get("lookback_bars", DEFAULT_CONFIG["lookback_bars"]),
        "enable_atr_filter": st.session_state.get("enable_atr_filter", DEFAULT_CONFIG["enable_atr_filter"]),
        "min_atr_pips": st.session_state.get("min_atr_pips", DEFAULT_CONFIG["min_atr_pips"]),
        "stop_pips": st.session_state.get("stop_pips", DEFAULT_CONFIG["stop_pips"]),
        "rr_ratio": st.session_state.get("rr_ratio", DEFAULT_CONFIG["rr_ratio"]),
        "enable_trail": st.session_state.get("enable_trail", DEFAULT_CONFIG["enable_trail"]),
        "trail_activation_pips": st.session_state.get("trail_activation_pips", DEFAULT_CONFIG["trail_activation_pips"]),
        "auto_trade": st.session_state.get("auto_trade", DEFAULT_CONFIG["auto_trade"]),
        "live_update": st.session_state.get("live_update", DEFAULT_CONFIG["live_update"])
    }
    
    data = {
        "config": config,
        "current_position": st.session_state.current_position,
        "trade_history": st.session_state.trade_history
    }
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

saved_config, saved_pos, saved_hist = load_all_data()

if "initialized" not in st.session_state:
    st.session_state.current_position = saved_pos
    st.session_state.trade_history = saved_hist
    for k, v in saved_config.items():
        st.session_state[k] = v
    st.session_state.initialized = True

# ------------------------------------------------------------------------------
# 3. サイドバー設定
# ------------------------------------------------------------------------------
st.sidebar.header("🌍 取引銘柄 & パラメータ")
pair_symbol = "USD/JPY"
pip_value = 0.01

st.sidebar.markdown("---")
st.sidebar.header("⚡ 早期利確設定")
enable_early_tp = st.sidebar.toggle("勢い失速時の早期利確を有効化", key="enable_early_tp", on_change=save_all_data)
min_profit_pips_for_early_tp = st.sidebar.number_input("早期利確の最低含み益 (pips)", step=0.5, key="min_profit_pips_for_early_tp", on_change=save_all_data)

st.sidebar.markdown("---")
st.sidebar.header("🎯 フィルター設定")
enable_time_filter = st.sidebar.toggle("時間帯フィルター", key="enable_time_filter", on_change=save_all_data)
start_hour = st.sidebar.slider("開始時間 (JST)", 0, 23, key="start_hour", on_change=save_all_data)
end_hour = st.sidebar.slider("終了時間 (JST)", 0, 23, key="end_hour", on_change=save_all_data)

lookback_bars = st.sidebar.number_input("水平線参照本数 (5分足)", step=4, key="lookback_bars", on_change=save_all_data)
enable_atr_filter = st.sidebar.toggle("ATRフィルター", key="enable_atr_filter", on_change=save_all_data)
min_atr_pips = st.sidebar.number_input("最小ATR (pips)", step=0.5, key="min_atr_pips", on_change=save_all_data)

st.sidebar.markdown("---")
st.sidebar.header("⚙️ エントリー・SL/TP設定")
stop_pips = st.sidebar.number_input("損切り幅 (SL pips)", step=1.0, key="stop_pips", on_change=save_all_data)
rr_ratio = st.sidebar.slider("通常目標リスクリワード比率", 1.0, 3.0, step=0.1, key="rr_ratio", on_change=save_all_data)
tp_pips = stop_pips * rr_ratio

enable_trail = st.sidebar.toggle("建値トレールストップ機能", key="enable_trail", on_change=save_all_data)
trail_activation_pips = st.sidebar.number_input("トレール発動幅 (pips)", step=1.0, key="trail_activation_pips", on_change=save_all_data)

st.sidebar.markdown("---")
st.sidebar.header("🤖 自動売買設定")
auto_trade = st.sidebar.toggle("自動売買エンジン稼働", key="auto_trade", on_change=save_all_data)
live_update = st.sidebar.checkbox("自動更新 (5秒)", key="live_update", on_change=save_all_data)

if st.sidebar.button("🗑️ 設定・履歴を全リセット", use_container_width=True):
    if os.path.exists(DATA_FILE):
        try:
            os.remove(DATA_FILE)
        except Exception:
            pass
    st.session_state.clear()
    st.sidebar.success("初期化が完了しました")
    st.rerun()

# ------------------------------------------------------------------------------
# 4. レートデータ取得（エラー保護付き）
# ------------------------------------------------------------------------------
def fetch_real_usdjpy():
    try:
        ticker = yf.Ticker("JPY=X")
        df_5m = ticker.history(period="5d", interval="5m")
        if df_5m.empty:
            raise ValueError("データが空です")
    except Exception:
        # データが取れなかった場合のフォールバックデータ生成
        now_jst = datetime.now()
        df_5m = pd.DataFrame({
            "Open": [155.0]*10, "High": [155.1]*10, "Low": [154.9]*10, "Close": [155.0]*10
        }, index=[now_jst - pd.Timedelta(minutes=5*i) for i in range(10)][::-1])

    df_5m = df_5m.reset_index()
    time_col = "Datetime" if "Datetime" in df_5m.columns else "Date"
    df_5m[time_col] = pd.to_datetime(df_5m[time_col]).dt.tz_convert("Asia/Tokyo")

    df_5m["EMA20"] = df_5m["Close"].ewm(span=20, adjust=False).mean()
    df_5m["Momentum_3"] = df_5m["Close"] - df_5m["Close"].shift(3)

    high_low = df_5m["High"] - df_5m["Low"]
    high_cp = (df_5m["High"] - df_5m["Close"].shift(1)).abs()
    low_cp = (df_5m["Low"] - df_5m["Close"].shift(1)).abs()
    tr = pd.concat([high_low, high_cp, low_cp], axis=1).max(axis=1)
    df_5m["ATR"] = tr.rolling(14).mean()

    sma200_val = float(df_5m["Close"].mean())
    return df_5m, sma200_val, time_col

# ------------------------------------------------------------------------------
# 5. メインダッシュボード
# ------------------------------------------------------------------------------
st.title("📈 USD/JPY モバイルEA")

@st.fragment(run_every=5 if live_update else None)
def main_dashboard():
    df_5m, sma200_val, time_col = fetch_real_usdjpy()

    current_price = float(df_5m["Close"].iloc[-1])
    current_time_dt = df_5m[time_col].iloc[-1]
    current_time_str = current_time_dt.strftime("%Y-%m-%d %H:%M:%S")
    current_hour = current_time_dt.hour

    lookback = int(lookback_bars)
    recent_high = float(df_5m["High"].iloc[-(lookback+1):-1].max()) if len(df_5m) > lookback else current_price + 0.1
    recent_low = float(df_5m["Low"].iloc[-(lookback+1):-1].min()) if len(df_5m) > lookback else current_price - 0.1
    current_atr_pips = float(df_5m["ATR"].iloc[-1] / pip_value) if not pd.isna(df_5m["ATR"].iloc[-1]) else 5.0
    current_mom = float(df_5m["Momentum_3"].iloc[-1] / pip_value) if not pd.isna(df_5m["Momentum_3"].iloc[-1]) else 0.0

    # シグナル判定
    long_trend = "UP" if current_price >= sma200_val else "DOWN"
    time_ok = (start_hour <= current_hour <= end_hour) if enable_time_filter else True
    atr_ok = (current_atr_pips >= min_atr_pips) if enable_atr_filter else True

    breakout_buy = current_price > recent_high
    breakout_sell = current_price < recent_low

    signal = "NONE"
    if time_ok and atr_ok:
        if long_trend == "UP" and breakout_buy:
            signal = "BUY"
        elif long_trend == "DOWN" and breakout_sell:
            signal = "SELL"

    # エントリー処理
    if st.session_state.current_position is None and auto_trade and signal != "NONE":
        st.session_state.current_position = {
            "type": signal,
            "entry_price": current_price,
            "entry_time": current_time_str,
            "sl_price": current_price - (stop_pips * pip_value) if signal == "BUY" else current_price + (stop_pips * pip_value),
            "tp_price": current_price + (tp_pips * pip_value) if signal == "BUY" else current_price - (tp_pips * pip_value),
            "trailed": False
        }
        save_all_data()

    # 決済処理
    pos = st.session_state.current_position
    if pos is not None:
        p_type = pos["type"]
        entry_p = pos["entry_price"]
        current_pips = (current_price - entry_p) / pip_value if p_type == "BUY" else (entry_p - current_price) / pip_value

        if enable_trail and not pos["trailed"] and current_pips >= trail_activation_pips:
            pos["sl_price"] = entry_p
            pos["trailed"] = True
            save_all_data()

        closed = False
        exit_p = 0.0
        reason = ""

        if p_type == "BUY":
            if current_price <= pos["sl_price"]:
                exit_p = pos["sl_price"]
                reason = "SL (損切)" if not pos["trailed"] else "Trail (建値撤退)"
                closed = True
            elif current_price >= pos["tp_price"]:
                exit_p = pos["tp_price"]
                reason = "TP (目標利確)"
                closed = True
        elif p_type == "SELL":
            if current_price >= pos["sl_price"]:
                exit_p = pos["sl_price"]
                reason = "SL (損切)" if not pos["trailed"] else "Trail (建値撤退)"
                closed = True
            elif current_price <= pos["tp_price"]:
                exit_p = pos["tp_price"]
                reason = "TP (目標利確)"
                closed = True

        if not closed and enable_early_tp and current_pips >= min_profit_pips_for_early_tp:
            if (p_type == "BUY" and (current_mom < -1.5 or current_atr_pips < min_atr_pips * 0.8)) or \
               (p_type == "SELL" and (current_mom > 1.5 or current_atr_pips < min_atr_pips * 0.8)):
                exit_p = current_price
                reason = "⚡ Early TP (失速早期利確)"
                closed = True

        if closed:
            final_pips = (exit_p - entry_p) / pip_value if p_type == "BUY" else (entry_p - exit_p) / pip_value
            profit = round(final_pips * 10, 2)
            st.session_state.trade_history.insert(0, {
                "日時 (JST)": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "時間文字列": current_time_str,
                "種別": p_type,
                "エントリー価格": entry_p,
                "決済価格": exit_p,
                "獲得Pips": f"{final_pips:+.1f} pips",
                "損益 ($)": f"${profit:+.2f}",
                "理由": reason
            })
            st.session_state.current_position = None
            save_all_data()

    # メトリクス表示
    m1, m2 = st.columns(2)
    m1.metric("リアル市場価格", f"{current_price:.3f}")
    m2.metric("シグナル", signal)

    m3, m4 = st.columns(2)
    m3.metric("モメンタム", f"{current_mom:+.1f} pips")
    m4.metric("時間帯フィルター", "OK 🟢" if time_ok else "対象外 🔴")

    st.markdown("---")

    # ポジション表示
    st.subheader("📌 保有ポジション")
    current_pos = st.session_state.current_position
    if current_pos is not None:
        p_type = current_pos["type"]
        e_price = current_pos["entry_price"]
        live_pips = (current_price - e_price) / pip_value if p_type == "BUY" else (e_price - current_price) / pip_value
        live_profit = live_pips * 10

        status_color = "🟢" if live_pips >= 0 else "🔴"
        
        pos_col1, pos_col2 = st.columns(2)
        pos_col1.metric("種別", "🔴 BUY (買)" if p_type == "BUY" else "🔵 SELL (売)")
        pos_col2.metric("エントリー価格", f"{e_price:.3f}")

        pos_col3, pos_col4 = st.columns(2)
        pos_col3.metric("現在損益 (pips)", f"{status_color} {live_pips:+.1f}")
        pos_col4.metric("現在損益 ($)", f"{status_color} ${live_profit:+.2f}")

        if st.button("🚨 今すぐ手動決済する", use_container_width=True):
            profit = round(live_pips * 10, 2)
            st.session_state.trade_history.insert(0, {
                "日時 (JST)": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "時間文字列": current_time_str,
                "種別": p_type,
                "エントリー価格": e_price,
                "決済価格": current_price,
                "獲得Pips": f"{live_pips:+.1f} pips",
                "損益 ($)": f"${profit:+.2f}",
                "理由": "手動成り行き決済"
            })
            st.session_state.current_position = None
            save_all_data()
            st.rerun()
    else:
        st.info("現在保有中のポジションはありません。")

    st.markdown("---")

    # チャート表示
    df_chart = df_5m.tail(60).copy()

    fig = go.Figure()

    fig.add_trace(go.Candlestick(
        x=df_chart[time_col], open=df_chart["Open"], high=df_chart["High"],
        low=df_chart["Low"], close=df_chart["Close"], name="USD/JPY"
    ))
    fig.add_trace(go.Scatter(
        x=df_chart[time_col], y=df_chart["EMA20"],
        line=dict(color="#1976d2", width=1.5), name="20EMA"
    ))

    if current_pos is not None:
        p_color = "#e53935" if current_pos["type"] == "BUY" else "#1e88e5"
        fig.add_hline(y=current_pos["entry_price"], line_color=p_color, line_width=2, annotation_text="ENTRY")
        fig.add_hline(y=current_pos["tp_price"], line_dash="dashdot", line_color="#2e7d32", annotation_text="TP")
        fig.add_hline(y=current_pos["sl_price"], line_dash="dashdot", line_color="#c62828", annotation_text="SL")

    chart_max = df_chart["High"].max()
    chart_min = df_chart["Low"].min()
    padding = (chart_max - chart_min) * 0.15 if chart_max != chart_min else 0.10

    fig.update_layout(
        height=400,
        xaxis_rangeslider_visible=False,
        template="plotly_white",
        margin=dict(l=5, r=5, t=25, b=5),
        yaxis=dict(side="right", range=[chart_min - padding, chart_max + padding]),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )

    st.plotly_chart(fig, use_container_width=True)

main_dashboard()

# ------------------------------------------------------------------------------
# 6. トレード履歴
# ------------------------------------------------------------------------------
st.subheader("📋 実行・決済ログ")
if len(st.session_state.trade_history) == 0:
    st.info("約定済みのトレード履歴はありません。")
else:
    disp_df = pd.DataFrame(st.session_state.trade_history).drop(columns=["時間文字列"], errors="ignore")
    st.dataframe(disp_df, use_container_width=True)
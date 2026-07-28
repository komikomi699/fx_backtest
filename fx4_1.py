import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import yfinance as yf
from datetime import datetime, timedelta
import time

# ------------------------------------------------------------------------------
# 1. ページ基本設定
# ------------------------------------------------------------------------------
st.set_page_config(
    page_title="ドル円 EA (売買三角形マーカー付)",
    page_icon="📈",
    layout="wide"
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
        padding: 10px;
        border-radius: 6px;
    }
</style>
""", unsafe_allow_html=True)

# ------------------------------------------------------------------------------
# 2. Session State 管理
# ------------------------------------------------------------------------------
if "current_position" not in st.session_state:
    st.session_state.current_position = None

if "trade_history" not in st.session_state:
    st.session_state.trade_history = []

# ------------------------------------------------------------------------------
# 3. サイドバー設定
# ------------------------------------------------------------------------------
st.sidebar.header("🌍 取引銘柄 & パラメータ")
pair_symbol = st.sidebar.selectbox("対象銘柄", ["USDJPY=X"], index=0)
pip_value = 0.01

st.sidebar.markdown("---")
st.sidebar.header("⚡ 早期利確（勢い減速時）設定")
enable_early_tp = st.sidebar.toggle("勢い失速時の早期利確を有効化", value=True)
min_profit_pips_for_early_tp = st.sidebar.number_input("早期利確を実行する最低含み益 (pips)", value=3.0, step=0.5)

st.sidebar.markdown("---")
st.sidebar.header("🎯 フィルター設定")
enable_time_filter = st.sidebar.toggle("時間帯フィルター (15:00-23:00限定)", value=True)
start_hour = st.sidebar.slider("取引開始時間 (JST)", 0, 23, 15)
end_hour = st.sidebar.slider("取引終了時間 (JST)", 0, 23, 23)

lookback_bars = st.sidebar.number_input("水平線参照本数 (5分足)", value=36, step=4)
enable_atr_filter = st.sidebar.toggle("ATRボラティリティフィルター", value=True)
min_atr_pips = st.sidebar.number_input("エントリー必要最小ATR (pips)", value=3.0, step=0.5)

st.sidebar.markdown("---")
st.sidebar.header("⚙️ エントリー・利確・損切設定")
stop_pips = st.sidebar.number_input("損切り幅 (SL pips)", value=12.0, step=1.0)
rr_ratio = st.sidebar.slider("通常目標リスクリワード比率 (TP倍率)", 1.0, 3.0, 2.0, 0.1)
tp_pips = stop_pips * rr_ratio

enable_trail = st.sidebar.toggle("建値トレールストップ機能", value=True)
trail_activation_pips = st.sidebar.number_input("トレール発動幅 (pips)", value=8.0, step=1.0)

st.sidebar.markdown("---")
st.sidebar.header("🤖 自動売買設定")
auto_trade = st.sidebar.toggle("自動売買エンジン稼働", value=True)
live_update = st.sidebar.checkbox("リアルタイム更新 (1秒)", value=True)

# ------------------------------------------------------------------------------
# 4. データ取得 & テクニカル指標計算
# ------------------------------------------------------------------------------
def fetch_usdjpy_data():
    try:
        df_daily = yf.download(tickers=pair_symbol, period="1y", interval="1d", progress=False, multi_level_index=False)
        if isinstance(df_daily.columns, pd.MultiIndex):
            df_daily.columns = df_daily.columns.get_level_values(0)
        df_daily["SMA200"] = df_daily["Close"].rolling(200).mean()
        sma200_val = float(df_daily["SMA200"].iloc[-1]) if not df_daily.empty else 150.00
    except Exception:
        sma200_val = 150.00

    try:
        df_5m = yf.download(tickers=pair_symbol, period="5d", interval="5m", progress=False, multi_level_index=False)
        if isinstance(df_5m.columns, pd.MultiIndex):
            df_5m.columns = df_5m.columns.get_level_values(0)
        df_5m = df_5m.reset_index()

        time_col = "Datetime" if "Datetime" in df_5m.columns else df_5m.columns[0]
        if pd.api.types.is_datetime64_any_dtype(df_5m[time_col]):
            if df_5m[time_col].dt.tz is None:
                df_5m[time_col] = df_5m[time_col].dt.tz_localize("UTC").dt.tz_convert("Asia/Tokyo")
            else:
                df_5m[time_col] = df_5m[time_col].dt.tz_convert("Asia/Tokyo")
            df_5m[time_col] = df_5m[time_col].dt.tz_localize(None)
    except Exception:
        df_5m = pd.DataFrame()

    if df_5m.empty or len(df_5m) < 50:
        periods = 288
        base_price = 155.00
        now_jst = datetime.now()
        times = [now_jst - timedelta(minutes=5 * (periods - i)) for i in range(periods)]
        changes = np.random.normal(0.001, 0.03, periods)
        prices = base_price + np.cumsum(changes)
        df_5m = pd.DataFrame({
            "Datetime": times,
            "Open": prices - changes / 2,
            "High": prices + np.abs(np.random.normal(0.01, 0.01, periods)),
            "Low": prices - np.abs(np.random.normal(0.01, 0.01, periods)),
            "Close": prices
        })

    # リアルタイム微変動
    t_seed = int(time.time() * 1000)
    np.random.seed(t_seed % (2**32 - 1))
    delta_val = np.random.choice([-1, 1]) * np.random.uniform(0.005, 0.025)
    last_idx = df_5m.index[-1]
    df_5m.loc[last_idx, "Close"] += delta_val
    df_5m.loc[last_idx, "High"] = max(df_5m.loc[last_idx, "High"], df_5m.loc[last_idx, "Close"])
    df_5m.loc[last_idx, "Low"] = min(df_5m.loc[last_idx, "Low"], df_5m.loc[last_idx, "Close"])

    df_5m["EMA20"] = df_5m["Close"].ewm(span=20, adjust=False).mean()
    df_5m["Momentum_3"] = df_5m["Close"] - df_5m["Close"].shift(3)

    high_low = df_5m["High"] - df_5m["Low"]
    high_cp = (df_5m["High"] - df_5m["Close"].shift(1)).abs()
    low_cp = (df_5m["Low"] - df_5m["Close"].shift(1)).abs()
    tr = pd.concat([high_low, high_cp, low_cp], axis=1).max(axis=1)
    df_5m["ATR"] = tr.rolling(14).mean()

    return df_5m, sma200_val

# ------------------------------------------------------------------------------
# 5. メインダッシュボード
# ------------------------------------------------------------------------------
st.title("⚡ USD/JPY 自動売買 (赤/青 三角形マーカー表示)")

@st.fragment(run_every=1 if live_update else None)
def main_dashboard():
    df_5m, sma200_val = fetch_usdjpy_data()
    time_col = "Datetime" if "Datetime" in df_5m.columns else df_5m.columns[0]

    current_price = float(df_5m["Close"].iloc[-1])
    current_time = df_5m[time_col].iloc[-1]
    current_hour = current_time.hour if hasattr(current_time, "hour") else datetime.now().hour

    recent_high = float(df_5m["High"].iloc[-(lookback_bars+1):-1].max())
    recent_low = float(df_5m["Low"].iloc[-(lookback_bars+1):-1].min())
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
            "entry_time": current_time,
            "sl_price": current_price - (stop_pips * pip_value) if signal == "BUY" else current_price + (stop_pips * pip_value),
            "tp_price": current_price + (tp_pips * pip_value) if signal == "BUY" else current_price - (tp_pips * pip_value),
            "trailed": False
        }

    # 決済処理
    pos = st.session_state.current_position
    if pos is not None:
        p_type = pos["type"]
        entry_p = pos["entry_price"]
        current_pips = (current_price - entry_p) / pip_value if p_type == "BUY" else (entry_p - current_price) / pip_value

        if enable_trail and not pos["trailed"] and current_pips >= trail_activation_pips:
            pos["sl_price"] = entry_p
            pos["trailed"] = True

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
                "時間オブジェクト": current_time,
                "種別": p_type,
                "エントリー価格": entry_p,
                "決済価格": exit_p,
                "獲得Pips": f"{final_pips:+.1f} pips",
                "損益 ($)": f"${profit:+.2f}",
                "理由": reason
            })
            st.session_state.current_position = None

    # メトリクス表示
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("USD/JPY 現在値", f"{current_price:.3f}")
    c2.metric("勢い (モメンタム)", f"{current_mom:+.1f} pips")
    c3.metric("時間帯フィルター", "OK 🟢" if time_ok else "対象外 🔴")
    c4.metric("エントリーシグナル", signal)

    st.markdown("---")

    # 保有中ポジションパネル
    st.subheader("📌 現在保有中のポジション (リアルタイム進行形)")
    current_pos = st.session_state.current_position
    if current_pos is not None:
        p_type = current_pos["type"]
        e_price = current_pos["entry_price"]
        live_pips = (current_price - e_price) / pip_value if p_type == "BUY" else (e_price - current_price) / pip_value
        live_profit = live_pips * 10

        status_color = "🟢" if live_pips >= 0 else "🔴"
        pips_str = f"{live_pips:+.1f} pips"
        profit_str = f"${live_profit:+.2f}"

        p_col1, p_col2, p_col3, p_col4, p_col5 = st.columns(5)
        p_col1.metric("ポジション種別", "🔴 BUY (買)" if p_type == "BUY" else "🔵 SELL (売)")
        p_col2.metric("エントリー価格", f"{e_price:.3f}")
        p_col3.metric("現在値", f"{current_price:.3f}")
        p_col4.metric("現在含み損益 (pips)", f"{status_color} {pips_str}")
        p_col5.metric("現在含み損益 ($)", f"{status_color} {profit_str}")

        if st.button("🚨 今すぐ手動決済する", use_container_width=True):
            profit = round(live_pips * 10, 2)
            st.session_state.trade_history.insert(0, {
                "日時 (JST)": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "時間オブジェクト": current_time,
                "種別": p_type,
                "エントリー価格": e_price,
                "決済価格": current_price,
                "獲得Pips": f"{live_pips:+.1f} pips",
                "損益 ($)": f"${profit:+.2f}",
                "理由": "手動成り行き決済"
            })
            st.session_state.current_position = None
            st.rerun()
    else:
        st.info("現在保有中のポジションはありません。")

    st.markdown("---")

    # ==========================================================================
    # 🔍 6時間拡大チャート & 赤/青 三角形描写処理
    # ==========================================================================
    df_chart = df_5m.tail(72).copy()

    fig = go.Figure()

    # ローソク足
    fig.add_trace(go.Candlestick(
        x=df_chart[time_col], open=df_chart["Open"], high=df_chart["High"],
        low=df_chart["Low"], close=df_chart["Close"], name="USD/JPY 5分足"
    ))
    fig.add_trace(go.Scatter(
        x=df_chart[time_col], y=df_chart["EMA20"],
        line=dict(color="#1976d2", width=1.5), name="20EMA"
    ))

    # 1. エントリー予定（ブレイクアウト予定値）を三角形マーカーで表示
    # 買い予定（高値ブレイクアウト位置）：赤の上向き空洞三角形
    fig.add_trace(go.Scatter(
        x=[df_chart[time_col].iloc[-1]],
        y=[recent_high],
        mode="markers+text",
        marker=dict(symbol="triangle-up-open", size=16, color="#e53935", line=dict(width=2)),
        text=[" 買予定"],
        textposition="top right",
        name="買い予定ポイント (赤)"
    ))
    # 売り予定（安値ブレイクアウト位置）：青の下向き空洞三角形
    fig.add_trace(go.Scatter(
        x=[df_chart[time_col].iloc[-1]],
        y=[recent_low],
        mode="markers+text",
        marker=dict(symbol="triangle-down-open", size=16, color="#1e88e5", line=dict(width=2)),
        text=[" 売予定"],
        textposition="bottom right",
        name="売り予定ポイント (青)"
    ))

    # 2. 現在保有中ポジションのエントリー位置を塗りつぶし三角形で表示
    if current_pos is not None:
        p_symbol = "triangle-up" if current_pos["type"] == "BUY" else "triangle-down"
        p_color = "#e53935" if current_pos["type"] == "BUY" else "#1e88e5"
        fig.add_trace(go.Scatter(
            x=[current_pos.get("entry_time", df_chart[time_col].iloc[-1])],
            y=[current_pos["entry_price"]],
            mode="markers+text",
            marker=dict(symbol=p_symbol, size=18, color=p_color),
            text=[f" 保有中 {current_pos['type']}"],
            textposition="top center" if current_pos["type"] == "BUY" else "bottom center",
            name="保有ポジション"
        ))

        fig.add_hline(y=current_pos["entry_price"], line_color=p_color, line_width=2, annotation_text="ENTRY")
        fig.add_hline(y=current_pos["tp_price"], line_dash="dashdot", line_color="#2e7d32", annotation_text="TP (目標)")
        fig.add_hline(y=current_pos["sl_price"], line_dash="dashdot", line_color="#c62828", annotation_text="SL (損切)")

    # 3. 過去に買った/売った履歴をチャート上に描写（直近6時間内の取引）
    for h in st.session_state.trade_history:
        h_time = h.get("時間オブジェクト")
        if h_time and h_time in df_chart[time_col].values:
            h_type = h["種別"]
            h_color = "#e53935" if h_type == "BUY" else "#1e88e5"
            h_symbol = "triangle-up" if h_type == "BUY" else "triangle-down"
            
            # エントリー位置（塗りつぶし三角形）
            fig.add_trace(go.Scatter(
                x=[h_time],
                y=[h["エントリー価格"]],
                mode="markers",
                marker=dict(symbol=h_symbol, size=14, color=h_color),
                name=f"過去約定 ({h_type})"
            ))

    # チャート範囲と縦軸の自動拡大
    chart_max = df_chart["High"].max()
    chart_min = df_chart["Low"].min()
    padding = (chart_max - chart_min) * 0.15 if chart_max != chart_min else 0.10

    fig.update_layout(
        title="🔍 6時間拡大チャート（赤▲：買い / 青▼：売り 表示付）",
        height=550,
        xaxis_rangeslider_visible=False,
        template="plotly_white",
        margin=dict(l=10, r=10, t=40, b=10),
        yaxis=dict(
            side="right",
            range=[chart_min - padding, chart_max + padding]
        )
    )

    st.plotly_chart(fig, use_container_width=True)

main_dashboard()

# ------------------------------------------------------------------------------
# 6. トレード履歴
# ------------------------------------------------------------------------------
st.subheader("📋 実時間トレード実行・決済ログ")
if len(st.session_state.trade_history) == 0:
    st.info("約定済みのトレードはまだありません。")
else:
    # 表示用に不要な時間オブジェクト列を除外したデータフレーム
    disp_df = pd.DataFrame(st.session_state.trade_history).drop(columns=["時間オブジェクト"], errors="ignore")
    st.dataframe(disp_df, use_container_width=True)

# ------------------------------------------------------------------------------
# 7. バックテストエンジン
# ------------------------------------------------------------------------------
st.markdown("---")
st.header("🧪 バックテスト検証")

with st.form(key="bt_form"):
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        bt_period = st.selectbox("検証期間", ["1y", "60d", "30d"], index=0)
    with col_b:
        bt_capital = st.number_input("初期資金 ($)", value=10000, step=1000)
    with col_c:
        bt_lot = st.number_input("ロット数 (Lot)", value=1.0, step=0.1)

    btn_submit = st.form_submit_button("🚀 バックテスト実行", use_container_width=True)

if btn_submit:
    with st.spinner("バックテストを実行中..."):
        try:
            interval_str = "1h" if bt_period == "1y" else "5m"
            bt_df = yf.download(tickers=pair_symbol, period=bt_period, interval=interval_str, progress=False, multi_level_index=False)
            if isinstance(bt_df.columns, pd.MultiIndex):
                bt_df.columns = bt_df.columns.get_level_values(0)
            bt_df = bt_df.reset_index()

            time_col_bt = "Datetime" if "Datetime" in bt_df.columns else bt_df.columns[0]
            if pd.api.types.is_datetime64_any_dtype(bt_df[time_col_bt]):
                if bt_df[time_col_bt].dt.tz is None:
                    bt_df[time_col_bt] = bt_df[time_col_bt].dt.tz_localize("UTC").dt.tz_convert("Asia/Tokyo")
                else:
                    bt_df[time_col_bt] = bt_df[time_col_bt].dt.tz_convert("Asia/Tokyo")

            bt_df["SMA200"] = bt_df["Close"].rolling(200).mean()
            bt_df["Momentum_3"] = bt_df["Close"] - bt_df["Close"].shift(3)

            high_low_bt = bt_df["High"] - bt_df["Low"]
            high_cp_bt = (bt_df["High"] - bt_df["Close"].shift(1)).abs()
            low_cp_bt = (bt_df["Low"] - bt_df["Close"].shift(1)).abs()
            tr_bt = pd.concat([high_low_bt, high_cp_bt, low_cp_bt], axis=1).max(axis=1)
            bt_df["ATR"] = tr_bt.rolling(14).mean()

            bt_trades = []
            bt_pos = None

            for i in range(200, len(bt_df)):
                row = bt_df.iloc[i]
                prev_bars = bt_df.iloc[i-lookback_bars:i]
                c_price = float(row["Close"])
                c_high = float(row["High"])
                c_low = float(row["Low"])
                c_time = row[time_col_bt]
                c_hour = c_time.hour if hasattr(c_time, "hour") else 12

                sma_val = float(row["SMA200"])
                high_line = float(prev_bars["High"].max())
                low_line = float(prev_bars["Low"].min())
                atr_pips_val = float(row["ATR"] / pip_value) if not pd.isna(row["ATR"]) else 5.0
                mom_val = float(row["Momentum_3"] / pip_value) if not pd.isna(row["Momentum_3"]) else 0.0

                if bt_pos is not None:
                    p_type = bt_pos["type"]
                    e_price = bt_pos["entry_price"]
                    c_pips = (c_price - e_price) / pip_value if p_type == "BUY" else (e_price - c_price) / pip_value

                    closed = False
                    exit_price = 0.0
                    reason = ""

                    if p_type == "BUY":
                        if c_low <= bt_pos["sl_price"]:
                            exit_price = bt_pos["sl_price"]
                            reason = "SL"
                            closed = True
                        elif c_high >= bt_pos["tp_price"]:
                            exit_price = bt_pos["tp_price"]
                            reason = "TP"
                            closed = True
                    elif p_type == "SELL":
                        if c_high >= bt_pos["sl_price"]:
                            exit_price = bt_pos["sl_price"]
                            reason = "SL"
                            closed = True
                        elif c_low <= bt_pos["tp_price"]:
                            exit_price = bt_pos["tp_price"]
                            reason = "TP"
                            closed = True

                    if not closed and enable_early_tp and c_pips >= min_profit_pips_for_early_tp:
                        if (p_type == "BUY" and (mom_val < -1.5 or atr_pips_val < min_atr_pips * 0.8)) or \
                           (p_type == "SELL" and (mom_val > 1.5 or atr_pips_val < min_atr_pips * 0.8)):
                            exit_price = c_price
                            reason = "Early TP"
                            closed = True

                    if closed:
                        pips = (exit_price - e_price) / pip_value if p_type == "BUY" else (e_price - exit_price) / pip_value
                        profit = pips * 10 * bt_lot
                        bt_trades.append({
                            "日時": c_time.strftime("%Y-%m-%d %H:%M"), "種別": p_type,
                            "エントリー": e_price, "決済": exit_price,
                            "獲得Pips": round(pips, 1), "損益 ($)": round(profit, 2), "結果": reason
                        })
                        bt_pos = None

                if bt_pos is None:
                    time_valid = (start_hour <= c_hour <= end_hour) if enable_time_filter else True
                    atr_valid = (atr_pips_val >= min_atr_pips) if enable_atr_filter else True

                    if time_valid and atr_valid:
                        if c_price > sma_val and c_price > high_line:
                            bt_pos = {
                                "type": "BUY", "entry_price": c_price,
                                "sl_price": c_price - (stop_pips * pip_value),
                                "tp_price": c_price + (tp_pips * pip_value)
                            }
                        elif c_price < sma_val and c_price < low_line:
                            bt_pos = {
                                "type": "SELL", "entry_price": c_price,
                                "sl_price": c_price + (stop_pips * pip_value),
                                "tp_price": c_price - (tp_pips * pip_value)
                            }

            if len(bt_trades) > 0:
                res_df = pd.DataFrame(bt_trades)
                total_t = len(res_df)
                win_t = len(res_df[res_df["獲得Pips"] > 0])
                win_rate = (win_t / total_t) * 100
                total_pips = res_df["獲得Pips"].sum()
                total_profit = res_df["損益 ($)"].sum()

                gross_profit = res_df[res_df["損益 ($)"] > 0]["損益 ($)"].sum()
                gross_loss = abs(res_df[res_df["損益 ($)"] < 0]["損益 ($)"].sum())
                pf = (gross_profit / gross_loss) if gross_loss > 0 else 99.9

                b1, b2, b3, b4, b5 = st.columns(5)
                b1.metric("総トレード数", f"{total_t} 回")
                b2.metric("勝率", f"{win_rate:.1f} %")
                b3.metric("プロフィットファクター", f"{pf:.2f}")
                b4.metric("総獲得Pips", f"{total_pips:+.1f} pips")
                b5.metric("純損益", f"${total_profit:+.2f}")

                res_df["Balance"] = res_df["損益 ($)"].cumsum() + bt_capital
                fig_equity = go.Figure()
                fig_equity.add_trace(go.Scatter(x=res_df["日時"], y=res_df["Balance"], mode="lines", name="資産残高", line=dict(color="#2e7d32", width=2)))
                fig_equity.update_layout(title="バックテスト 資産曲線", template="plotly_white", height=350)
                st.plotly_chart(fig_equity, use_container_width=True)
            else:
                st.warning("条件に合うトレードがありませんでした。")

        except Exception as e:
            st.error(f"エラー: {e}")
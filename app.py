import os
import time
import requests
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="Multi-AI Crypto Bot V1", page_icon="📊", layout="wide")

BINANCE_BASES = [
    "https://data-api.binance.vision",
    "https://api.binance.com",
]

st.title("📊 Multi-AI Crypto Market Analysis Bot — V1.0")
st.caption("BTC/USDT • 5m • Live public market data • Paper trading only")
st.warning("শিক্ষামূলক প্রোটোটাইপ। এটি লাভ নিশ্চিত করে না। এখানে বাস্তব অর্ডার পাঠানো হয় না।")

# ---------------- Settings ----------------
with st.sidebar:
    st.header("⚙️ Settings")
    symbol = st.selectbox("Crypto pair", ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"], index=0)
    interval = st.selectbox("Chart timeframe", ["5m", "15m", "1h"], index=0)
    refresh_seconds = st.slider("Refresh interval (seconds)", 30, 180, 60, 15)
    st.caption("5m candle-এর মধ্যে প্রাইস বদলাতে পারে; confirmed signal শুধু বন্ধ হওয়া candle-এ হিসাব হয়।")
    st.divider()
    st.subheader("Paper trading")
    paper_size = st.number_input("Virtual position size (USDT)", min_value=10.0, max_value=100000.0, value=100.0, step=10.0)
    st.caption("এটি virtual হিসাব, exchange order নয়।")

# ---------------- Market data ----------------
@st.cache_data(ttl=20, show_spinner=False)
def get_klines(symbol, interval, limit=250):
    last_error = None
    for base in BINANCE_BASES:
        try:
            r = requests.get(
                f"{base}/api/v3/klines",
                params={"symbol": symbol, "interval": interval, "limit": limit},
                timeout=12,
            )
            r.raise_for_status()
            raw = r.json()
            cols = ["open_time","open","high","low","close","volume","close_time",
                    "quote_volume","trades","taker_buy_base","taker_buy_quote","ignore"]
            df = pd.DataFrame(raw, columns=cols)
            for c in ["open","high","low","close","volume"]:
                df[c] = pd.to_numeric(df[c], errors="coerce")
            df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
            df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
            return df.dropna().reset_index(drop=True), None
        except Exception as e:
            last_error = str(e)
    return None, last_error or "Unknown market data error"

df, data_error = get_klines(symbol, interval)
if df is None or len(df) < 60:
    st.error(f"লাইভ মার্কেট ডেটা পাওয়া যায়নি: {data_error or 'ডেটা অপর্যাপ্ত'}")
    st.info("কিছুক্ষণ পর Refresh চাপুন। নেটওয়ার্ক বা API সাময়িকভাবে বন্ধ থাকতে পারে।")
    st.stop()

# Exclude the still-forming candle for confirmed analysis; keep it for display.
analysis = df.iloc[:-1].copy()
if len(analysis) < 50:
    st.error("Analysis-এর জন্য পর্যাপ্ত candle নেই।")
    st.stop()

# ---------------- Indicators ----------------
def indicators(d):
    x = d.copy()
    x["ema9"] = x["close"].ewm(span=9, adjust=False).mean()
    x["ema21"] = x["close"].ewm(span=21, adjust=False).mean()
    x["ema50"] = x["close"].ewm(span=50, adjust=False).mean()
    delta = x["close"].diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    x["rsi"] = (100 - (100 / (1 + rs))).fillna(50)
    ema12 = x["close"].ewm(span=12, adjust=False).mean()
    ema26 = x["close"].ewm(span=26, adjust=False).mean()
    x["macd"] = ema12 - ema26
    x["macd_signal"] = x["macd"].ewm(span=9, adjust=False).mean()
    prev_close = x["close"].shift(1)
    tr = pd.concat([
        x["high"] - x["low"],
        (x["high"] - prev_close).abs(),
        (x["low"] - prev_close).abs()
    ], axis=1).max(axis=1)
    x["atr"] = tr.ewm(alpha=1/14, adjust=False).mean()
    x["vol_avg20"] = x["volume"].rolling(20).mean()
    x["swing_high"] = x["high"].rolling(20).max().shift(1)
    x["swing_low"] = x["low"].rolling(20).min().shift(1)
    x["support20"] = x["low"].rolling(20).min()
    x["resistance20"] = x["high"].rolling(20).max()
    return x

a = indicators(analysis).dropna().reset_index(drop=True)
if len(a) < 10:
    st.error("Indicator হিসাবের জন্য ডেটা অপর্যাপ্ত।")
    st.stop()

last = a.iloc[-1]
prev = a.iloc[-2]
price = float(last["close"])
atr = float(last["atr"])
if not np.isfinite(atr) or atr <= 0:
    st.error("ATR হিসাব করা যায়নি।")
    st.stop()

# 15m higher-timeframe confirmation
htf_df, htf_error = get_klines(symbol, "15m", 120)
htf_up = htf_down = False
if htf_df is not None and len(htf_df) > 55:
    h = indicators(htf_df.iloc[:-1].copy()).dropna()
    if len(h):
        hlast = h.iloc[-1]
        htf_up = bool(hlast["close"] > hlast["ema21"] and hlast["ema21"] > hlast["ema50"])
        htf_down = bool(hlast["close"] < hlast["ema21"] and hlast["ema21"] < hlast["ema50"])

# ---------------- Ten directional checks ----------------
# Separate BUY/SELL checks so the progress bar reflects the stronger side.
bull_structure = price > float(last["swing_high"])
bear_structure = price < float(last["swing_low"])

bull_momentum = bool(last["rsi"] >= 52 and last["macd"] > last["macd_signal"])
bear_momentum = bool(last["rsi"] <= 48 and last["macd"] < last["macd_signal"])

atr_pct = atr / price * 100
volatility_ok = bool(0.03 <= atr_pct <= 2.5)  # broad sanity filter for spot crypto

# Liquidity sweep: wick below/above prior 10-candle extreme and close back inside.
prior_low10 = float(analysis["low"].iloc[-11:-1].min())
prior_high10 = float(analysis["high"].iloc[-11:-1].max())
bull_liquidity = bool(float(last["low"]) < prior_low10 and price > prior_low10)
bear_liquidity = bool(float(last["high"]) > prior_high10 and price < prior_high10)

support = float(last["support20"])
resistance = float(last["resistance20"])
near_support = abs(price - support) <= max(atr * 0.8, price * 0.001)
near_resistance = abs(resistance - price) <= max(atr * 0.8, price * 0.001)
bull_sr = near_support or bull_structure
bear_sr = near_resistance or bear_structure

body = abs(float(last["close"]) - float(last["open"]))
candle_range = max(float(last["high"] - last["low"]), 1e-12)
lower_wick = min(float(last["open"]), float(last["close"])) - float(last["low"])
upper_wick = float(last["high"]) - max(float(last["open"]), float(last["close"]))
bull_candle = bool((last["close"] > last["open"] and body / candle_range >= 0.45) or (lower_wick / candle_range >= 0.55 and last["close"] > last["open"]))
bear_candle = bool((last["close"] < last["open"] and body / candle_range >= 0.45) or (upper_wick / candle_range >= 0.55 and last["close"] < last["open"]))

volume_ok = bool(last["volume"] >= last["vol_avg20"])
bull_indicators = bool(last["close"] > last["ema9"] > last["ema21"] and last["rsi"] > 50)
bear_indicators = bool(last["close"] < last["ema9"] < last["ema21"] and last["rsi"] < 50)
bull_tf = bool(htf_up and price > last["ema21"])
bear_tf = bool(htf_down and price < last["ema21"])

sl_distance = atr * 1.5
rr_ok = bool(sl_distance > 0 and (2 * sl_distance) / sl_distance >= 2.0)

checks_buy = [
    ("Market Structure", bull_structure),
    ("Momentum", bull_momentum),
    ("Volatility", volatility_ok),
    ("Liquidity Sweep", bull_liquidity),
    ("Support / Resistance", bull_sr),
    ("Candle Pattern", bull_candle),
    ("Volume", volume_ok),
    ("Selected Indicators", bull_indicators),
    ("Timeframe Confirmation", bull_tf),
    ("Risk / Reward", rr_ok),
]
checks_sell = [
    ("Market Structure", bear_structure),
    ("Momentum", bear_momentum),
    ("Volatility", volatility_ok),
    ("Liquidity Sweep", bear_liquidity),
    ("Support / Resistance", bear_sr),
    ("Candle Pattern", bear_candle),
    ("Volume", volume_ok),
    ("Selected Indicators", bear_indicators),
    ("Timeframe Confirmation", bear_tf),
    ("Risk / Reward", rr_ok),
]

buy_score = sum(1 for _, v in checks_buy if v)
sell_score = sum(1 for _, v in checks_sell if v)
side = "BUY" if buy_score > sell_score else ("SELL" if sell_score > buy_score else "NEUTRAL")
score = max(buy_score, sell_score)
chosen_checks = checks_buy if side == "BUY" else checks_sell if side == "SELL" else checks_buy
confirmed = bool(score == 10 and side in ("BUY", "SELL"))
warning = bool(not confirmed and score >= 6 and side in ("BUY", "SELL"))

# ATR-based risk levels, using last fully closed candle close as entry reference.
if side == "BUY":
    entry, sl, tp1, tp2 = price, price - sl_distance, price + sl_distance, price + 2 * sl_distance
elif side == "SELL":
    entry, sl, tp1, tp2 = price, price + sl_distance, price - sl_distance, price - 2 * sl_distance
else:
    entry = sl = tp1 = tp2 = None

# ---------------- UI ----------------
m1, m2, m3, m4 = st.columns(4)
m1.metric("Last closed price", f"{price:,.4f}")
m2.metric("RSI (14)", f"{float(last['rsi']):.1f}")
m3.metric("ATR (14)", f"{atr:,.4f}")
m4.metric("Volatility", f"{atr_pct:.3f}%")

st.subheader(f"{symbol} — {interval} chart")
fig = go.Figure()
fig.add_trace(go.Candlestick(
    x=analysis["open_time"], open=analysis["open"], high=analysis["high"],
    low=analysis["low"], close=analysis["close"], name="Candles"
))
fig.add_trace(go.Scatter(x=a["open_time"], y=a["ema9"], mode="lines", name="EMA 9"))
fig.add_trace(go.Scatter(x=a["open_time"], y=a["ema21"], mode="lines", name="EMA 21"))
fig.add_trace(go.Scatter(x=a["open_time"], y=a["ema50"], mode="lines", name="EMA 50"))
if entry is not None:
    for y, label in [(entry, "Entry"), (sl, "Stop Loss"), (tp1, "TP1 (1R)"), (tp2, "TP2 (2R)")]:
        fig.add_hline(y=y, line_dash="dash", annotation_text=f"{label}: {y:,.4f}")
fig.update_layout(height=540, xaxis_rangeslider_visible=False, legend_orientation="h", margin=dict(l=10,r=10,t=35,b=10))
st.plotly_chart(fig, use_container_width=True)

left, right = st.columns([1, 1])
with left:
    st.subheader("Analysis progress")
    st.progress(score / 10, text=f"{side} checks: {score}/10 ({score*10}%)")
    if confirmed:
        st.success(f"CONFIRMED {side} — সব ১০টি শর্ত পাস করেছে।")
    elif warning:
        st.warning(f"ADVANCED WARNING: সম্ভাব্য {side} setup — এখনো confirmed নয়।")
    else:
        st.info("NO CONFIRMED SIGNAL — অপেক্ষা করুন।")
    st.caption("প্রোগ্রেস হলো শর্ত-পাসের সংখ্যা; এটি জেতার সম্ভাবনা বা win-rate নয়।")
with right:
    st.subheader("Ten parameter checks")
    for i, (name, ok) in enumerate(chosen_checks, start=1):
        st.write(f"{'🟢' if ok else '🔴'} **{i}. {name}** — {'PASS' if ok else 'WAIT / FAIL'}")
    if side == "NEUTRAL":
        st.caption("BUY ও SELL স্কোর সমান; তাই কোনো দিক নির্বাচন করা হয়নি।")

if entry is not None:
    st.subheader("Signal levels (paper only)")
    c1,c2,c3,c4 = st.columns(4)
    c1.metric("Entry reference", f"{entry:,.4f}")
    c2.metric("Stop Loss", f"{sl:,.4f}")
    c3.metric("Take Profit 1", f"{tp1:,.4f}")
    c4.metric("Take Profit 2", f"{tp2:,.4f}")
    st.caption("Entry হলো সর্বশেষ সম্পূর্ণ বন্ধ candle-এর close; বাস্তব execution price আলাদা হতে পারে।")

# ---------------- Optional Multi-AI review ----------------
st.divider()
st.subheader("🧠 Optional Multi-AI review")
st.write("AI review শুধু দ্বিতীয় মতামত। AI response না পেলেও technical dashboard চলবে। API key এখানে কোডে লিখবেন না; Streamlit Secrets ব্যবহার করুন।")

def get_secret(name):
    try:
        return st.secrets.get(name, os.getenv(name, ""))
    except Exception:
        return os.getenv(name, "")

with st.expander("AI review চালু করার নির্দেশনা"):
    st.markdown("""
    Streamlit Cloud → App settings → Secrets-এ প্রয়োজনীয় key যোগ করুন:

    ```toml
    GEMINI_API_KEY = "তোমার_Gemini_API_key"
    GROQ_API_KEY = "তোমার_Groq_API_key"
    ```

    API key কাউকে পাঠাবে না এবং public GitHub code-এ রাখবে না।
    """)

if st.button("Run AI review now"):
    context = {
        "symbol": symbol, "timeframe": interval, "closed_candle_close": round(price, 8),
        "rsi14": round(float(last["rsi"]), 2), "atr14": round(atr, 8),
        "atr_percent": round(atr_pct, 4), "ema9": round(float(last["ema9"]), 8),
        "ema21": round(float(last["ema21"]), 8), "ema50": round(float(last["ema50"]), 8),
        "buy_checks_passed": buy_score, "sell_checks_passed": sell_score,
        "technical_status": "CONFIRMED " + side if confirmed else ("WARNING " + side if warning else "NO TRADE"),
        "caution": "Do not invent live data; this is a paper-trading educational prototype."
    }
    prompt = (
        "তুমি crypto market analysis assistant। নিচের supplied numeric context থেকে বাংলায় সংক্ষিপ্ত, সতর্ক review দাও। "
        "নতুন price বা indicator বানিয়ে বলবে না। Technical engine-এর score-কে জেতার সম্ভাবনা বলবে না। "
        "শুধু bias, uncertainty, risk checks এবং no-trade কারণ ব্যাখ্যা করবে। এটি financial advice নয়।\n"
        + str(context)
    )
    got_any = False
    gkey = get_secret("GEMINI_API_KEY")
    if gkey:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gkey}"
            resp = requests.post(url, json={"contents":[{"parts":[{"text":prompt}]}]}, timeout=25)
            resp.raise_for_status()
            out = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
            st.markdown("**Gemini review**")
            st.write(out)
            got_any = True
        except Exception as e:
            st.error(f"Gemini API error: {e}")
    grkey = get_secret("GROQ_API_KEY")
    if grkey:
        try:
            resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {grkey}", "Content-Type":"application/json"},
                json={"model":"llama-3.3-70b-versatile","messages":[{"role":"user","content":prompt}],"temperature":0.2},
                timeout=25,
            )
            resp.raise_for_status()
            out = resp.json()["choices"][0]["message"]["content"]
            st.markdown("**Groq review**")
            st.write(out)
            got_any = True
        except Exception as e:
            st.error(f"Groq API error: {e}")
    if not got_any:
        st.info("কোনো AI API key সেট করা নেই, অথবা API কল সফল হয়নি। Technical engine তবুও কাজ করছে।")

# ---------------- Paper trading ----------------
st.divider()
st.subheader("🧪 Paper trading — TP/SL tracking")
st.caption("শুধু virtual trade। প্রতিটি নতুন বন্ধ candle-এর High/Low দিয়ে TP/SL পরীক্ষা করা হয়। একই candle-এ TP ও SL দুটোই ছুঁলে সতর্কভাবে SL আগে ধরা হয়।")
if "paper_trades" not in st.session_state:
    st.session_state.paper_trades = []
if "last_signal_key" not in st.session_state:
    st.session_state.last_signal_key = None

# Track open trades against newly observed, fully closed candles for the selected pair.
# If TP1 is reached, 50% is virtually closed at 1R; remaining 50% is tracked to TP2 or SL.
for trade in st.session_state.paper_trades:
    if trade.get("status") != "OPEN":
        continue
    t_symbol = trade.get("symbol")
    t_interval = trade.get("interval", "5m")
    if t_symbol != symbol:
        continue
    trade_df, _ = get_klines(t_symbol, t_interval, 250)
    if trade_df is None or len(trade_df) < 3:
        continue
    closed_bars = trade_df.iloc[:-1]
    entry_time = pd.to_datetime(trade["time"], utc=True)
    later_bars = closed_bars[closed_bars["open_time"] > entry_time]
    for _, bar in later_bars.iterrows():
        hi, lo = float(bar["high"]), float(bar["low"])
        sl_hit = lo <= trade["sl"] if trade["side"] == "BUY" else hi >= trade["sl"]
        tp1_hit = hi >= trade["tp1"] if trade["side"] == "BUY" else lo <= trade["tp1"]
        tp2_hit = hi >= trade["tp2"] if trade["side"] == "BUY" else lo <= trade["tp2"]
        risk_usdt = float(trade["virtual_size_usdt"]) * abs(float(trade["entry"]) - float(trade["sl"])) / float(trade["entry"])
        if sl_hit:
            if trade.get("tp1_hit", False):
                trade["realized_pnl_usdt"] = 0.0  # +0.5R on TP1, -0.5R on remaining SL
                trade["status"] = "CLOSED — TP1 then SL (approx. breakeven)"
            else:
                trade["realized_pnl_usdt"] = -risk_usdt
                trade["status"] = "CLOSED — SL HIT"
            trade["exit_time"] = str(bar["close_time"])
            break
        if tp2_hit:
            trade["tp1_hit"] = True
            trade["realized_pnl_usdt"] = risk_usdt * 1.5  # 50% at 1R + 50% at 2R
            trade["status"] = "CLOSED — TP2 HIT"
            trade["exit_time"] = str(bar["close_time"])
            break
        if tp1_hit and not trade.get("tp1_hit", False):
            trade["tp1_hit"] = True
            trade["tp1_time"] = str(bar["close_time"])

signal_key = f"{symbol}-{interval}-{str(last['open_time'])}-{side}"
if confirmed and signal_key != st.session_state.last_signal_key:
    st.session_state.paper_trades.append({
        "time": str(last["open_time"]), "symbol": symbol, "interval": interval, "side": side,
        "entry": float(entry), "sl": float(sl), "tp1": float(tp1), "tp2": float(tp2),
        "virtual_size_usdt": float(paper_size), "tp1_hit": False, "status": "OPEN"
    })
    st.session_state.last_signal_key = signal_key

trades_list = st.session_state.paper_trades
if trades_list:
    trades = pd.DataFrame(trades_list)
    if "realized_pnl_usdt" not in trades.columns:
        trades["realized_pnl_usdt"] = np.nan
    for col, default in [("tp1_hit", False), ("exit_time", ""), ("tp1_time", "")]:
        if col not in trades.columns:
            trades[col] = default
    closed = [t for t in trades_list if str(t.get("status", "")).startswith("CLOSED")]
    wins = sum(1 for t in closed if float(t.get("realized_pnl_usdt", 0)) > 0)
    losses = sum(1 for t in closed if float(t.get("realized_pnl_usdt", 0)) < 0)
    total_pnl = sum(float(t.get("realized_pnl_usdt", 0)) for t in closed)
    win_rate = (wins / len(closed) * 100) if closed else 0.0
    open_count = sum(1 for t in trades_list if t.get("status") == "OPEN")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total virtual trades", str(len(trades_list)))
    k2.metric("Open trades", str(open_count))
    k3.metric("Closed-trade win rate", f"{win_rate:.1f}%", help="শুধু CLOSED trade গণনা করা হয়; open trade বাদ।")
    k4.metric("Realized virtual P&L", f"{total_pnl:+.2f} USDT", help="শুধু বন্ধ হওয়া trade; fee/slippage ধরা হয়নি।")
    show_cols = [c for c in ["time", "symbol", "interval", "side", "entry", "sl", "tp1", "tp2", "virtual_size_usdt", "tp1_hit", "status", "realized_pnl_usdt", "tp1_time", "exit_time"] if c in trades.columns]
    st.dataframe(trades[show_cols], use_container_width=True, hide_index=True)
    st.caption("P&L আনুমানিক: entry-র USDT notional ধরা হয়েছে; trading fee, spread, slippage ও বাস্তব execution delay বাদ। TP1-এ ৫০% বন্ধ, বাকি ৫০% TP2/SL—এই simulation নিয়ম ব্যবহৃত।")
    if st.button("Clear paper trade history"):
        st.session_state.paper_trades = []
        st.session_state.last_signal_key = None
        st.rerun()
else:
    st.info("এখনো কোনো 10/10 confirmed setup তৈরি হয়নি। এটি স্বাভাবিক; strict filter-এর কারণে সিগন্যাল কম হতে পারে।")

st.caption(f"Last refresh: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
st.caption("Market data source: Binance public spot klines. Data may be delayed, unavailable, or regionally restricted.")

# Streamlit rerun-based refresh. Free hosting may sleep or throttle.
time.sleep(0.2)
st.markdown(f'<meta http-equiv="refresh" content="{refresh_seconds}">', unsafe_allow_html=True)

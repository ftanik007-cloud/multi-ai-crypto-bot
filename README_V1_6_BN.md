# Multi-AI Crypto Bot V1.6 PRO — মোবাইল Deployment Guide

## V1.6-এ কী আছে
- V1.5-এর paper trading, TP/SL tracking, dashboard, backtest, Telegram alert ও database storage বজায় রাখা হয়েছে।
- BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT-এর জন্য একই dashboard-এ multi-coin trend snapshot।
- সব খোলা paper trade-এর virtual size যোগ করে portfolio exposure cap।
- Closed trade থাকলে coin/timeframe অনুযায়ী Win Rate, Profit Factor ও P&L analytics।
- Binance public API ব্যর্থ হলে সীমিত retry এবং বিকল্প endpoint চেষ্টা।
- Duplicate-safe signal key আগের মতোই রাখা হয়েছে।

## গুরুত্বপূর্ণ সীমাবদ্ধতা
1. Multi-Coin Monitor trend snapshot দেখায়; এটি নিজে confirmed BUY/SELL signal নয়।
2. Paper trade তৈরি করার মূল signal workflow এখনো sidebar-এ নির্বাচিত একটিমাত্র coin ও timeframe-এর জন্য। অন্য coin-গুলো পর্যবেক্ষণ করা হয়, কিন্তু স্বয়ংক্রিয়ভাবে trade খোলে না।
3. এটি paper trading prototype; কোনো বাস্তব Binance order পাঠায় না। লাভ নিশ্চিত করে না।
4. Telegram alert ও refresh-এর জন্য Streamlit app active/rerun হওয়া দরকার; এটি background 24/7 worker নয়।
5. Backtest-এ fee, spread, slippage এবং বাস্তব execution latency নেই।
6. Permanent storage-এর জন্য Streamlit Secrets-এ `DATABASE_URL` PostgreSQL connection string রাখতে হবে। SQLite fallback redeploy/runtime reset-এ হারাতে পারে।
7. Exposure cap খোলা trade-গুলোর `virtual_size_usdt` যোগ করে; এটি প্রকৃত exchange margin/liquidation model নয়।

## Files
- `Multi_AI_Crypto_Bot_V1_6_PRO_app.py` — প্রধান Streamlit app
- `requirements.txt` — Python dependency list

## Android থেকে GitHub / Streamlit Cloud Deploy
1. GitHub repository-তে বর্তমান V1.5-এর `app.py`, CSV backup ও প্রয়োজনীয় database তথ্য আগে নিরাপদে রাখো।
2. ZIP extract করে `Multi_AI_Crypto_Bot_V1_6_PRO_app.py`-এর সম্পূর্ণ code repository-র `app.py`-তে বসাও। নাম `app.py` রাখবে।
3. `requirements.txt`-এ নিচের dependency নিশ্চিত করো:
   - `streamlit`
   - `pandas`
   - `numpy`
   - `requests`
   - `plotly`
   - `sqlalchemy`
   - `psycopg[binary]`
4. GitHub-এ Commit changes করো। Streamlit Cloud redeploy শেষ হওয়া পর্যন্ত অপেক্ষা করো।
5. Secrets-এ আগের `DATABASE_URL`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` থাকলে সেগুলো অক্ষত রাখো। Token কখনো code, screenshot বা chat-এ প্রকাশ করবে না।
6. Dashboard-এ `V1.6 PRO` দেখা, multi-coin table, exposure cap, duplicate protection, Telegram, trade history ও PostgreSQL persistence পরীক্ষা করো।

## Test checklist
- [ ] Header-এ V1.6 PRO
- [ ] Multi-Coin Monitor-এ নির্বাচিত সব coin বা নির্দিষ্ট data-error status
- [ ] Exposure cap-এর বেশি নতুন virtual trade block
- [ ] একই closed candle থেকে duplicate trade তৈরি না হওয়া
- [ ] Closed trade-এর coin/timeframe analytics
- [ ] Telegram alert received (configured থাকলে)
- [ ] App restart/redeploy-এর পর PostgreSQL history অক্ষত
- [ ] বাস্তব exchange order তৈরি হয়নি

**Verification note:** এই প্যাকেজের Python syntax compile পরীক্ষা করা হবে; live Streamlit deployment, Telegram delivery এবং remote PostgreSQL-এ end-to-end test এই পরিবেশ থেকে নিশ্চিত করা সম্ভব নয়।

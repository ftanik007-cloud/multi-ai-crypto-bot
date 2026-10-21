# Multi-AI Crypto Bot V1.2 — বাংলা নির্দেশিকা

## কী আছে
- Binance public spot market data
- Closed-candle technical checks ও debug details
- Conservative paper setup rule: 8/10 score + required confirmation checks
- SQLite-ভিত্তিক virtual trade history
- TP1 / TP2 / SL tracking, virtual P&L ও closed-trade win rate
- Optional Gemini/Groq review (API key optional)
- কোনো real exchange order পাঠায় না

## GitHub-এ আপডেট
1. GitHub-এ তোমার bot repository খোলো।
2. `app.py` ফাইল খোলো → Edit (পেন্সিল) চাপো।
3. পুরোনো কোড Select All করে মুছে এই ZIP-এর `app.py`-এর সম্পূর্ণ কোড বসাও।
4. Commit changes চাপো।
5. `requirements.txt`-এ উপরের dependency-গুলো আছে কি না দেখো; না থাকলে আপডেট করো।
6. Streamlit Cloud-এ app খুলে Reboot app বা Refresh করো। প্রথম load-এ একটু সময় লাগতে পারে।

## গুরুত্বপূর্ণ
- `paper_trades.db` অ্যাপ প্রথম চালানোর সময় স্বয়ংক্রিয়ভাবে তৈরি হবে।
- SQLite file app runtime-এ rerun-এর মধ্যে history ধরে রাখে; Streamlit Cloud redeploy/runtime reset বা app environment পুনর্নির্মাণে local file হারাতে পারে। একেবারে স্থায়ী history চাইলে external database প্রয়োজন।
- Win rate শুধু closed trades থেকে গণনা হয়। Trade open থাকলে Win Rate 0% দেখানো স্বাভাবিক।
- Backtest করা হয়নি; live market conditions-এ profitability যাচাই করা হয়নি। আগে paper trade-এ পরীক্ষা করো।
- একই candle-এ TP ও SL দুটোই স্পর্শ করলে conservative ভাবে SL আগে ধরা হয়। Fees, spread, slippage এবং execution delay হিসাবের বাইরে।
- API keys কখনো GitHub code-এ লিখবে না। Streamlit Secrets ব্যবহার করো।

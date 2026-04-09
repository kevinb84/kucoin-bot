# Quick Start Guide - 5-Minute Scalping Bot

Get your self-improving trading bot running in under 10 minutes!

## 🚀 Quick Setup (5 Steps)

### Step 1: Install Python Dependencies

```bash
pip install -r requirements.txt
```

This installs all necessary packages including:
- `ccxt` - Exchange API
- `scikit-learn` - Machine learning
- `pandas` & `numpy` - Data analysis
- `websocket-client` - Real-time data
- `sqlalchemy` - Database

### Step 2: Setup API Credentials

Create a `.env` file:

```bash
cp .env.example .env
```

Edit `.env` and add your KuCoin credentials:

```env
KUCOIN_API_KEY=your_key_here
KUCOIN_API_SECRET=your_secret_here
KUCOIN_API_PASSPHRASE=your_passphrase_here
KUCOIN_SANDBOX=true
```

**🔑 Get API Keys:**
1. Go to https://www.kucoin.com/account/api
2. Create new API key with "Futures" permissions
3. Enable IP whitelist (recommended)
4. Copy keys to `.env` file

⚠️ **IMPORTANT:** Keep `KUCOIN_SANDBOX=true` for testing with fake money!

### Step 3: Review Configuration

Open `config/config.yaml` and review settings:

```yaml
# For testing, use these conservative settings:
symbol: "BTC-USDT"
timeframe: "5m"
leverage: 5               # Lower leverage for safety
risk_per_trade: 1.0       # Risk only 1% per trade
max_position_size: 100    # Small position for testing
stop_loss_percent: 0.5
take_profit_percent: 1.0
```

### Step 4: Run the Bot

```bash
python main.py
```

You should see:
```
======================================================================
  KuCoin Self-Improving 5-Minute Scalping Trading Agent
  With ML Predictions & Adaptive Learning
======================================================================

✓ Config: config/config.yaml
✓ Symbol override: BTC-USDT
✓ Timeframe override: 5m

======================================================================
  Starting Trading Engine
======================================================================
  Symbol:        BTC-USDT
  Timeframe:     5m
  Check Interval: 30s
  Learning:      Enabled
  ML Predictions:Enabled
  WebSocket:     Enabled
======================================================================

Press Ctrl+C to stop
```

### Step 5: Monitor Performance

The bot will:
1. ✅ Connect to KuCoin (sandbox mode)
2. ✅ Fetch market data every 30 seconds
3. ✅ Analyze with technical indicators
4. ✅ Get ML predictions
5. ✅ Execute trades when signals are strong
6. ✅ Track all trades in database
7. ✅ Auto-optimize parameters every 100 trades

## 📊 Viewing Results

### Check Performance Report

```bash
python main.py --show-report
```

This shows:
- Total trades executed
- Win rate percentage
- Profit/loss statistics
- Sharpe ratio
- Daily performance

### View Trade Database

```bash
# Using SQLite command line
sqlite3 trading_journal.db

# See all trades
SELECT timestamp, side, entry_price, exit_price, pnl FROM trades ORDER BY timestamp DESC;

# See win rate
SELECT 
  COUNT(*) as total,
  SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
  ROUND(AVG(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) * 100, 2) as win_rate
FROM trades;
```

## 🎯 First 24 Hours Checklist

- [ ] Bot runs without errors for 1 hour
- [ ] WebSocket connects successfully
- [ ] Market data is being fetched
- [ ] ML model trains (after enough data)
- [ ] First trade executed
- [ ] Trade recorded in journal
- [ ] Performance report shows data
- [ ] No circuit breakers triggered
- [ ] Logs show normal activity

## 🔧 Common Issues & Fixes

### Issue: "ModuleNotFoundError: No module named 'sklearn'"

**Solution:**
```bash
pip install scikit-learn
```

### Issue: "WebSocket connection failed"

**Solution:**
- Normal - bot will fallback to REST API
- Check your internet connection
- KuCoin API might be temporarily down

### Issue: "Insufficient balance"

**Solution:**
- In sandbox mode, request test funds from KuCoin testnet faucet
- Or reduce `max_position_size` in config

### Issue: "Circuit breaker triggered"

**Solution:**
- Bot hit daily loss limit
- Review your risk parameters
- Reduce `risk_per_trade` and `max_position_size`

### Issue: "No trade signals generated"

**Solution:**
- Market might be ranging (no clear trend)
- Lower `min_signal_strength` in config (try 5)
- Wait for stronger market conditions

## 🎓 Understanding Bot Behavior

### What You'll See:

**"Signal: HOLD"**
- No strong trading opportunity
- Bot is waiting for better setup
- This is normal and good!

**"Signal: BUY/SELL [Strength: 7/10]"**
- Strong trading opportunity detected
- ML prediction confirms direction
- Bot will execute trade

**"Trailing stop updated"**
- Position is profitable
- Stop loss moved to lock in gains
- Risk management working

**"Parameter optimization complete"**
- Bot analyzed last 100 trades
- Adjusted parameters for better performance
- Self-improvement in action!

## 📈 Going Live (After Successful Testing)

Once you're profitable in sandbox:

1. **Change to Live Trading:**
   ```env
   KUCOIN_SANDBOX=false
   ```

2. **Start Small:**
   ```yaml
   risk_per_trade: 0.5    # Start with 0.5% risk
   max_position_size: 50  # Small positions
   ```

3. **Monitor Closely:**
   - Watch every trade initially
   - Verify execution matches expectations
   - Check slippage and fees

4. **Gradually Scale:**
   - Increase position sizes slowly
   - Add more trading pairs
   - Adjust risk as confidence grows

## ⚠️ Safety Rules

1. **NEVER** trade with money you can't afford to lose
2. **ALWAYS** test in sandbox first (minimum 1 week)
3. **MONITOR** the bot regularly
4. **REVIEW** performance reports daily
5. **ADJUST** parameters based on results
6. **ENABLE** circuit breakers (already default)

## 🆘 Need Help?

1. Check `README.md` for detailed documentation
2. Review `trading_bot.log` for error details
3. Look at recent trades in journal database
4. Open GitHub issue with logs (hide API keys!)

## 🎉 Success Indicators

You're on the right track when:

✅ Bot runs 24/7 without crashes  
✅ Win rate stabilizes around 50-60%  
✅ Profit factor stays above 1.5  
✅ Parameters auto-optimize successfully  
✅ ML model accuracy improves over time  
✅ Daily PnL shows consistent profits  

## 🚨 When to Stop

Stop trading and reassess if:

❌ Win rate drops below 40%  
❌ Multiple circuit breakers trigger  
❌ Unexpected errors in logs  
❌ Drawdown exceeds 15%  
❌ Bot behavior seems erratic  

---

**Remember:** The bot is designed to learn and improve. Give it time, monitor regularly, and let the self-learning system work!

Good luck! 🚀

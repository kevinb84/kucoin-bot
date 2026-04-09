# ⚠️ IMPORTANT SAFETY GUIDE - LIVE TRADING

## KuCoin Futures - No Testnet Available

**KuCoin does not provide a testnet for futures trading.** This bot connects directly to the LIVE KuCoin API and will execute REAL trades with REAL money.

## 🛡️ Safety Configuration Applied

Your bot is configured with **ULTRA-CONSERVATIVE** settings:

| Setting | Value | Purpose |
|---------|-------|---------|
| Max Position Size | $10 | Minimum risk per trade |
| Risk Per Trade | 0.5% | Only 0.5% of balance at risk |
| Leverage | 3x | Very low leverage |
| Daily Loss Limit | 2% | Stops trading after $2 loss per $100 |
| Max Drawdown | 5% | Emergency stop at 5% loss |
| Stop Loss | 0.3% | Very tight stops |
| ML Confidence | 70% | Only trades when very certain |
| Signal Strength | 7/10 | Only strong signals |

## 💰 Recommended Starting Balance

**Minimum: $100 USDT**
- With $100 and 0.5% risk = $0.50 risk per trade
- With $100 and 2% daily limit = $2 max loss per day
- This is SAFE for learning

**Ideal: $200-500 USDT**
- More breathing room for normal fluctuations
- Still very low absolute risk

## 🔐 API Key Safety

### Create a Restricted API Key:
1. Go to KuCoin → Account → API
2. Create NEW API key with these restrictions:
   - ✅ Enable "Futures" permission
   - ✅ Enable "Read" permission
   - ❌ DISABLE "Withdraw" permission (IMPORTANT!)
   - ❌ DISABLE "Transfer" permission
   - ✅ Set IP whitelist to your IP address

### API Key Permissions:
```
✅ Read spot & futures accounts
✅ Trade spot & futures
❌ Transfer
❌ Withdraw
```

## 📊 Before Going Live - Checklist

- [ ] Understand the bot is trading REAL money
- [ ] Start with minimum $100 balance
- [ ] API key has NO withdrawal permissions
- [ ] IP whitelist is enabled
- [ ] Read the SAFETY_GUIDE.md completely
- [ ] Test with $10 position sizes first
- [ ] Monitor every trade initially
- [ ] Set up price alerts on your phone

## 🚀 Safe Launch Procedure

### Day 1-2: Observation Mode
1. Start the bot: `python src/dashboard/app.py`
2. Watch the dashboard but DON'T add funds yet
3. See if signals are generated
4. Verify it's working correctly

### Day 3-4: Micro Trading
1. Add $50-100 to your KuCoin futures account
2. Set `max_position_size: 5` (even smaller)
3. Let it trade with $5 positions
4. Monitor every single trade
5. Check logs for errors

### Day 5-7: Normal Operation
1. If profitable with micro trades, increase to $10
2. Set `max_position_size: 10` in config
3. Continue monitoring closely
4. Review daily performance reports

### Week 2+: Scale Up (If Profitable)
1. Only increase position sizes if consistently profitable
2. Never risk more than 2% per trade
3. Keep daily loss limits enabled
4. Withdraw profits regularly

## 🚨 Emergency Procedures

### If Bot Goes Wrong:
1. **STOP THE BOT IMMEDIATELY:**
   ```
   Press Ctrl+C in the terminal
   ```

2. **Close All Positions Manually:**
   - Go to KuCoin website
   - Navigate to Futures → Positions
   - Close any open positions

3. **Revoke API Key:**
   - Go to KuCoin → Account → API
   - Delete the API key immediately

### Warning Signs to Stop:
- ❌ More than 3 losing trades in a row
- ❌ Daily loss approaching 2% limit
- ❌ Bot making unexpected trades
- ❌ Errors in the log file
- ❌ Unusual behavior on dashboard

## 📈 Realistic Expectations

### What to Expect:
- Win rate: 50-65% (no strategy wins 100%)
- Daily profit: 0.5-2% on good days
- Some days will be losing days
- Circuit breakers WILL trigger (that's good!)

### What NOT to Expect:
- ❌ Winning every trade
- ❌ Getting rich quick
- ❌ Profits every single day
- ❌ No losing streaks

## 💡 Pro Tips for Safety

1. **Start Small:** Begin with $50-100 only
2. **Monitor Daily:** Check performance every day
3. **Withdraw Profits:** Take out 50% of profits weekly
4. **Keep Logs:** Save all trade logs for analysis
5. **Update Regularly:** Keep the bot updated
6. **Never Compromise:** Don't increase risk too fast
7. **Have Stop-Loss:** Always use stop losses
8. **Diversify:** Don't put all funds in one bot

## ⚖️ Risk Disclosure

**Trading futures involves substantial risk:**
- You can lose MORE than your initial investment with leverage
- Past performance does not guarantee future results
- This is educational software - use at your own risk
- Never trade with money you can't afford to lose
- Cryptocurrency markets are extremely volatile

## 🆘 Support & Resources

- KuCoin Support: https://www.kucoin.com/support
- KuCoin API Docs: https://docs.kucoin.com/futures
- Bot Logs: Check `trading_bot.log` for details
- Dashboard: http://localhost:5000 for monitoring

## ✅ Final Safety Checklist

Before running the bot:

- [ ] I understand this trades REAL money
- [ ] I have $100+ in my KuCoin futures account
- [ ] My API key has NO withdrawal permissions
- [ ] IP whitelist is enabled
- [ ] I've read and understood this guide
- [ ] I'm prepared to lose the money I'm trading with
- [ ] I will monitor the bot regularly
- [ ] I know how to stop the bot (Ctrl+C)
- [ ] I have emergency procedures planned

---

**Remember: The goal is to LEARN and preserve capital, not get rich overnight.**

**Trade safely! 🛡️**

# KuCoin Self-Improving 5-Minute Scalping Trading Agent

A sophisticated cryptocurrency trading bot for KuCoin perpetual futures that combines **technical analysis**, **machine learning predictions**, and **adaptive self-learning** to execute profitable 5-minute scalping trades.

## 🚀 Key Features

### 📊 Advanced Trading Strategy
- **5-minute scalping** optimized EMA crossovers (9/21)
- **Multi-timeframe analysis** (5m, 15m, 1h) for better context
- **Dual strategy modes**: Trend following + Mean reversion
- **Volume confirmation** for higher accuracy
- **Market regime detection** (trending, ranging, volatile)
- **RSI + MACD + Bollinger Bands** for comprehensive analysis

### 🤖 Machine Learning Integration
- **Price direction prediction** using Random Forest / Gradient Boosting
- **Automatic feature engineering** from OHLCV data
- **Confidence-based filtering** - only trade when ML is certain
- **Model retraining** after N trades to adapt to market changes
- **Feature importance tracking** to understand what drives predictions

### 🧠 Self-Learning & Optimization
- **Trade journal** with SQLite database for persistent storage
- **Performance analytics**: Win rate, profit factor, Sharpe ratio, max drawdown
- **Automatic parameter optimization** using grid search
- **Adaptive parameter adjustment** based on performance metrics
- **Best parameters tracking** - learns from winning trades
- **Market condition recording** for regime-based optimization

### 🛡️ Advanced Risk Management
- **ATR-based position sizing** - adjusts to market volatility
- **Signal strength scaling** - stronger signals = larger positions
- **Trailing stop losses** - locks in profits as price moves
- **Daily loss circuit breaker** - stops trading after max daily loss
- **Maximum drawdown protection** - automatic halt on excessive losses
- **Dynamic leverage adjustment** based on account health
- **Real-time position monitoring** with PnL tracking

### ⚡ Real-Time Data
- **WebSocket integration** for instant market data
- **Automatic fallback** to REST polling if WebSocket fails
- **Low-latency execution** critical for scalping
- **Order book analysis** (bid/ask spread, depth)

### 📈 Performance Tracking
- **Comprehensive trade journal** with detailed metrics
- **Real-time performance reports** (hourly/daily)
- **Win/loss analysis** with consecutive stats
- **Expectancy calculation** - expected profit per trade
- **Risk-adjusted returns** (Sharpe ratio)

## 📁 Project Structure

```
kucoin/
├── main.py                          # Entry point with CLI
├── config/
│   └── config.yaml                  # Trading configuration
├── src/
│   ├── api/
│   │   ├── kucoin_client.py         # REST API wrapper (ccxt)
│   │   └── websocket_client.py      # Real-time WebSocket client
│   ├── strategy/
│   │   └── trend_following.py       # Enhanced scalping strategy
│   ├── risk/
│   │   ├── risk_manager.py          # Basic risk management
│   │   └── advanced_risk_manager.py # Advanced risk with trailing stops
│   ├── engine/
│   │   └── trading_engine.py        # Core orchestration engine
│   ├── learning/
│   │   ├── trade_journal.py         # Trade database & journaling
│   │   ├── performance_analyzer.py  # Performance metrics
│   │   └── parameter_optimizer.py   # Auto-tuning parameters
│   ├── ml/
│   │   └── price_predictor.py       # ML price prediction model
│   └── utils/
│       └── logger.py                # Logging utility
├── requirements.txt                 # Python dependencies
├── .env                            # API credentials (not in git)
├── .env.example                    # Template for .env
└── trading_journal.db              # SQLite database (auto-created)
```

## 🛠️ Installation

### Prerequisites
- Python 3.9 or higher
- KuCoin account (use sandbox/testnet for testing)
- Basic understanding of trading concepts

### Step 1: Clone Repository
```bash
git clone <repository-url>
cd kucoin
```

### Step 2: Install Dependencies
```bash
pip install -r requirements.txt
```

This installs:
- `ccxt` - Exchange API library
- `scikit-learn` - Machine learning models
- `pandas` & `numpy` - Data manipulation
- `optuna` - Hyperparameter optimization
- `sqlalchemy` - Database integration
- `websocket-client` - Real-time data
- `ta` - Technical analysis indicators

### Step 3: Configure API Credentials

1. Copy the example environment file:
```bash
cp .env.example .env
```

2. Edit `.env` and add your KuCoin API credentials:
```env
KUCOIN_API_KEY=your_api_key_here
KUCOIN_API_SECRET=your_api_secret_here
KUCOIN_API_PASSPHRASE=your_api_passphrase_here
KUCOIN_SANDBOX=true  # Use true for testnet, false for live trading
```

**⚠️ IMPORTANT:** Never commit your `.env` file to version control!

### Step 4: Configure Trading Parameters

Edit `config/config.yaml` to customize:

```yaml
# Trading
symbol: "BTC-USDT"        # Trading pair
timeframe: "5m"           # Candle timeframe
check_interval: 30        # Seconds between checks
leverage: 10              # Futures leverage

# Risk Management
stop_loss_percent: 0.5    # Tight stops for scalping
take_profit_percent: 1.0  # Quick profit targets
trailing_stop: true       # Enable trailing stops
max_daily_loss: 5.0       # Circuit breaker (%)

# Strategy
ema_fast: 9               # Fast EMA for scalping
ema_slow: 21              # Slow EMA for scalping
rsi_overbought: 65        # Lower for quicker exits
rsi_oversold: 35          # Higher for quicker entries

# Self-Learning
learning_enabled: true
optimization_interval: 100  # Optimize every N trades
ml_enabled: true
ml_confidence_threshold: 0.6
```

## 🚀 Usage

### Start Trading
```bash
python main.py
```

### Command-Line Options
```bash
# Use custom config
python main.py --config my_config.yaml

# Trade different symbol
python main.py --symbol ETH-USDT

# Change timeframe
python main.py --timeframe 3m

# Paper trading (sandbox)
python main.py --paper

# View performance report
python main.py --show-report

# Custom check interval
python main.py --interval 60
```

### Stop Trading
Press `Ctrl+C` for graceful shutdown. The bot will:
- Close any open WebSocket connections
- Save final performance report
- Log all shutdown activities

## 📊 Understanding the Strategy

### Entry Signals

The bot generates trading signals based on:

1. **EMA Crossover** (9/21 for scalping)
   - Bullish crossover → Buy signal
   - Bearish crossover → Sell signal
   - Pullback entries in strong trends

2. **RSI Extremes**
   - RSI < 35 + price below BB lower → Buy
   - RSI > 65 + price above BB upper → Sell

3. **MACD Confirmation**
   - Histogram increasing → Confirms direction
   - Histogram decreasing → Weakens signal

4. **Volume Confirmation**
   - Volume must be 1.5x average for confirmation
   - Filters out weak signals

5. **Multi-Timeframe Analysis**
   - 15m and 1h trends checked for alignment
   - Higher timeframe agreement boosts strength

6. **ML Prediction**
   - Random Forest model predicts next candle direction
   - Confidence threshold filters low-certainty trades
   - Feature importance reveals key predictors

### Exit Strategies

Positions are closed when:

1. **Stop Loss Hit** - Fixed % or ATR-based
2. **Take Profit Hit** - Quick targets for scalping
3. **Trailing Stop** - Locks in profits
4. **Opposite Signal** - Strategy reversal with high strength
5. **Time-Based Exit** - Maximum hold time (optional)

### Self-Improvement Loop

Every N trades (default 100):

1. **Analyze Performance**
   - Calculate win rate, profit factor, Sharpe ratio
   - Identify winning and losing trade patterns

2. **Parameter Optimization**
   - Grid search over EMA periods, RSI settings
   - Score combinations based on historical performance
   - Recommend optimal parameters

3. **Adaptive Adjustment**
   - Blend new recommendations with current params (70/30)
   - Avoid drastic changes that could hurt performance
   - Save best parameters to database

4. **Model Retraining**
   - Retrain ML model with new trade data
   - Update feature importance rankings
   - Improve prediction accuracy over time

## 🔧 Configuration Guide

### Risk Management Settings

```yaml
# Conservative (Lower Risk)
risk_per_trade: 1.0          # 1% risk per trade
max_position_size: 500       # Smaller positions
stop_loss_percent: 0.3       # Tighter stops
max_daily_loss: 3.0          # Stop after 3% daily loss
max_drawdown: 5.0            # Halt at 5% drawdown

# Moderate (Balanced)
risk_per_trade: 2.0
max_position_size: 1000
stop_loss_percent: 0.5
max_daily_loss: 5.0
max_drawdown: 10.0

# Aggressive (Higher Risk/Reward)
risk_per_trade: 3.0
max_position_size: 2000
stop_loss_percent: 0.8
max_daily_loss: 8.0
max_drawdown: 15.0
```

### Scalping vs Swing Trading

```yaml
# 5-Minute Scalping
timeframe: "5m"
check_interval: 30
ema_fast: 9
ema_slow: 21
stop_loss_percent: 0.5
take_profit_percent: 1.0
trailing_stop_distance: 0.3

# 1-Hour Swing Trading
timeframe: "1h"
check_interval: 300
ema_fast: 12
ema_slow: 26
stop_loss_percent: 2.0
take_profit_percent: 5.0
trailing_stop_distance: 1.0
```

### ML Model Selection

```yaml
# Random Forest (Recommended)
ml_model_type: "random_forest"
# - Good accuracy, fast training
# - Handles non-linear patterns
# - Provides feature importance

# Gradient Boosting
ml_model_type: "gradient_boosting"
# - Higher accuracy potential
# - Slower training
# - More prone to overfitting

# Logistic Regression
ml_model_type: "logistic_regression"
# - Fastest, simplest
# - Linear relationships only
# - Good baseline model
```

## 📈 Performance Metrics

The bot tracks comprehensive metrics:

### Trade Statistics
- **Total Trades**: Number of completed trades
- **Win Rate**: Percentage of winning trades
- **Average Win/Loss**: Mean profit/loss per trade
- **Profit Factor**: Gross profit / Gross loss (target > 1.5)
- **Expectancy**: Expected profit per trade

### Risk Metrics
- **Max Drawdown**: Largest peak-to-trough decline
- **Sharpe Ratio**: Risk-adjusted return (target > 1.0)
- **Consecutive Wins/Losses**: Streak analysis
- **Daily PnL**: Profit/loss per trading day

### ML Metrics
- **Prediction Accuracy**: ML model accuracy
- **Feature Importance**: Which indicators matter most
- **Confidence Distribution**: How certain the model is
- **Retraining Frequency**: How often model updates

## 🧪 Testing & Backtesting

### Paper Trading (Recommended First)
```bash
# Use KuCoin sandbox (testnet)
python main.py --paper
```

This uses fake money on real market data - perfect for testing!

### View Historical Performance
```bash
# Show all-time performance report
python main.py --show-report

# Check trade journal database
sqlite3 trading_journal.db
SELECT * FROM trades ORDER BY timestamp DESC LIMIT 10;
```

## 🔍 Monitoring & Debugging

### Log Files
All activity is logged to:
- `trading_bot.log` - Detailed log file
- Console output - Real-time messages

### Log Levels
```yaml
# In config.yaml
log_level: "DEBUG"   # Verbose (all details)
log_level: "INFO"    # Normal (recommended)
log_level: "WARNING" # Only warnings/errors
```

### Common Issues

**"Insufficient data for training"**
- Bot needs at least 100 candles before ML model trains
- Wait for more data or reduce `ml_feature_count`

**"WebSocket connection failed"**
- Normal fallback to REST polling
- Check internet connection
- KuCoin API may be temporarily down

**"Circuit breaker triggered"**
- Daily loss limit reached
- Bot will stop trading automatically
- Review risk parameters and reduce position sizes

## 🎯 Tips for Success

### 1. Start Conservative
- Begin with paper trading
- Use small position sizes
- Increase gradually as confidence grows

### 2. Monitor Performance
- Check reports daily
- Adjust parameters if win rate < 45%
- Let the bot optimize automatically

### 3. Choose Right Market Conditions
- Bot performs best in trending markets
- Avoid high-impact news events
- 5-minute timeframe works 24/7 but best during high volume

### 4. Risk Management is Key
- Never risk more than 2% per trade
- Always use stop losses
- Enable circuit breakers

### 5. Let It Learn
- Don't manually override parameters too often
- Allow optimization to run every 100 trades
- Review recommended changes before applying

## ⚠️ Risk Disclaimer

**Trading cryptocurrencies involves substantial risk of loss. This software is provided "as is" without warranty. Past performance does not guarantee future results. Only trade with capital you can afford to lose.**

- Test thoroughly in sandbox mode first
- Start with small position sizes
- Monitor the bot regularly
- Be prepared for losing trades
- No strategy wins 100% of the time

## 🤝 Contributing

Contributions welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## 📝 License

MIT License - See LICENSE file for details

## 🆘 Support

For issues and questions:
1. Check the documentation above
2. Review log files for errors
3. Open an issue on GitHub
4. Include relevant log excerpts (hide API keys!)

## 🗺️ Roadmap

Future enhancements:
- [ ] Backtesting engine with historical data
- [ ] Web dashboard for real-time monitoring
- [ ] Telegram/Discord notifications
- [ ] Multiple symbol support (portfolio mode)
- [ ] Sentiment analysis integration (Twitter, news)
- [ ] Advanced ML models (LSTM, Transformer)
- [ ] Strategy marketplace (community strategies)
- [ ] Mobile app for monitoring

---

**Happy Trading! 🚀📈**

*Remember: The goal is consistent profitability over time, not winning every single trade.*

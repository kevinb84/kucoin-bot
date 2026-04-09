"""
KuCoin Trading Bot - Integrated Dashboard + Trading Engine
One process: Dashboard shows charts AND bot actually trades.
"""

from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit
import threading
import time
import yaml
import pandas as pd
from datetime import datetime
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.api.kucoin_client import KuCoinClient
from src.strategy.trend_following import TrendFollowingStrategy
from src.risk.advanced_risk_manager import AdvancedRiskManager
from src.learning.trade_journal import TradeJournal
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ── Flask setup ──────────────────────────────────────────────
app = Flask(__name__)
app.config['SECRET_KEY'] = 'kucoin-bot-2026'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# ── Load config ───────────────────────────────────────────────
CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'config', 'config.yaml')
with open(CONFIG_PATH, 'r') as f:
    CONFIG = yaml.safe_load(f)

SYMBOL   = CONFIG.get('symbol', 'XBTUSDTM')
TF       = CONFIG.get('timeframe', '5m')
INTERVAL = CONFIG.get('check_interval', 10)

# ── Shared state (dashboard reads this) ───────────────────────
state = {
    'is_running':      False,
    'ticker':          {},
    'candles':         [],
    'position':        None,
    'last_signal':     {'signal': 'none', 'strength': 0, 'reason': ''},
    'performance':     {},
    'recent_trades':   [],
    'log_feed':        [],          # last 50 log lines shown in UI
    'cycle':           0,
    'last_update':     '',
}

# ── Components ────────────────────────────────────────────────
client   = KuCoinClient()
journal  = TradeJournal(db_path=CONFIG.get('journal_db_path', 'trading_journal.db'))
strategy = TrendFollowingStrategy(CONFIG)
risk_mgr = AdvancedRiskManager(CONFIG)

# ── Thread handles ────────────────────────────────────────────
bot_thread    = None
market_thread = None

# ─────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────

def push_log(msg: str):
    """Append a message to the live log feed and broadcast."""
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    state['log_feed'].append(line)
    if len(state['log_feed']) > 50:
        state['log_feed'] = state['log_feed'][-50:]
    socketio.emit('log', {'line': line})
    logger.info(msg)


def fetch_candles():
    """Fetch OHLCV and return list-of-dicts for the UI."""
    df = client.fetch_ohlcv(SYMBOL, TF, limit=100)
    if df is None or df.empty:
        return []
    rows = []
    for _, r in df.iterrows():
        ts = r['timestamp']
        if isinstance(ts, pd.Timestamp):
            ts = int(ts.timestamp() * 1000)
        else:
            ts = int(ts)
        rows.append({
            'time':   ts,
            'open':   float(r['open']),
            'high':   float(r['high']),
            'low':    float(r['low']),
            'close':  float(r['close']),
            'volume': float(r['volume']),
        })
    return rows


def update_performance():
    stats = journal.get_trade_statistics(SYMBOL)
    state['performance']   = stats
    state['recent_trades'] = journal.get_recent_trades(SYMBOL, limit=20)


# ─────────────────────────────────────────────────────────────
#  MARKET DATA THREAD  (always runs, updates chart every 5 s)
# ─────────────────────────────────────────────────────────────

def market_loop():
    while True:
        try:
            # candles
            candles = fetch_candles()
            if candles:
                state['candles'] = candles

            # ticker
            ticker = client.fetch_ticker(SYMBOL)
            if ticker:
                state['ticker'] = {
                    'price':  ticker.get('last', 0),
                    'change': ticker.get('percentage', 0),
                    'high':   ticker.get('high', 0),
                    'low':    ticker.get('low', 0),
                    'volume': ticker.get('baseVolume', 0),
                }

            # position
            pos = client.fetch_position(SYMBOL)
            if pos and pos.get('contracts', 0) != 0:
                state['position'] = {
                    'side':           'long' if float(pos.get('contracts', 0)) > 0 else 'short',
                    'size':           pos.get('contracts', 0),
                    'entry_price':    pos.get('entryPrice', 0),
                    'mark_price':     pos.get('markPrice', 0),
                    'unrealized_pnl': pos.get('unrealizedPnl', 0),
                    'leverage':       pos.get('leverage', 10),
                }
            else:
                state['position'] = None

            state['last_update'] = datetime.now().strftime('%H:%M:%S')
            update_performance()

            socketio.emit('state', state)

        except Exception as e:
            logger.error(f"Market loop error: {e}")

        time.sleep(5)


# ─────────────────────────────────────────────────────────────
#  TRADING ENGINE THREAD  (runs only when bot is started)
# ─────────────────────────────────────────────────────────────

def trading_loop():
    """Core trading loop - generates signals and executes orders."""
    push_log(f"🟢 Trading engine started | {SYMBOL} | {TF} | 10x leverage")
    push_log(f"💰 Check interval: {INTERVAL}s | Min signal: {CONFIG.get('min_signal_strength',4)}/10")

    while state['is_running']:
        try:
            state['cycle'] += 1
            cycle = state['cycle']

            # ── 1. Fetch data ──────────────────────────────────
            df = client.fetch_ohlcv(SYMBOL, TF, limit=100)
            if df is None or df.empty:
                push_log("⚠️  No market data, retrying...")
                time.sleep(INTERVAL)
                continue

            # ── 2. Analyse market ──────────────────────────────
            signal = strategy.analyze(df)
            sig    = signal.get('signal', 'hold')
            str_   = signal.get('strength', 0)
            reason = signal.get('reason', '')

            state['last_signal'] = signal
            push_log(f"📊 Cycle {cycle} | Signal: {sig.upper()} ({str_}/10) | {reason}")

            # ── 3. Check if already in position ───────────────
            pos = client.fetch_position(SYMBOL)
            in_position = pos and float(pos.get('contracts', 0)) != 0

            # ── 4. Monitor existing position ──────────────────
            if in_position:
                ticker = client.fetch_ticker(SYMBOL)
                if ticker:
                    price = float(ticker.get('last', 0))
                    risk_mgr.update_position_tracking(price)
                    risk_mgr.update_trailing_stop(price, risk_mgr.open_position['side'] if risk_mgr.open_position else 'buy')

                    if risk_mgr.check_stop_loss_triggered(price):
                        push_log(f"🛑 STOP LOSS hit @ {price:.2f}")
                        _close_trade(price, 'stop_loss')
                        in_position = False

                    elif risk_mgr.check_take_profit_triggered(price):
                        push_log(f"✅ TAKE PROFIT hit @ {price:.2f}")
                        _close_trade(price, 'take_profit')
                        in_position = False

            # ── 5. Enter new trade ─────────────────────────────
            if not in_position and sig in ('buy', 'sell'):
                min_strength = CONFIG.get('min_signal_strength', 4)
                if str_ >= min_strength:
                    _execute_trade(sig, str_, df)
                else:
                    push_log(f"⏭️  Signal too weak ({str_} < {min_strength}), skip")

        except Exception as e:
            push_log(f"❌ Trading loop error: {e}")
            logger.error(f"Trading loop error: {e}", exc_info=True)

        time.sleep(INTERVAL)

    push_log("🔴 Trading engine stopped")


def _execute_trade(side: str, strength: int, df: pd.DataFrame):
    """Execute a market order and record it."""
    try:
        ticker = client.fetch_ticker(SYMBOL)
        if not ticker:
            push_log("❌ Cannot fetch ticker")
            return

        price = float(ticker.get('last', 0))
        if price <= 0:
            push_log("❌ Invalid price from ticker")
            return

        # Balance check
        bal = client.fetch_balance()
        if not bal:
            push_log("❌ Cannot fetch balance")
            return

        usdt = float(bal.get('USDT', {}).get('free', 0) or 0)
        push_log(f"💳 Available balance: ${usdt:.2f} USDT")

        if usdt < 5:
            push_log(f"⚠️  Insufficient balance (${usdt:.2f} < $5 USDT) — add funds to KuCoin Futures account")
            return

        # XBTUSDTM: 1 contract = 0.001 BTC
        # With 10x leverage, $10 margin controls $100 worth = ~1 contract at $83,000
        leverage   = CONFIG.get('leverage', 10)
        risk_pct   = CONFIG.get('risk_per_trade', 1.5) / 100
        margin_usd = usdt * risk_pct                          # e.g. $50 * 1.5% = $0.75
        margin_usd = max(margin_usd, 1.0)                    # minimum $1 margin
        position_usd = margin_usd * leverage                 # e.g. $0.75 * 10 = $7.50
        contracts  = max(1, int(position_usd / (price * 0.001)))  # 0.001 BTC per contract

        # SL / TP prices
        sl_pct = CONFIG.get('stop_loss_percent', 0.3) / 100
        tp_pct = CONFIG.get('take_profit_percent', 0.5) / 100
        if side == 'buy':
            sl = round(price * (1 - sl_pct), 2)
            tp = round(price * (1 + tp_pct), 2)
        else:
            sl = round(price * (1 + sl_pct), 2)
            tp = round(price * (1 - tp_pct), 2)

        push_log(f"🚀 {side.upper()} {contracts} contracts @ ${price:,.2f} | Margin:${margin_usd:.2f} | SL:{sl:,.2f} TP:{tp:,.2f}")

        order = client.create_order(
            symbol=SYMBOL,
            order_type='market',
            side=side,
            amount=contracts
        )

        if order:
            oid = order.get('id', 'N/A')
            push_log(f"✅ Order filled! ID: {oid}")

            risk_mgr.open_trade({
                'symbol':          SYMBOL,
                'side':            side,
                'entry_price':     price,
                'quantity':        contracts,
                'leverage':        leverage,
                'stop_loss':       sl,
                'take_profit':     tp,
                'signal_strength': strength,
            })
        else:
            push_log(f"❌ Order failed — check terminal window for exact error from KuCoin API")
            push_log(f"   Hint: Ensure API key has FUTURES TRADING permission on KuCoin")

    except Exception as e:
        push_log(f"❌ Execute trade error: {e}")
        logger.error(f"Execute trade error: {e}", exc_info=True)


def _close_trade(exit_price: float, reason: str):
    """Close current position."""
    try:
        if not risk_mgr.open_position:
            return

        side  = risk_mgr.open_position['side']
        qty   = abs(risk_mgr.open_position['quantity'])
        close_side = 'sell' if side == 'buy' else 'buy'

        order = client.create_order(
            symbol=SYMBOL,
            order_type='market',
            side=close_side,
            amount=qty,
            params={'reduceOnly': True}   # ADD THIS
        )
        if order:
            result = risk_mgr.close_trade(exit_price, reason)
            if result:
                journal.record_trade(result)
                pnl = result.get('pnl', 0)
                emoji = 'WIN' if pnl >= 0 else 'LOSS'
                push_log(f"[{emoji}] Trade closed | {reason} | PnL: ${pnl:.4f}")
        else:
            push_log("CLOSE FAILED - position may still be open!")

    except Exception as e:
        push_log(f"Close trade error: {e}")
        logger.error(f"Close trade error: {e}", exc_info=True)


# ─────────────────────────────────────────────────────────────
#  FLASK ROUTES
# ─────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('dashboard.html')

@app.route('/api/state')
def api_state():
    return jsonify(state)

@app.route('/api/trades')
def api_trades():
    return jsonify(journal.get_recent_trades(SYMBOL, limit=50))

@app.route('/api/performance')
def api_performance():
    return jsonify(journal.get_trade_statistics(SYMBOL))


# ─────────────────────────────────────────────────────────────
#  WEBSOCKET EVENTS
# ─────────────────────────────────────────────────────────────

@socketio.on('connect')
def on_connect():
    emit('state', state)
    for line in state['log_feed']:
        emit('log', {'line': line})

@socketio.on('start_bot')
def on_start():
    global bot_thread
    if state['is_running']:
        emit('log', {'line': '⚠️  Bot already running'})
        return
    state['is_running'] = True
    bot_thread = threading.Thread(target=trading_loop, daemon=True)
    bot_thread.start()
    emit('state', state)

@socketio.on('stop_bot')
def on_stop():
    state['is_running'] = False
    push_log("🔴 Stop signal sent...")
    emit('state', state)


# ─────────────────────────────────────────────────────────────
#  STARTUP
# ─────────────────────────────────────────────────────────────

def start():
    global market_thread
    # Railway assigns PORT dynamically via env var
    port = int(os.environ.get('PORT', 5000))
    
    # Always run market data thread
    market_thread = threading.Thread(target=market_loop, daemon=True)
    market_thread.start()
    
    logger.info(f"Dashboard starting on port {port} -> http://localhost:{port}")
    
    # Use eventlet for production (required by Railway)
    socketio.run(
        app,
        host='0.0.0.0',
        port=port,
        debug=False,
        allow_unsafe_werkzeug=True
    )


if __name__ == '__main__':
    start()

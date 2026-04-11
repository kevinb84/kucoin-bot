"""
KuCoin Smart Scanner Bot
Scans 20 KuCoin Futures pairs every cycle.
Only trades when confidence >= 7/10.
5-minute chart. One open position at a time.
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
from src.strategy.market_scanner import MarketScanner, CONTRACT_SIZE
from src.risk.advanced_risk_manager import AdvancedRiskManager
from src.learning.trade_journal import TradeJournal
from src.learning.compounding_engine import CompoundingEngine
from src.strategy.market_intelligence import MarketIntelligence
from src.utils.logger import get_logger

logger = get_logger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'kucoin-bot-2026'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# ── Load config ───────────────────────────────────────────────
CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'config', 'config.yaml'
)
with open(CONFIG_PATH, 'r') as f:
    CONFIG = yaml.safe_load(f)

TF             = CONFIG.get('timeframe', '5m')
INTERVAL       = CONFIG.get('check_interval', 15)
MIN_SCORE      = CONFIG.get('scanner_min_score', 7)

# ── Shared state ──────────────────────────────────────────────
state = {
    'is_running':      False,
    'ticker':          {},
    'candles':         [],
    'position':        None,
    'last_signal':     {'signal': 'none', 'strength': 0, 'reason': ''},
    'performance':     {},
    'recent_trades':   [],
    'log_feed':        [],
    'cycle':           0,
    'last_update':     '',
    'active_pair':     'Scanning...',
    'compounding':     {},
    'scanner_results': [],   # Latest scan scores for all pairs
    'trade_open_time': None,
    'current_symbol':  None, # Symbol of current open trade
}

# ── Components ────────────────────────────────────────────────
client     = KuCoinClient()
journal    = TradeJournal(db_path=CONFIG.get('journal_db_path', 'trading_journal.db'))
strategy   = TrendFollowingStrategy(CONFIG)
risk_mgr   = AdvancedRiskManager(CONFIG)
risk_mgr.trade_history = []
risk_mgr.daily_pnl     = 0.0
intel      = MarketIntelligence(client)
compounder = CompoundingEngine(starting_balance=45.0, risk_pct=20.0)
scanner    = MarketScanner(client, strategy, intel, timeframe=TF)

bot_thread    = None
market_thread = None

# ─────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────

def push_log(msg: str):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    state['log_feed'].append(line)
    if len(state['log_feed']) > 150:
        state['log_feed'] = state['log_feed'][-150:]
    socketio.emit('log', {'line': line})
    logger.info(msg)


def df_to_candles(df):
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


def get_contracts(symbol: str, margin_usd: float, leverage: int, price: float) -> int:
    contract_size = CONTRACT_SIZE.get(symbol, 0.001)
    position_usd  = margin_usd * leverage
    contracts     = position_usd / (price * contract_size)
    return max(1, int(contracts))


def update_performance():
    # Collect recent trades from journal (all pairs)
    all_trades = journal.get_recent_trades(limit=20)
    state['recent_trades'] = all_trades
    state['performance']   = journal.get_trade_statistics()
    state['compounding']   = compounder.get_stats()
    state['scanner_results'] = scanner.get_watchlist_status()
    state['intelligence']  = {
        'flash_crash_cooldown': intel.flash_crash_cooldown,
        'consecutive_losses':  intel.consecutive_losses,
        'session':             intel.get_session_info().get('session', 'unknown'),
    }


# ─────────────────────────────────────────────────────────────
#  MARKET DATA THREAD (charts + positions)
# ─────────────────────────────────────────────────────────────

def market_loop():
    logger.info("Market data loop started")
    while True:
        try:
            # Show chart for active symbol (or BTC if none)
            active = state.get('current_symbol') or 'XBTUSDTM'
            df = client.fetch_ohlcv(active, TF, limit=100)
            if df is not None and not df.empty:
                state['candles'] = df_to_candles(df)

            ticker = client.fetch_ticker(active)
            if ticker:
                state['ticker'] = {
                    'symbol': active,
                    'price':  ticker.get('last', 0),
                    'change': ticker.get('percentage', 0),
                    'high':   ticker.get('high', 0),
                    'low':    ticker.get('low', 0),
                    'volume': ticker.get('baseVolume', 0),
                }

            # Check open position
            if state.get('current_symbol'):
                pos = client.fetch_position(state['current_symbol'])
                if pos and float(pos.get('contracts', 0) or 0) != 0:
                    state['position'] = {
                        'symbol':         state['current_symbol'],
                        'side':           'long' if float(pos.get('contracts', 0)) > 0 else 'short',
                        'size':           pos.get('contracts', 0),
                        'entry_price':    pos.get('entryPrice', 0),
                        'mark_price':     pos.get('markPrice', 0),
                        'unrealized_pnl': pos.get('unrealizedPnl', 0),
                        'leverage':       pos.get('leverage', 10),
                    }
                else:
                    state['position'] = None
            else:
                state['position'] = None

            state['last_update'] = datetime.now().strftime('%H:%M:%S')
            update_performance()
            socketio.emit('state', state)

        except Exception as e:
            logger.error(f"Market loop error: {e}")

        time.sleep(5)


# ─────────────────────────────────────────────────────────────
#  TRADING ENGINE - SCANNER DRIVEN
# ─────────────────────────────────────────────────────────────

def trading_loop():
    from src.strategy.market_scanner import WATCHLIST as SCANNER_WATCHLIST
    push_log(f"Scanner Bot started | TF:{TF} | Min score:{MIN_SCORE}/10 | Scanning {len(SCANNER_WATCHLIST)} pairs")
    push_log("Will scan all pairs and only trade when confidence >= 7/10")

    while state['is_running']:
        try:
            state['cycle'] += 1
            cycle = state['cycle']

            # ── MANAGE EXISTING POSITION ────────────────────
            current_sym = state.get('current_symbol')
            if current_sym and risk_mgr.open_position:
                ticker = client.fetch_ticker(current_sym)
                if ticker:
                    price = float(ticker.get('last', 0))
                    risk_mgr.update_position_tracking(price)
                    risk_mgr.update_trailing_stop(price, risk_mgr.open_position.get('side', 'buy'))

                    if risk_mgr.check_stop_loss_triggered(price):
                        push_log(f"[{current_sym}] STOP LOSS @ {price:.6f}")
                        _close_trade(price, 'stop_loss', current_sym)

                    elif risk_mgr.check_take_profit_triggered(price):
                        push_log(f"[{current_sym}] TAKE PROFIT @ {price:.6f}")
                        _close_trade(price, 'take_profit', current_sym)

                    elif state.get('trade_open_time'):
                        hold_secs = time.time() - state['trade_open_time']
                        max_hold  = CONFIG.get('max_hold_time_minutes', 15) * 60
                        if hold_secs >= max_hold:
                            push_log(f"[{current_sym}] MAX HOLD ({hold_secs/60:.1f}min) - closing")
                            _close_trade(price, 'max_hold_time', current_sym)

                    else:
                        push_log(f"[{current_sym}] IN POSITION @ {price:.6f} | PnL: {risk_mgr.open_position.get('unrealized_pnl', 0):.4f}")

                time.sleep(INTERVAL)
                continue

            # ── SCAN MARKET FOR BEST OPPORTUNITY ────────────
            push_log(f"[#{cycle}] Scanning 20 pairs for opportunities...")
            state['active_pair'] = 'Scanning...'

            best = scanner.get_best_opportunity(exclude_symbols=[current_sym] if current_sym else [])

            if best and best.get('tradeable'):
                symbol = best['symbol']
                side   = best['side']
                score  = best['score']
                reason = best.get('reason', '')[:100]

                push_log(f"[#{cycle}] BEST: {symbol} {side.upper()} score={score}/10")
                push_log(f"  Reason: {reason}")
                state['active_pair']  = symbol
                state['last_signal']  = best.get('signal', {})

                _execute_trade(side, score, symbol)

            else:
                push_log(f"[#{cycle}] No high-confidence setup found. Waiting...")
                state['active_pair'] = 'Waiting for setup...'

        except Exception as e:
            push_log(f"Loop error: {str(e)[:80]}")
            logger.error(f"Trading loop error: {e}", exc_info=True)

        time.sleep(INTERVAL)

    push_log("Trading engine stopped")


def _execute_trade(side: str, strength: int, symbol: str):
    try:
        ticker = client.fetch_ticker(symbol)
        if not ticker:
            push_log(f"[{symbol}] Cannot get ticker")
            return
        price = float(ticker.get('last', 0))
        if price <= 0:
            push_log(f"[{symbol}] Bad price")
            return

        bal = client.fetch_balance()
        if not bal:
            push_log(f"[{symbol}] Cannot get balance")
            return
        usdt = float(bal.get('USDT', {}).get('free', 0) or 0)
        push_log(f"[{symbol}] Balance: ${usdt:.2f}")
        if usdt < 5:
            push_log(f"[{symbol}] Balance too low (${usdt:.2f})")
            return

        leverage = CONFIG.get('leverage', 10)
        compounder.update_balance(usdt)
        margin_usd = max(compounder.get_position_size_usd(), 1.0)

        # Apply loss limiter
        loss_check = intel.check_loss_limit()
        if loss_check['position_multiplier'] < 1.0:
            margin_usd = margin_usd * loss_check['position_multiplier']
            push_log(f"[{symbol}] Size reduced: {loss_check['reason']}")

        # Cap margin at available balance
        margin_usd = min(margin_usd, usdt * 0.5)

        contracts = get_contracts(symbol, margin_usd, leverage, price)

        sl_pct = CONFIG.get('stop_loss_percent', 0.3) / 100
        tp_pct = CONFIG.get('take_profit_percent', 0.5) / 100
        sl = round(price * (1 - sl_pct if side == 'buy' else 1 + sl_pct), 8)
        tp = round(price * (1 + tp_pct if side == 'buy' else 1 - tp_pct), 8)

        push_log(f"[{symbol}] {side.upper()} {contracts} contracts @ {price:.6f} | margin=${margin_usd:.2f} | SL:{sl:.6f} TP:{tp:.6f}")

        order = client.create_order(symbol=symbol, order_type='market', side=side, amount=contracts)
        if order:
            push_log(f"[{symbol}] ORDER FILLED! ID:{order.get('id','?')}")
            risk_mgr.open_trade({
                'symbol': symbol, 'side': side, 'entry_price': price,
                'quantity': contracts, 'leverage': leverage,
                'stop_loss': sl, 'take_profit': tp, 'signal_strength': strength,
            })
            state['trade_open_time'] = time.time()
            state['current_symbol']  = symbol
        else:
            push_log(f"[{symbol}] Order FAILED")

    except Exception as e:
        push_log(f"[{symbol}] Execute error: {str(e)[:100]}")
        logger.error(f"Execute trade error: {e}", exc_info=True)


def _close_trade(exit_price: float, reason: str, symbol: str):
    try:
        if not risk_mgr.open_position:
            return
        side       = risk_mgr.open_position['side']
        qty        = abs(risk_mgr.open_position['quantity'])
        close_side = 'sell' if side == 'buy' else 'buy'

        order = client.create_order(
            symbol=symbol, order_type='market',
            side=close_side, amount=qty,
            params={'reduceOnly': True}
        )
        if order:
            result = risk_mgr.close_trade(exit_price, reason)
            if result:
                journal.record_trade(result)
                pnl = result.get('pnl', 0)
                compounder.record_trade(pnl, side, symbol)
                intel.record_trade_result(won=(pnl >= 0))
                tag = 'WIN ✓' if pnl >= 0 else 'LOSS ✗'
                push_log(f"[{symbol}] [{tag}] {reason} | PnL: ${pnl:.4f}")
        else:
            push_log(f"[{symbol}] CLOSE FAILED!")

        state['trade_open_time'] = None
        state['current_symbol']  = None

    except Exception as e:
        push_log(f"[{symbol}] Close error: {str(e)[:100]}")
        logger.error(f"Close trade error: {e}", exc_info=True)


# ─────────────────────────────────────────────────────────────
#  FLASK ROUTES + WEBSOCKET
# ─────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('dashboard.html')

@app.route('/api/state')
def api_state():
    return jsonify(state)

@app.route('/api/trades')
def api_trades():
    return jsonify(journal.get_recent_trades(limit=50))

@app.route('/api/performance')
def api_performance():
    return jsonify(journal.get_trade_statistics())

@app.route('/api/scanner')
def api_scanner():
    return jsonify(scanner.get_watchlist_status())

@socketio.on('connect')
def on_connect():
    emit('state', state)
    for line in state['log_feed']:
        emit('log', {'line': line})

@socketio.on('start_bot')
def on_start():
    global bot_thread
    if state['is_running']:
        emit('log', {'line': 'Bot already running'})
        return
    state['is_running'] = True
    bot_thread = threading.Thread(target=trading_loop, daemon=True)
    bot_thread.start()
    emit('state', state)

@socketio.on('stop_bot')
def on_stop():
    state['is_running'] = False
    push_log("Stop signal sent")
    emit('state', state)


# ─────────────────────────────────────────────────────────────
#  STARTUP
# ─────────────────────────────────────────────────────────────

def start():
    global market_thread
    port = int(os.environ.get('PORT', 5000))
    market_thread = threading.Thread(target=market_loop, daemon=True)
    market_thread.start()
    from src.strategy.market_scanner import WATCHLIST as SCANNER_WATCHLIST
    logger.info(f"Smart Scanner Bot on port {port} | Scanning {len(SCANNER_WATCHLIST)} pairs | TF:{TF}")
    socketio.run(app, host='0.0.0.0', port=port, debug=False, allow_unsafe_werkzeug=True)


if __name__ == '__main__':
    start()

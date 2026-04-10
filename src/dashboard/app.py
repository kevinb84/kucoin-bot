"""
KuCoin Trading Bot - Integrated Dashboard + Trading Engine
Supports multiple pairs: XBTUSDTM (BTC) + SIRENUSDTM (SIREN)
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
from src.learning.compounding_engine import CompoundingEngine
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

PRIMARY_SYMBOL = CONFIG.get('symbol', 'XBTUSDTM')
TF             = CONFIG.get('timeframe', '5m')
INTERVAL       = CONFIG.get('check_interval', 10)

# Get all pairs from config
multi_cfg = CONFIG.get('multi_pair_trading', {})
ALL_PAIRS = multi_cfg.get('pairs', [PRIMARY_SYMBOL]) if multi_cfg.get('enabled', False) else [PRIMARY_SYMBOL]

# Contract sizes per symbol (contracts per unit)
# XBTUSDTM: 1 contract = 0.001 BTC
# SIRENUSDTM: 1 contract = 10 SIREN
CONTRACT_SIZE = {
    'XBTUSDTM':  0.001,
    'SIRENUSDTM': 10.0,
    'ETHUSDTM':  0.01,
    'SOLUSDTM':  1.0,
    'XRPUSDTM':  10.0,
}

# ── Shared state ──────────────────────────────────────────────
state = {
    'is_running':    False,
    'ticker':        {},
    'candles':       [],
    'siren_candles': [],
    'position':      None,
    'last_signal':   {'signal': 'none', 'strength': 0, 'reason': ''},
    'performance':   {},
    'recent_trades': [],
    'log_feed':      [],
    'cycle':         0,
    'last_update':   '',
    'pairs':         ALL_PAIRS,
    'active_pair':   PRIMARY_SYMBOL,
    'compounding':   {},
}

# ── Components ────────────────────────────────────────────────
client   = KuCoinClient()
journal  = TradeJournal(db_path=CONFIG.get('journal_db_path', 'trading_journal.db'))
strategy = TrendFollowingStrategy(CONFIG)
risk_mgr = AdvancedRiskManager(CONFIG)
# Compounding engine - starts at current balance with 10% risk per trade
compounder = CompoundingEngine(
    starting_balance = 45.0,   # started at $50, now at $45 after losses
    risk_pct         = 20.0,   # 20% risk per trade = $3-5 profit per winning trade
)

bot_thread    = None
market_thread = None

# ─────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────

def push_log(msg: str):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    state['log_feed'].append(line)
    if len(state['log_feed']) > 100:
        state['log_feed'] = state['log_feed'][-100:]
    socketio.emit('log', {'line': line})
    logger.info(msg)


def df_to_candles(df):
    """Convert OHLCV dataframe to list of dicts for chart."""
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
    """Calculate number of contracts based on margin and contract size."""
    contract_size = CONTRACT_SIZE.get(symbol, 0.001)
    position_usd  = margin_usd * leverage
    contracts     = position_usd / (price * contract_size)
    return max(1, int(contracts))


def update_performance():
    all_trades = []
    for sym in ALL_PAIRS:
        trades = journal.get_recent_trades(sym, limit=10)
        all_trades.extend(trades)
    all_trades.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    state['recent_trades'] = all_trades[:20]
    # Performance from primary pair
    state['performance'] = journal.get_trade_statistics(PRIMARY_SYMBOL)
    state['compounding'] = compounder.get_stats()


# ─────────────────────────────────────────────────────────────
#  MARKET DATA THREAD
# ─────────────────────────────────────────────────────────────

def market_loop():
    """Always-running thread: fetches prices + charts for ALL pairs."""
    logger.info(f"Market loop started for pairs: {ALL_PAIRS}")
    while True:
        try:
            # ── BTC / primary pair ──
            df_btc = client.fetch_ohlcv(PRIMARY_SYMBOL, TF, limit=100)
            if df_btc is not None and not df_btc.empty:
                state['candles'] = df_to_candles(df_btc)

            ticker = client.fetch_ticker(PRIMARY_SYMBOL)
            if ticker:
                state['ticker'] = {
                    'price':  ticker.get('last', 0),
                    'change': ticker.get('percentage', 0),
                    'high':   ticker.get('high', 0),
                    'low':    ticker.get('low', 0),
                    'volume': ticker.get('baseVolume', 0),
                }

            # ── SIREN (if in pairs) ──
            if 'SIRENUSDTM' in ALL_PAIRS:
                df_siren = client.fetch_ohlcv('SIRENUSDTM', TF, limit=100)
                if df_siren is not None and not df_siren.empty:
                    state['siren_candles'] = df_to_candles(df_siren)
                    # Add SIREN ticker to state
                    t_siren = client.fetch_ticker('SIRENUSDTM')
                    if t_siren:
                        state['siren_ticker'] = {
                            'price':  t_siren.get('last', 0),
                            'change': t_siren.get('percentage', 0),
                        }

            # ── Position ──
            for sym in ALL_PAIRS:
                pos = client.fetch_position(sym)
                if pos and float(pos.get('contracts', 0) or 0) != 0:
                    state['position'] = {
                        'symbol':         sym,
                        'side':           'long' if float(pos.get('contracts', 0)) > 0 else 'short',
                        'size':           pos.get('contracts', 0),
                        'entry_price':    pos.get('entryPrice', 0),
                        'mark_price':     pos.get('markPrice', 0),
                        'unrealized_pnl': pos.get('unrealizedPnl', 0),
                        'leverage':       pos.get('leverage', 10),
                    }
                    break
            else:
                state['position'] = None

            state['last_update'] = datetime.now().strftime('%H:%M:%S')
            update_performance()
            socketio.emit('state', state)

        except Exception as e:
            logger.error(f"Market loop error: {e}")

        time.sleep(5)


# ─────────────────────────────────────────────────────────────
#  TRADING ENGINE THREAD
# ─────────────────────────────────────────────────────────────

def trading_loop():
    """Scans ALL pairs every cycle for trade signals."""
    push_log(f"Trading engine started | Pairs: {', '.join(ALL_PAIRS)}")
    push_log(f"Interval: {INTERVAL}s | Min signal: {CONFIG.get('min_signal_strength',5)}/10")
    push_log(f"Pairs loaded from config: {ALL_PAIRS}")
    push_log(f"Multi-pair enabled: {CONFIG.get('multi_pair_trading', {}).get('enabled', False)}")
    for p in ALL_PAIRS:
        from src.api.kucoin_client import to_ccxt_symbol
        push_log(f"  {p} -> {to_ccxt_symbol(p)} (ccxt symbol)")

    while state['is_running']:
        try:
            state['cycle'] += 1
            cycle = state['cycle']

            for symbol in ALL_PAIRS:
                if not state['is_running']:
                    break
                try:
                    df = client.fetch_ohlcv(symbol, TF, limit=100)
                    if df is None or df.empty:
                        push_log(f"[{symbol}] No data - check Railway logs for KuCoin error")
                        time.sleep(5)
                        continue

                    signal = strategy.analyze(df)
                    sig    = signal.get('signal', 'hold')
                    str_   = signal.get('strength', 0)
                    reason = signal.get('reason', '')[:60]

                    if symbol == ALL_PAIRS[0]:
                        state['last_signal'] = signal

                    push_log(f"[{symbol}] #{cycle} {sig.upper()} ({str_}/10) | {reason}")

                    # Check existing position
                    pos = client.fetch_position(symbol)
                    in_pos = pos and float(pos.get('contracts', 0) or 0) != 0

                    if in_pos and risk_mgr.open_position:
                        ticker = client.fetch_ticker(symbol)
                        if ticker:
                            price = float(ticker.get('last', 0))
                            risk_mgr.update_position_tracking(price)
                            risk_mgr.update_trailing_stop(price, risk_mgr.open_position.get('side','buy'))
                            if risk_mgr.check_stop_loss_triggered(price):
                                push_log(f"[{symbol}] STOP LOSS @ {price:.5f}")
                                _close_trade(price, 'stop_loss', symbol)
                                in_pos = False
                            elif risk_mgr.check_take_profit_triggered(price):
                                push_log(f"[{symbol}] TAKE PROFIT @ {price:.5f}")
                                _close_trade(price, 'take_profit', symbol)
                                in_pos = False

                    if not in_pos and sig in ('buy', 'sell'):
                        min_str = CONFIG.get('min_signal_strength', 5)
                        if str_ >= min_str:
                            _execute_trade(sig, str_, symbol)
                        else:
                            push_log(f"[{symbol}] Weak signal ({str_}<{min_str}), skip")

                except Exception as e:
                    push_log(f"[{symbol}] Error: {str(e)[:80]}")
                    logger.error(f"[{symbol}] error: {e}", exc_info=True)

                time.sleep(1)

        except Exception as e:
            push_log(f"Loop error: {str(e)[:80]}")
        time.sleep(INTERVAL)

    push_log("Trading engine stopped")


def _execute_trade(side: str, strength: int, symbol: str):
    """Execute market order for given symbol."""
    try:
        ticker = client.fetch_ticker(symbol)
        if not ticker:
            push_log(f"[{symbol}] Cannot get ticker")
            return
        price = float(ticker.get('last', 0))
        if price <= 0:
            push_log(f"[{symbol}] Bad price: {price}")
            return

        bal = client.fetch_balance()
        if not bal:
            push_log(f"[{symbol}] Cannot get balance")
            return
        usdt = float(bal.get('USDT', {}).get('free', 0) or 0)
        push_log(f"[{symbol}] Balance: ${usdt:.2f}")
        if usdt < 3:
            push_log(f"[{symbol}] Balance too low (${usdt:.2f})")
            return

        leverage   = CONFIG.get('leverage', 10)
        # Use compounding engine for position sizing (grows with balance)
        compounder.update_balance(usdt)
        margin_usd = max(compounder.get_position_size_usd(), 1.0)
        contracts  = get_contracts(symbol, margin_usd, leverage, price)

        sl_pct = CONFIG.get('stop_loss_percent', 0.2) / 100
        tp_pct = CONFIG.get('take_profit_percent', 0.6) / 100
        sl = round(price * (1 - sl_pct if side=='buy' else 1 + sl_pct), 6)
        tp = round(price * (1 + tp_pct if side=='buy' else 1 - tp_pct), 6)

        push_log(f"[{symbol}] {side.upper()} {contracts} contracts @ {price:.5f} | SL:{sl:.5f} TP:{tp:.5f}")

        order = client.create_order(symbol=symbol, order_type='market', side=side, amount=contracts)
        if order:
            push_log(f"[{symbol}] Order filled! ID:{order.get('id','?')}")
            risk_mgr.open_trade({
                'symbol': symbol, 'side': side, 'entry_price': price,
                'quantity': contracts, 'leverage': leverage,
                'stop_loss': sl, 'take_profit': tp, 'signal_strength': strength,
            })
        else:
            push_log(f"[{symbol}] Order failed - check terminal for KuCoin error")

    except Exception as e:
        push_log(f"[{symbol}] Trade error: {str(e)[:100]}")
        logger.error(f"Execute trade error: {e}", exc_info=True)


def _close_trade(exit_price: float, reason: str, symbol: str):
    """Close open position for symbol."""
    try:
        if not risk_mgr.open_position:
            return
        side       = risk_mgr.open_position['side']
        qty        = abs(risk_mgr.open_position['quantity'])
        close_side = 'sell' if side == 'buy' else 'buy'
        order = client.create_order(symbol=symbol, order_type='market',
                                    side=close_side, amount=qty,
                                    params={'reduceOnly': True})
        if order:
            result = risk_mgr.close_trade(exit_price, reason)
            if result:
                journal.record_trade(result)
                pnl = result.get('pnl', 0)
                compounder.record_trade(pnl, side, symbol)
                tag = 'WIN' if pnl >= 0 else 'LOSS'
                push_log(f"[{symbol}] [{tag}] {reason} | PnL: ${pnl:.4f}")
        else:
            push_log(f"[{symbol}] CLOSE FAILED!")
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
    return jsonify(journal.get_recent_trades(PRIMARY_SYMBOL, limit=50))

@app.route('/api/performance')
def api_performance():
    return jsonify(journal.get_trade_statistics(PRIMARY_SYMBOL))

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
    logger.info(f"Dashboard on port {port} | Pairs: {ALL_PAIRS}")
    socketio.run(app, host='0.0.0.0', port=port, debug=False, allow_unsafe_werkzeug=True)


if __name__ == '__main__':
    start()

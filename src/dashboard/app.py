"""
KuCoin Advanced AI Scanner Bot
Scans ALL KuCoin Futures pairs, scores 0-100.
Only trades when score >= 70 AND profit > 3x fees.
Supports up to 3 concurrent positions.
5-minute chart with fee-aware position sizing.
"""

from flask import Flask, render_template, jsonify
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
from src.strategy.market_scanner import AdvancedMarketScanner, CONTRACT_SIZE, KUCOIN_FEE_RATE
from src.risk.advanced_risk_manager import AdvancedRiskManager
from src.learning.trade_journal import TradeJournal
from src.learning.compounding_engine import CompoundingEngine
from src.strategy.market_intelligence import MarketIntelligence
from src.learning.adaptive_intelligence import AdaptiveIntelligenceEngine
from src.utils.logger import get_logger

logger = get_logger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'kucoin-ai-bot-2026'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# ── Load config ───────────────────────────────────────────────
CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'config', 'config.yaml'
)
with open(CONFIG_PATH, 'r') as f:
    CONFIG = yaml.safe_load(f)

TF              = CONFIG.get('timeframe', '5m')
INTERVAL        = CONFIG.get('check_interval', 15)
MIN_SCORE       = CONFIG.get('scanner_min_score', 70)  # Now out of 100
MAX_POSITIONS   = CONFIG.get('scanner_max_open', 3)
RISK_PER_TRADE  = CONFIG.get('risk_per_trade', 3.0)  # 3% of balance per trade

# ── Shared state ──────────────────────────────────────────────
state = {
    'is_running':      False,
    'ticker':          {},
    'candles':         [],
    'positions':       [],     # List of open positions
    'last_signal':     {'signal': 'none', 'strength': 0, 'reason': ''},
    'performance':     {},
    'recent_trades':   [],
    'log_feed':        [],
    'cycle':           0,
    'last_update':     '',
    'active_pair':     'Scanning...',
    'compounding':     {},
    'scanner_results': [],
    'trade_open_times': {},    # symbol -> open timestamp
}

# ── Components ────────────────────────────────────────────────
client     = KuCoinClient()
journal    = TradeJournal(db_path=CONFIG.get('journal_db_path', 'trading_journal.db'))
strategy   = TrendFollowingStrategy(CONFIG)
risk_mgr   = AdvancedRiskManager(CONFIG)
intel      = MarketIntelligence(client)
compounder = CompoundingEngine(starting_balance=45.0, risk_pct=RISK_PER_TRADE * 10)
scanner    = AdvancedMarketScanner(client, strategy, intel, timeframe=TF)
ai_engine  = AdaptiveIntelligenceEngine(journal, scanner, CONFIG)

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
    all_trades = journal.get_recent_trades(limit=20)
    state['recent_trades'] = all_trades
    state['performance']   = journal.get_trade_statistics()
    state['compounding']   = compounder.get_stats()
    state['scanner_results'] = scanner.get_watchlist_status()
    state['ai_learning']   = ai_engine.get_learning_summary()
    state['intelligence']  = {
        'flash_crash_cooldown': intel.flash_crash_cooldown,
        'consecutive_losses':  intel.consecutive_losses,
        'session':             intel.get_session_info().get('session', 'unknown'),
    }


# ─────────────────────────────────────────────────────────────
#  MARKET DATA THREAD
# ─────────────────────────────────────────────────────────────

def market_loop():
    logger.info("Market data loop started")
    while True:
        try:
            # Show chart for first active symbol or BTC
            active_syms = list(state.get('trade_open_times', {}).keys())
            display_sym = active_syms[0] if active_syms else 'XBTUSDTM'

            df = client.fetch_ohlcv(display_sym, TF, limit=100)
            if df is not None and not df.empty:
                state['candles'] = df_to_candles(df)

            ticker = client.fetch_ticker(display_sym)
            if ticker:
                state['ticker'] = {
                    'symbol': display_sym,
                    'price':  ticker.get('last', 0),
                    'change': ticker.get('percentage', 0),
                    'high':   ticker.get('high', 0),
                    'low':    ticker.get('low', 0),
                    'volume': ticker.get('baseVolume', 0),
                }

            # Check all open positions
            positions = []
            for sym in list(state.get('trade_open_times', {}).keys()):
                pos = client.fetch_position(sym)
                if pos and float(pos.get('contracts', 0) or 0) != 0:
                    positions.append({
                        'symbol':         sym,
                        'side':           'long' if float(pos.get('contracts', 0)) > 0 else 'short',
                        'size':           pos.get('contracts', 0),
                        'entry_price':    pos.get('entryPrice', 0),
                        'mark_price':     pos.get('markPrice', 0),
                        'unrealized_pnl': pos.get('unrealizedPnl', 0),
                        'leverage':       pos.get('leverage', 10),
                    })
            state['positions'] = positions

            state['last_update'] = datetime.now().strftime('%H:%M:%S')
            update_performance()
            socketio.emit('state', state)

        except Exception as e:
            logger.error(f"Market loop error: {e}")

        time.sleep(5)


# ─────────────────────────────────────────────────────────────
#  TRADING ENGINE - AI SCANNER DRIVEN
# ─────────────────────────────────────────────────────────────

def trading_loop():
    push_log(f"AI Scanner Bot v2 | TF:{TF} | Min score:{MIN_SCORE}/100")
    push_log(f"Max positions:{MAX_POSITIONS} | Risk:{RISK_PER_TRADE}% per trade")
    push_log("Scanning all KuCoin Futures pairs for high-probability setups...")

    while state['is_running']:
        try:
            state['cycle'] += 1
            cycle = state['cycle']

            # ── MANAGE EXISTING POSITIONS ───────────────────
            open_syms = list(state.get('trade_open_times', {}).keys())

            for sym in open_syms[:]:
                ticker = client.fetch_ticker(sym)
                if not ticker:
                    continue

                price = float(ticker.get('last', 0))
                if price <= 0:
                    continue

                # Update risk manager tracking
                if risk_mgr.open_position and risk_mgr.open_position.get('symbol') == sym:
                    risk_mgr.update_position_tracking(price)
                    risk_mgr.update_trailing_stop(price, risk_mgr.open_position.get('side', 'buy'))

                    # Check exit conditions
                    if risk_mgr.check_stop_loss_triggered(price):
                        push_log(f"[{sym}] STOP LOSS @ {price:.6f}")
                        _close_trade(price, 'stop_loss', sym)
                        open_syms.remove(sym)
                        continue

                    elif risk_mgr.check_take_profit_triggered(price):
                        push_log(f"[{sym}] TAKE PROFIT @ {price:.6f}")
                        _close_trade(price, 'take_profit', sym)
                        open_syms.remove(sym)
                        continue

                    elif state['trade_open_times'].get(sym):
                        hold_secs = time.time() - state['trade_open_times'][sym]
                        trend_component = best.get('trend', 0) if 'best' in locals() else 0
                        if trend_component >= 25:
                            max_hold = CONFIG.get('max_hold_strong_trend', 60) * 60
                        else:
                            max_hold = CONFIG.get('max_hold_time_minutes', 20) * 60
                        if hold_secs >= max_hold:
                            push_log(f"[{sym}] MAX HOLD ({hold_secs/60:.1f}min) - closing")
                            _close_trade(price, 'max_hold_time', sym)
                            open_syms.remove(sym)
                            continue

            # ── SCAN FOR NEW OPPORTUNITIES ──────────────────
            open_count = len(state.get('trade_open_times', {}))

            if open_count < MAX_POSITIONS:
                push_log(f"[#{cycle}] Scanning market... ({open_count}/{MAX_POSITIONS} positions open)")
                state['active_pair'] = 'Scanning...'

                best = scanner.get_best_opportunity(
                    exclude_symbols=open_syms,
                    open_positions=open_count
                )

                # Aggression mode: adjust based on recent performance
                recent_wins = sum(1 for t in ai_engine.recent_trades[-10:] if t['won']) if ai_engine.recent_trades else 0
                recent_wr = recent_wins / min(len(ai_engine.recent_trades), 10) if ai_engine.recent_trades else 0

                if recent_wr > 0.60:
                    push_log(f"[AI] AGGRESSION MODE: Recent WR {recent_wr:.1%} - lowering entry bar")
                elif recent_wr < 0.35:
                    push_log(f"[AI] DEFENSIVE MODE: Recent WR {recent_wr:.1%} - raising standards")

                if best and best.get('tradeable'):
                    symbol = best['symbol']
                    side   = best['signal']
                    score  = best['total_score']
                    reason = best.get('reason', '')[:100]

                    # AI filtering: check symbol tradeability
                    tradeable, ai_reason = ai_engine.is_symbol_tradeable(symbol)
                    if not tradeable:
                        push_log(f"[#{cycle}] SKIPPED {symbol}: {ai_reason}")
                        time.sleep(2)
                        continue

                    # Check session quality
                    session_info = intel.get_session_info()
                    should_trade_sess, sess_reason = ai_engine.should_trade_this_session(session_info.get('session', 'unknown'))
                    if not should_trade_sess:
                        push_log(f"[#{cycle}] Session blocked: {sess_reason}")
                        time.sleep(5)
                        continue

                    # BTC correlation check
                    btc_df = scanner._get_btc_df()
                    if btc_df is not None and len(btc_df) >= 6:
                        btc_change = (btc_df.iloc[-1]['close'] - btc_df.iloc[-6]['close']) / btc_df.iloc[-6]['close'] * 100
                        btc_trend = 'bullish' if btc_change > 0.3 else ('bearish' if btc_change < -0.3 else 'neutral')
                        corr_ok, corr_reason = ai_engine.get_btc_correlation_advice(symbol, btc_trend)
                        if not corr_ok:
                            push_log(f"[#{cycle}] Correlation warning: {corr_reason}")
                            time.sleep(2)
                            continue

                    push_log(f"[#{cycle}] FOUND: {symbol} {side.upper()} score={score}/100 | AI: {ai_reason}")
                    push_log(f"  Reason: {reason}")
                    state['active_pair']  = symbol
                    state['last_signal']  = best

                    _execute_trade(side, score, symbol)
                else:
                    push_log(f"[#{cycle}] No qualifying setups (need {MIN_SCORE}+/100). Waiting...")
                    state['active_pair'] = 'Waiting for setup...'
            else:
                push_log(f"[#{cycle}] Max positions ({MAX_POSITIONS}) reached. Managing open trades...")
                state['active_pair'] = f'{open_count} positions open'

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

        df = client.fetch_ohlcv(symbol, TF, limit=50)

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

        # Dynamic position sizing: risk 2-5% based on confidence
        risk_pct = RISK_PER_TRADE
        if strength >= 85:
            risk_pct = RISK_PER_TRADE * 1.5  # Increase for very high confidence
        elif strength < 75:
            risk_pct = RISK_PER_TRADE * 0.7  # Reduce for marginal setups

        # Calculate position size from stop-loss distance
        sl_pct = CONFIG.get('stop_loss_percent', 0.3) / 100
        margin_usd = (usdt * risk_pct / 100) / sl_pct if sl_pct > 0 else usdt * 0.03

        # Cap margin at available balance
        margin_usd = min(margin_usd, usdt * 0.4)
        margin_usd = max(margin_usd, 5.0)  # Minimum $5

        # Apply loss limiter
        loss_check = intel.check_loss_limit()
        if loss_check['position_multiplier'] < 1.0:
            margin_usd = margin_usd * loss_check['position_multiplier']
            push_log(f"[{symbol}] Size reduced: {loss_check['reason']}")

        contracts = get_contracts(symbol, margin_usd, leverage, price)

        # Dynamic TP based on trend strength
        if CONFIG.get('take_profit_dynamic', False):
            trend_component = best.get('trend', 0) if 'best' in locals() else 0
            if trend_component >= 25:
                tp_pct = CONFIG.get('tp_strong_trend', 1.2) / 100
            else:
                tp_pct = CONFIG.get('tp_normal', 0.8) / 100
        else:
            tp_pct = CONFIG.get('take_profit_percent', 0.6) / 100

        # Dynamic trailing stop based on volatility
        atr_pct = scanner._estimate_atr_pct(df) if 'df' in locals() and df is not None else 1.0
        if atr_pct > 2.0:
            trailing_distance = CONFIG.get('trailing_stop_volatile', 0.5) / 100
        else:
            trailing_distance = CONFIG.get('trailing_stop_distance', 0.25) / 100

        # Minimum profit filter: skip if expected profit < $1.00
        expected_profit_usd = margin_usd * leverage * tp_pct
        if expected_profit_usd < 1.0:
            push_log(f"[{symbol}] SKIPPED: Expected profit ${expected_profit_usd:.2f} too small (min $1.00)")
            return
        sl = round(price * (1 - sl_pct if side == 'buy' else 1 + sl_pct), 8)
        tp = round(price * (1 + tp_pct if side == 'buy' else 1 - tp_pct), 8)

        # Fee check: ensure profit > 3x fees
        expected_profit_pct = tp_pct * 100
        fee_cost_pct = KUCOIN_FEE_RATE * 2 * 100 * leverage  # Entry + exit fees
        if expected_profit_pct < fee_cost_pct * 3:
            push_log(f"[{symbol}] SKIPPED: Expected profit ({expected_profit_pct:.2f}%) < 3x fees ({fee_cost_pct*3:.2f}%)")
            return

        push_log(f"[{symbol}] {side.upper()} {contracts} contracts @ {price:.6f} | margin=${margin_usd:.2f} | SL:{sl:.6f} TP:{tp:.6f}")

        order = client.create_order(symbol=symbol, order_type='market', side=side, amount=contracts)
        if order:
            push_log(f"[{symbol}] ORDER FILLED! ID:{order.get('id','?')}")
            risk_mgr.open_trade({
                'symbol': symbol, 'side': side, 'entry_price': price,
                'quantity': contracts, 'leverage': leverage,
                'stop_loss': sl, 'take_profit': tp, 'signal_strength': strength,
            })
            state['trade_open_times'][symbol] = time.time()
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
                scanner.record_trade_result(symbol, won=(pnl >= 0), pnl=pnl)

                # Record in adaptive AI engine with full context
                session_info = intel.get_session_info()
                btc_df = scanner._get_btc_df()
                market_regime = ai_engine.detect_market_regime(btc_df) if btc_df is not None else 'unknown'
                btc_trend = 'neutral'
                if btc_df is not None and len(btc_df) >= 6:
                    btc_change = (btc_df.iloc[-1]['close'] - btc_df.iloc[-6]['close']) / btc_df.iloc[-6]['close'] * 100
                    if btc_change > 0.3:
                        btc_trend = 'bullish'
                    elif btc_change < -0.3:
                        btc_trend = 'bearish'

                ai_engine.record_trade({
                    'symbol': symbol,
                    'side': side,
                    'entry_price': result.get('entry_price', 0),
                    'exit_price': exit_price,
                    'pnl': pnl,
                    'pnl_percent': result.get('pnl_percent', 0),
                    'strategy_used': 'trend_following',  # Could be dynamic based on signal type
                    'signal_strength': result.get('signal_strength', 0),
                    'session': session_info.get('session', 'unknown'),
                    'market_regime': market_regime,
                    'btc_trend_at_entry': btc_trend,
                })

                tag = 'WIN ✓' if pnl >= 0 else 'LOSS ✗'
                push_log(f"[{symbol}] [{tag}] {reason} | PnL: ${pnl:.4f}")

                # Check for weekly report
                report = ai_engine.check_and_generate_report()
                if report:
                    push_log("[AI] Weekly performance report generated")
                    logger.info(report)
        else:
            push_log(f"[{symbol}] CLOSE FAILED!")

        state['trade_open_times'].pop(symbol, None)

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
    logger.info(f"AI Scanner Bot v2 on port {port} | TF:{TF} | Score threshold:{MIN_SCORE}/100")
    socketio.run(app, host='0.0.0.0', port=port, debug=False, allow_unsafe_werkzeug=True)


if __name__ == '__main__':
    start()

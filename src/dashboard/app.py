"""
KuCoin AI Trader v7.1
Adaptive scoring: Model(40-60%) + ML(10-30%) + Orderflow(30%)
Threshold: 0.65 (dynamic based on mode/activity)
Defensive mode on daily loss | Force scan after 3h inactivity
Micro-confirmation skips in low volatility (ATR < 1%)
Max 3 positions | 7% daily stop loss
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
from src.strategy.order_flow import OrderFlowAnalyzer
from src.risk.advanced_risk_manager import AdvancedRiskManager
from src.learning.trade_journal import TradeJournal
from src.learning.compounding_engine import CompoundingEngine
from src.strategy.market_intelligence import MarketIntelligence
from src.learning.adaptive_intelligence import AdaptiveIntelligenceEngine
from src.ml.trade_predictor import TradePredictor
from src.utils.logger import get_logger

logger = get_logger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'kucoin-ai-bot-v7-2026'
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
SCORE_THRESHOLD = CONFIG.get('score_threshold', 0.65)
MAX_POSITIONS   = CONFIG.get('scanner_max_open', 3)
RISK_PER_TRADE  = CONFIG.get('risk_per_trade', 3.0)
DAILY_STOP_PCT  = CONFIG.get('daily_stop_loss_pct', 7.0)

# ── Shared state ──────────────────────────────────────────────
state = {
    'is_running':      False,
    'ticker':          {},
    'candles':         [],
    'positions':       [],
    'last_signal':     {'signal': 'none', 'strength': 0, 'reason': ''},
    'performance':     {},
    'recent_trades':   [],
    'log_feed':        [],
    'cycle':           0,
    'last_update':     '',
    'active_pair':     'Scanning...',
    'compounding':     {},
    'scanner_results': [],
    'trade_open_times': {},
    'daily_pnl':       0.0,
    'daily_stop_hit':  False,
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
order_analyzer = OrderFlowAnalyzer(client)
ml_predictor = TradePredictor()

bot_thread    = None
market_thread = None

# ── Daily PnL tracking ────────────────────────────────────────
daily_pnl_start = 0.0
daily_pnl_reset_date = None


def get_trading_mode(effective_threshold=SCORE_THRESHOLD):
    """Determine current trading mode based on performance."""
    daily_pnl = risk_mgr.daily_pnl or 0
    max_daily_loss = CONFIG.get('max_daily_loss', 7.0)

    # Quality priority: if recent losses, raise threshold
    if len(ai_engine.recent_trades) >= 5:
        last_5 = ai_engine.recent_trades[-5:]
        loss_count = sum(1 for t in last_5 if not t.get('won', False))
        if loss_count >= 3:
            effective_threshold += 0.05
            push_log(f"[v7] QUALITY MODE: {loss_count}/5 losses — raising threshold to {effective_threshold:.2f}")

    # Performance feedback: adjust threshold based on recent win rate
    if len(ai_engine.recent_trades) >= 10:
        last_10 = ai_engine.recent_trades[-10:]
        recent_wr = sum(1 for t in last_10 if t['won']) / 10

        if recent_wr < 0.40:
            effective_threshold += 0.05
            push_log(f"[v7] POOR PERFORMANCE (WR {recent_wr:.0%}) — raising threshold to {effective_threshold:.2f}")
        elif recent_wr > 0.65:
            effective_threshold = max(0.55, effective_threshold - 0.03)
            push_log(f"[v7] STRONG PERFORMANCE (WR {recent_wr:.0%}) — lowering threshold to {effective_threshold:.2f}")

    if daily_pnl < -max_daily_loss:
        return 'DEFENSIVE', effective_threshold
    elif ai_engine.recent_trades and len(ai_engine.recent_trades) >= 10:
        recent_wr = sum(1 for t in ai_engine.recent_trades[-10:] if t.get('won')) / 10
        if recent_wr > 0.60:
            return 'AGGRESSIVE', effective_threshold
    return 'NORMAL', effective_threshold


def reset_daily_pnl_if_needed():
    global daily_pnl_start, daily_pnl_reset_date
    today = datetime.now().date()
    if daily_pnl_reset_date != today:
        daily_pnl_reset_date = today
        daily_pnl_start = compounder.get_stats().get('current_balance', 45.0)
        state['daily_pnl'] = 0.0
        state['daily_stop_hit'] = False
        push_log(f"[v7] Daily PnL reset. Starting balance: ${daily_pnl_start:.2f}")

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
    push_log(f"AI Trader v7 | TF:{TF} | Threshold:{SCORE_THRESHOLD}")
    push_log(f"Scoring: Model(40%) + ML(30%) + Orderflow(30%)")
    push_log(f"Max positions:{MAX_POSITIONS} | Risk:{RISK_PER_TRADE}% | Daily stop:{DAILY_STOP_PCT}%")
    push_log("Scanning all KuCoin Futures pairs for high-probability setups...")

    while state['is_running']:
        try:
            reset_daily_pnl_if_needed()

            # Trade frequency control
            now = time.time()
            recent_trades_1h = [t for t in ai_engine.recent_trades if now - t['timestamp'] < 3600]
            if len(recent_trades_1h) >= 5:
                push_log(f"[v7] RATE LIMIT: 5 trades in last hour — waiting...")
                time.sleep(INTERVAL * 2)
                continue

            # Minimum 3 min between trades
            if ai_engine.recent_trades:
                last_trade_ts = ai_engine.recent_trades[-1]['timestamp']
                if now - last_trade_ts < 180:
                    time.sleep(10)
                    continue

            trading_mode, effective_threshold = get_trading_mode()

            if trading_mode == 'DEFENSIVE':
                daily_pnl = risk_mgr.daily_pnl or 0
                push_log(f"[v7] DEFENSIVE MODE: Daily loss {daily_pnl:.2f}% — reducing risk to 1%, raising threshold")
                effective_risk_pct = 1.0
                effective_threshold = 0.70
            elif trading_mode == 'AGGRESSIVE':
                effective_risk_pct = RISK_PER_TRADE * 1.5
                effective_threshold = 0.58
            else:
                effective_risk_pct = RISK_PER_TRADE

            last_trade_time = ai_engine.recent_trades[-1]['timestamp'] if ai_engine.recent_trades else 0
            hours_since_trade = (time.time() - last_trade_time) / 3600 if last_trade_time > 0 else 999

            if hours_since_trade > 2:
                effective_threshold = max(0.55, effective_threshold - 0.05)
                push_log(f"[v7] INACTIVITY DETECTED ({hours_since_trade:.1f}h) — lowering threshold to {effective_threshold:.2f}")

            if hours_since_trade > 3:
                push_log(f"[v7] FORCE SCAN MODE: Executing best available setup")
                force_mode = True
            else:
                force_mode = False

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
                        if sym in open_syms:
                            open_syms.remove(sym)
                        continue

                    elif risk_mgr.check_take_profit_triggered(price):
                        push_log(f"[{sym}] TAKE PROFIT @ {price:.6f}")
                        _close_trade(price, 'take_profit', sym)
                        if sym in open_syms:
                            open_syms.remove(sym)
                        continue

                    elif state['trade_open_times'].get(sym):
                        hold_secs = time.time() - state['trade_open_times'][sym]
                        max_hold = CONFIG.get('max_hold_time_minutes', 20) * 60
                        if hold_secs >= max_hold:
                            push_log(f"[{sym}] MAX HOLD ({hold_secs/60:.1f}min) - closing")
                            _close_trade(price, 'max_hold_time', sym)
                            if sym in open_syms:
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

                if best and best.get('tradeable'):
                    symbol = best['symbol']
                    side   = best['signal']
                    score  = best['total_score']
                    reason = best.get('reason', '')[:100]

                    # Fetch OHLCV for entry model analysis
                    df = client.fetch_ohlcv(symbol, TF, limit=100)
                    if df is None or df.empty or len(df) < 30:
                        push_log(f"[#{cycle}] SKIPPED {symbol}: Insufficient data")
                        time.sleep(2)
                        continue

                    # Add indicators for analysis
                    df = scanner._add_indicators(df)
                    latest = df.iloc[-1]

                    # Run all 3 entry models
                    liq_grab = scanner._detect_liquidity_grab(df)
                    breakout = scanner._detect_breakout_retest(df)
                    momentum = scanner._detect_momentum_ignition(df)

                    # Pick highest confidence model
                    models = [liq_grab, breakout, momentum]
                    best_model = max(models, key=lambda x: x['confidence'])

                    model_confidence = best_model['confidence']
                    push_log(f"[v7] Model confidence: {model_confidence:.2f} | Checking entry models...")
                    if model_confidence == 0.0:
                        push_log(f"[v7] WARNING: All entry models returned 0.0 — market conditions may not match any setup")

                    # Order flow analysis
                    orderflow = order_analyzer.analyze_orderbook_imbalance(symbol)
                    orderflow_score = orderflow.get('imbalance', 0)
                    orderflow_normalized = (orderflow_score + 1) / 2

                    # ML prediction
                    btc_df = scanner._get_btc_df()
                    btc_direction = 0
                    if btc_df is not None and len(btc_df) >= 6:
                        btc_direction = (btc_df.iloc[-1]['close'] - btc_df.iloc[-6]['close']) / btc_df.iloc[-6]['close']

                    ml_features = {
                        'trend_strength': best.get('trend', 0) / 30.0,
                        'volume_ratio': best.get('volume', 0) / 25.0,
                        'volatility': scanner._estimate_atr_pct(df),
                        'rsi': latest.get('rsi', 50) if 'rsi' in latest else 50,
                        'btc_direction': btc_direction,
                        'orderbook_imbalance': orderflow_score,
                        'distance_from_liquidity': 0,
                        'breakout_strength': best.get('momentum', 0) / 20.0,
                        'candle_momentum': abs(latest['close'] - latest['open']) / latest['open'] * 100
                    }

                    ml_confidence = ml_predictor.predict_win_probability(ml_features)

                    total_trades_count = len(ai_engine.recent_trades)
                    if total_trades_count < 30:
                        ml_weight = 0.10
                        model_weight = 0.60
                        of_weight = 0.30
                    else:
                        ml_weight = 0.30
                        model_weight = 0.40
                        of_weight = 0.30

                    final_score = (
                        model_confidence * model_weight +
                        ml_confidence * ml_weight +
                        orderflow_normalized * of_weight
                    )

                    push_log(f"[{symbol}] Score: {final_score:.2f}/{effective_threshold:.2f} | Model:{model_confidence:.2f} ML:{ml_confidence:.2f} OF:{orderflow_normalized:.2f} | Mode:{trading_mode}")

                    # Force scan safety floor
                    if force_mode and final_score < 0.60:
                        if model_confidence < 0.65 and orderflow_normalized < 0.60:
                            push_log(f"[{symbol}] FORCE SCAN REJECTED: Model ({model_confidence:.2f}) and Orderflow ({orderflow_normalized:.2f}) too weak")
                            time.sleep(2)
                            continue
                        push_log(f"[{symbol}] FORCE SCAN OVERRIDE: Executing based on strong {'Model' if model_confidence >= 0.65 else 'Orderflow'}")

                    if force_mode:
                        push_log(f"[v7] FORCE MODE TRADE EXECUTED | Model:{model_confidence:.2f} OF:{orderflow_normalized:.2f}")
                        state['force_mode_trades'] = state.get('force_mode_trades', 0) + 1

                    if not force_mode and final_score < effective_threshold:
                        push_log(f"[{symbol}] Score too low ({final_score:.2f} < {effective_threshold}) - skipping")
                        time.sleep(2)
                        continue

                    push_log(f"[{symbol}] FINAL SCORE: {final_score:.2f} | Model:{model_confidence:.2f} ML:{ml_confidence:.2f} OF:{orderflow_normalized:.2f}")

                    atr_pct = scanner._estimate_atr_pct(df)
                    if not scanner._micro_confirm_entry(df, best_model['signal'], atr_pct):
                        push_log(f"[{symbol}] Micro-confirmation FAILED - waiting")
                        time.sleep(INTERVAL)
                        continue

                    push_log(f"[{symbol}] Micro-confirmation PASSED")

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
                    if btc_df is not None and len(btc_df) >= 6:
                        btc_change = (btc_df.iloc[-1]['close'] - btc_df.iloc[-6]['close']) / btc_df.iloc[-6]['close'] * 100
                        btc_trend = 'bullish' if btc_change > 0.3 else ('bearish' if btc_change < -0.3 else 'neutral')
                        corr_ok, corr_reason = ai_engine.get_btc_correlation_advice(symbol, btc_trend)
                        if not corr_ok:
                            push_log(f"[#{cycle}] Correlation warning: {corr_reason}")
                            time.sleep(2)
                            continue

                    push_log(f"[#{cycle}] ENTRY APPROVED: {symbol} {best_model['signal'].upper()} | Model: {best_model['reason']}")
                    state['active_pair']  = symbol
                    # Don't store 'best' in state (contains non-serializable data)
                    # state['last_signal']  = best

                    _execute_trade(best_model['signal'], final_score, symbol, df, effective_risk_pct, trading_mode)
                else:
                    push_log(f"[#{cycle}] No qualifying setups. Waiting...")
                    state['active_pair'] = 'Waiting for setup...'
                    
                    # If force mode and still no trades after full scan, execute best available
                    if force_mode:
                        push_log(f"[v7] FORCE MODE: No model-triggered setups found — executing highest scoring pair")
                        best_fallback = None
                        best_fallback_score = 0
                        
                        for sym, cached in scanner.scan_cache.items():
                            score = cached.get('total_score', 0)
                            if score > best_fallback_score:
                                best_fallback = cached
                                best_fallback_score = score
                        
                        if best_fallback_score == 0.0:
                            push_log(f"[v7] All scores 0.0 — using volume/volatility fallback scoring")
                            for sym in scanner.active_symbols:
                                try:
                                    df_temp = client.fetch_ohlcv(sym, TF, limit=20)
                                    if df_temp is None or df_temp.empty:
                                        continue
                                    vol_ratio = df_temp['volume'].iloc[-1] / df_temp['volume'].mean()
                                    atr_pct = scanner._estimate_atr_pct(df_temp)
                                    fallback_score = min((vol_ratio * atr_pct) * 10, 5.0)
                                    if fallback_score > best_fallback_score:
                                        best_fallback_score = fallback_score
                                        best_fallback = {'symbol': sym, 'total_score': fallback_score, 'signal': 'buy', 'df': df_temp}
                                except:
                                    continue

                        if best_fallback and best_fallback_score > 0.50:
                            fb_symbol = best_fallback['symbol']
                            fb_side = best_fallback['signal']
                            fb_df = best_fallback.get('df')
                            
                            ticker = client.fetch_ticker(fb_symbol)
                            if ticker and float(ticker.get('last', 0)) > 0:
                                fb_price = float(ticker['last'])
                                bal = client.fetch_balance()
                                if bal:
                                    usdt = float(bal.get('USDT', {}).get('free', 0) or 0)
                                    leverage = CONFIG.get('leverage', 10)
                                    fb_atr = scanner._estimate_atr_pct(fb_df) if fb_df is not None else 1.0
                                    fb_tp_pct = CONFIG.get('tp_normal', 0.8) / 100
                                    fb_entry_fee = usdt * 0.03 * leverage * KUCOIN_FEE_RATE
                                    fb_exit_fee = usdt * 0.03 * leverage * fb_tp_pct * KUCOIN_FEE_RATE
                                    fb_expected_net = (usdt * 0.03 * leverage * fb_tp_pct) - (fb_entry_fee + fb_exit_fee)
                                    
                                    if fb_expected_net > 1.00:
                                        push_log(f"[v7] FORCE EXECUTING: {fb_symbol} score={best_fallback_score:.2f} expected_net=${fb_expected_net:.2f}")
                                        _execute_trade(
                                            fb_side,
                                            best_fallback_score,
                                            fb_symbol,
                                            fb_df,
                                            effective_risk_pct * 0.5
                                        )
                                    else:
                                        push_log(f"[v7] FORCE MODE REJECTED: {fb_symbol} expected net profit ${fb_expected_net:.2f} < $1.00")
                                else:
                                    push_log(f"[v7] FORCE MODE: Cannot fetch balance for fallback")
                            else:
                                push_log(f"[v7] FORCE MODE: Cannot fetch ticker for {fb_symbol}")
                        else:
                            push_log(f"[v7] FORCE MODE: No suitable fallback found (best score: {best_fallback_score:.2f})")
            else:
                push_log(f"[#{cycle}] Max positions ({MAX_POSITIONS}) reached. Managing open trades...")
                state['active_pair'] = f'{open_count} positions open'

        except Exception as e:
            push_log(f"Loop error: {str(e)[:80]}")
            logger.error(f"Trading loop error: {e}", exc_info=True)

        time.sleep(INTERVAL)

    push_log("Trading engine stopped")


def _execute_trade(side: str, final_score: float, symbol: str, df: pd.DataFrame, effective_risk_pct: float, trading_mode: str):
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
        if leverage != 10:
            push_log(f"[WARNING] Leverage is {leverage}x — overriding to 10x")
            leverage = 10

        # Volatility-based leverage adjustment
        atr_pct = scanner._estimate_atr_pct(df) if df is not None else 1.0
        if atr_pct > 2.0:
            leverage = 5
            push_log(f"[{symbol}] High volatility (ATR {atr_pct:.1f}%) — reducing leverage to 5x")
        else:
            leverage = CONFIG.get('leverage', 10)

        compounder.update_balance(usdt)

        risk_pct = effective_risk_pct
        if final_score >= 0.80:
            risk_pct = effective_risk_pct * 1.5
        elif final_score < 0.70:
            risk_pct = effective_risk_pct * 0.7

        # Dynamic stop loss based on volatility
        atr_pct = scanner._estimate_atr_pct(df) if df is not None else 1.0
        if atr_pct > 2.0:
            sl_pct = CONFIG.get('stop_loss_volatile', 0.7) / 100
        else:
            sl_pct = CONFIG.get('stop_loss_base', 0.35) / 100
        margin_usd = (usdt * risk_pct / 100) / sl_pct if sl_pct > 0 else usdt * 0.03

        # Cap margin at available balance
        margin_usd = min(margin_usd, usdt * 0.4)
        margin_usd = max(margin_usd, 5.0)

        # Edge optimization: reduce size for low-edge strategies
        edge_scores = ai_engine.get_edge_quality_scores()
        current_strategy = 'trend_following'
        strategy_edge = edge_scores.get(current_strategy, 0)

        if strategy_edge < 0.5:
            margin_usd *= 0.7
            push_log(f"[{symbol}] Low edge strategy (${strategy_edge:.2f}/trade) — reducing size 30%")

        # Apply loss limiter
        loss_check = intel.check_loss_limit()
        if loss_check['position_multiplier'] < 1.0:
            margin_usd = margin_usd * loss_check['position_multiplier']
            push_log(f"[{symbol}] Size reduced: {loss_check['reason']}")

        contracts = get_contracts(symbol, margin_usd, leverage, price)

        # Dynamic TP based on volatility (ATR-based)
        if atr_pct > 2.0:
            tp_pct = CONFIG.get('tp_volatile', 1.5) / 100
        elif atr_pct > 1.0:
            tp_pct = CONFIG.get('tp_normal', 0.8) / 100
        else:
            tp_pct = CONFIG.get('tp_low_vol', 0.5) / 100

        # Dynamic trailing stop based on volatility
        if atr_pct > 2.0:
            trailing_distance = CONFIG.get('trailing_stop_volatile', 0.5) / 100
        else:
            trailing_distance = CONFIG.get('trailing_stop_distance', 0.25) / 100

        # Strict profit enforcement: expected profit AFTER fees
        entry_fee = margin_usd * leverage * KUCOIN_FEE_RATE
        exit_fee = margin_usd * leverage * tp_pct * KUCOIN_FEE_RATE
        total_fees = entry_fee + exit_fee
        expected_gross_profit = margin_usd * leverage * tp_pct
        expected_net_profit = expected_gross_profit - total_fees

        # Dynamic profit target scaled to balance (accounts for 0.12% total fees)
        if usdt < 100:
            min_profit_dynamic = max(0.30, usdt * 0.005)  # $0.30 min for small accounts
        elif usdt < 500:
            min_profit_dynamic = max(0.75, usdt * 0.004)
        else:
            min_profit_dynamic = max(1.0, usdt * 0.005)

        if expected_net_profit < min_profit_dynamic:
            push_log(f"[{symbol}] REJECTED: Net profit ${expected_net_profit:.2f} < ${min_profit_dynamic:.2f} (dynamic min)")
            return

        # Ensure TP distance > 3× total fees
        fee_pct = KUCOIN_FEE_RATE * 2
        if tp_pct < fee_pct * 3:
            push_log(f"[{symbol}] REJECTED: TP ({tp_pct:.2%}) < 3× fees ({fee_pct*3:.2%})")
            return

        sl = round(price * (1 - sl_pct if side == 'buy' else 1 + sl_pct), 8)
        tp = round(price * (1 + tp_pct if side == 'buy' else 1 - tp_pct), 8)

        push_log(f"[{symbol}] {side.upper()} {contracts} contracts @ {price:.6f} | margin=${margin_usd:.2f} | SL:{sl_pct*100:.2f}% TP:{tp_pct*100:.2f}% Trail:{trailing_distance*100:.2f}%")

        order = client.create_order(symbol=symbol, order_type='market', side=side, amount=contracts)
        if order:
            push_log(f"[{symbol}] ORDER FILLED! ID:{order.get('id','?')}")
            push_log(f"[{symbol}] EXECUTED: Score={final_score:.2f} | Lev={leverage}x | ExpProfit=${expected_net_profit:.2f} | Mode={trading_mode}")
            risk_mgr.open_trade({
                'symbol': symbol, 'side': side, 'entry_price': price,
                'quantity': contracts, 'leverage': leverage,
                'stop_loss': sl, 'take_profit': tp, 'signal_strength': final_score,
                'trailing_distance': trailing_distance,
                'atr_pct': atr_pct,
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
    logger.info(f"AI Trader v7 on port {port} | TF:{TF} | Threshold:{SCORE_THRESHOLD}")
    socketio.run(app, host='0.0.0.0', port=port, debug=False, allow_unsafe_werkzeug=True)


if __name__ == '__main__':
    start()

"""
Market Scanner
Scans all KuCoin Futures pairs every cycle.
Scores each pair 0-10 based on signal quality.
Returns the best opportunity to trade right now.
"""
import time
import traceback
from typing import Dict, List, Optional
from datetime import datetime
import pandas as pd

from src.utils.logger import get_logger

logger = get_logger(__name__)

# All major KuCoin Futures pairs (USDT margined)
# Ordered by liquidity - most liquid first
WATCHLIST = [
    'XBTUSDTM',   # BTC
    'ETHUSDTM',   # ETH
    'SOLUSDTM',   # SOL
    'XRPUSDTM',   # XRP
    'DOGEUSDTM',  # DOGE
    'ADAUSDTM',   # ADA
    'AVAXUSDTM',  # AVAX
    'LINKUSDTM',  # LINK
    'BNBUSDTM',   # BNB
    'LTCUSDTM',   # LTC
    'DOTUSDTM',   # DOT
    'BCHUSDTM',   # BCH
    'UNIUSDTM',   # UNI
    'ATOMUSDTM',  # ATOM
    'NEARUSDTM',  # NEAR
    'MATICUSDTM', # MATIC
    'AAVEUSDTM',  # AAVE
    'FILUSDTM',   # FIL
    'TRXUSDTM',   # TRX
    'ETCUSDTM',   # ETC
]

# Contract sizes for each symbol
CONTRACT_SIZE = {
    'XBTUSDTM':   0.001,
    'ETHUSDTM':   0.01,
    'SOLUSDTM':   1.0,
    'XRPUSDTM':   10.0,
    'DOGEUSDTM':  100.0,
    'ADAUSDTM':   10.0,
    'AVAXUSDTM':  1.0,
    'LINKUSDTM':  1.0,
    'BNBUSDTM':   0.1,
    'LTCUSDTM':   0.1,
    'DOTUSDTM':   1.0,
    'BCHUSDTM':   0.1,
    'UNIUSDTM':   1.0,
    'ATOMUSDTM':  1.0,
    'NEARUSDTM':  1.0,
    'MATICUSDTM': 10.0,
    'AAVEUSDTM':  0.1,
    'FILUSDTM':   1.0,
    'TRXUSDTM':   100.0,
    'ETCUSDTM':   1.0,
    'SIRENUSDTM': 10.0,
}


class MarketScanner:
    """
    Scans all pairs and returns the best trading opportunities.
    Only recommends trades when confidence is HIGH (7+/10).
    """

    def __init__(self, client, strategy, intel, timeframe: str = '5m'):
        self.client    = client
        self.strategy  = strategy
        self.intel     = intel
        self.timeframe = timeframe

        self.last_scan:   Dict[str, Dict] = {}   # symbol -> last scan result
        self.scan_time:   Dict[str, float] = {}  # symbol -> last scan timestamp
        self.scan_interval = 60                  # Re-scan each pair every 60s
        self.btc_df: Optional[pd.DataFrame] = None
        self.btc_fetched_at: float = 0

    # ── BTC DATA (shared for correlation) ─────────────────────

    def _get_btc_df(self) -> Optional[pd.DataFrame]:
        """Get BTC data, cached for 60 seconds."""
        now = time.time()
        if now - self.btc_fetched_at > 60 or self.btc_df is None:
            df = self.client.fetch_ohlcv('XBTUSDTM', self.timeframe, limit=100)
            if df is not None and not df.empty:
                self.btc_df = df
                self.btc_fetched_at = now
        return self.btc_df

    # ── SINGLE PAIR SCAN ──────────────────────────────────────

    def scan_pair(self, symbol: str) -> Dict:
        """
        Scan a single pair and return a scored opportunity dict.
        Returns score 0-10, signal direction, and reasons.
        """
        try:
            # Fetch OHLCV
            df = self.client.fetch_ohlcv(symbol, self.timeframe, limit=100)
            if df is None or df.empty or len(df) < 30:
                return self._empty_result(symbol, 'No data')

            # Base strategy signal
            signal = self.strategy.analyze(df)

            if signal.get('signal', 'hold') == 'hold':
                return self._empty_result(symbol, f"Hold: {signal.get('reason','')[:50]}")

            # Intelligence layer
            btc_df = self._get_btc_df() if symbol != 'XBTUSDTM' else None
            signal = self.intel.get_trade_intelligence(
                symbol=symbol,
                signal=signal,
                btc_df=btc_df,
                alt_df=df
            )

            score    = signal.get('strength', 0)
            side     = signal.get('signal', 'hold')
            reason   = signal.get('reason', '')
            price    = float(df.iloc[-1]['close'])

            # Extra filters for confidence
            score = self._apply_quality_filters(df, score, side)

            result = {
                'symbol':    symbol,
                'score':     score,
                'side':      side,
                'price':     price,
                'reason':    reason,
                'df':        df,
                'signal':    signal,
                'timestamp': time.time(),
                'tradeable': score >= 7 and side in ('buy', 'sell'),
            }

            self.last_scan[symbol]  = result
            self.scan_time[symbol]  = time.time()

            if result['tradeable']:
                logger.info(f"[Scanner] {symbol} OPPORTUNITY: {side.upper()} score={score}/10 | {reason[:60]}")

            return result

        except Exception as e:
            logger.error(f"[Scanner] Error scanning {symbol}: {e}")
            return self._empty_result(symbol, f'Error: {str(e)[:40]}')

    # ── FULL MARKET SCAN ──────────────────────────────────────

    def scan_all(self, exclude_symbols: List[str] = None) -> List[Dict]:
        """
        Scan all watchlist pairs.
        Returns list of tradeable opportunities sorted by score (best first).
        Skips symbols already in an open position.
        """
        exclude = set(exclude_symbols or [])
        opportunities = []

        for symbol in WATCHLIST:
            if symbol in exclude:
                continue

            # Throttle: don't re-scan too frequently
            last_t = self.scan_time.get(symbol, 0)
            if time.time() - last_t < self.scan_interval:
                # Use cached result
                cached = self.last_scan.get(symbol)
                if cached and cached.get('tradeable'):
                    opportunities.append(cached)
                continue

            result = self.scan_pair(symbol)
            if result.get('tradeable'):
                opportunities.append(result)

            time.sleep(0.3)  # Avoid rate limit

        # Sort by score descending
        opportunities.sort(key=lambda x: x['score'], reverse=True)
        return opportunities

    def get_best_opportunity(self, exclude_symbols: List[str] = None) -> Optional[Dict]:
        """
        Get the single best trading opportunity right now.
        Returns None if no high-confidence setup found.
        """
        opps = self.scan_all(exclude_symbols=exclude_symbols)
        if opps:
            best = opps[0]
            logger.info(
                f"[Scanner] Best: {best['symbol']} {best['side'].upper()} "
                f"score={best['score']}/10"
            )
            return best
        logger.info("[Scanner] No high-confidence opportunities found this cycle")
        return None

    # ── QUALITY FILTERS ───────────────────────────────────────

    def _apply_quality_filters(self, df: pd.DataFrame, score: int, side: str) -> int:
        """
        Additional quality checks to boost/reduce score.
        Returns adjusted score.
        """
        try:
            latest  = df.iloc[-1]
            prev5   = df.iloc[-6] if len(df) >= 6 else df.iloc[0]

            # 1. Trend alignment: price moving in signal direction over last 5 candles
            price_change_5 = (latest['close'] - prev5['close']) / prev5['close'] * 100
            if side == 'buy' and price_change_5 > 0.1:
                score += 1  # Momentum confirms buy
            elif side == 'sell' and price_change_5 < -0.1:
                score += 1  # Momentum confirms sell
            elif side == 'buy' and price_change_5 < -0.5:
                score -= 1  # Fighting momentum
            elif side == 'sell' and price_change_5 > 0.5:
                score -= 1  # Fighting momentum

            # 2. Candle body strength (not a doji)
            body     = abs(latest['close'] - latest['open'])
            candle_range = latest['high'] - latest['low']
            if candle_range > 0:
                body_ratio = body / candle_range
                if body_ratio > 0.5:
                    score += 1  # Strong candle body
                elif body_ratio < 0.2:
                    score -= 1  # Doji / indecision

            # 3. Volume trend (is volume increasing?)
            if len(df) >= 10:
                recent_vol = df['volume'].tail(3).mean()
                avg_vol    = df['volume'].tail(20).mean()
                if recent_vol > avg_vol * 1.2:
                    score += 1  # Volume surge

            # 4. Not at extreme (avoid chasing tops/bottoms)
            if len(df) >= 20:
                high_20 = df['high'].tail(20).max()
                low_20  = df['low'].tail(20).min()
                price   = latest['close']
                pos_in_range = (price - low_20) / (high_20 - low_20) if high_20 != low_20 else 0.5
                if side == 'buy' and pos_in_range > 0.90:
                    score -= 2  # Buying at top of range
                elif side == 'sell' and pos_in_range < 0.10:
                    score -= 2  # Selling at bottom of range

            return max(0, min(10, score))

        except Exception as e:
            return score

    def _empty_result(self, symbol: str, reason: str) -> Dict:
        return {
            'symbol':    symbol,
            'score':     0,
            'side':      'hold',
            'price':     0,
            'reason':    reason,
            'df':        None,
            'signal':    {},
            'timestamp': time.time(),
            'tradeable': False,
        }

    def get_contract_size(self, symbol: str) -> float:
        return CONTRACT_SIZE.get(symbol, 1.0)

    def get_watchlist_status(self) -> List[Dict]:
        """Return current status of all scanned pairs for dashboard."""
        status = []
        for symbol in WATCHLIST:
            cached = self.last_scan.get(symbol)
            if cached:
                status.append({
                    'symbol': symbol,
                    'score':  cached.get('score', 0),
                    'side':   cached.get('side', 'hold'),
                    'tradeable': cached.get('tradeable', False),
                })
            else:
                status.append({'symbol': symbol, 'score': 0, 'side': 'hold', 'tradeable': False})
        return status

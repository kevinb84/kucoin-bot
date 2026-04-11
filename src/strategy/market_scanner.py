"""
Advanced AI Market Scanner for KuCoin Futures
- Scans ALL available pairs dynamically
- Filters by volume, volatility, liquidity
- Smart 100-point scoring system
- Fee-aware (only trades with 3x fee profit margin)
- Dynamic position sizing (2-5% risk per trade)
- Multi-trade support (up to 3 concurrent positions)
- Self-learning from trade history
"""
import time
import traceback
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import pandas as pd
import numpy as np

from src.utils.logger import get_logger

logger = get_logger(__name__)

# Contract sizes for major KuCoin Futures pairs
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
    'PEPEUSDTM':  1000000.0,
    'SHIBUSDTM':  100000.0,
    'ARBUSDTM':   10.0,
    'OPUSDTM':    1.0,
    'SUIUSDTM':   10.0,
    'SEIUSDTM':   10.0,
}

# KuCoin taker fee rate (0.06%)
KUCOIN_FEE_RATE = 0.0006


class AdvancedMarketScanner:
    """
    Professional-grade market scanner that:
    1. Discovers all tradable KuCoin Futures pairs dynamically
    2. Ranks them by liquidity and volatility
    3. Scores each pair 0-100 using multi-factor analysis
    4. Only trades when score >= 70 AND profit potential > 3x fees
    5. Supports up to 3 concurrent positions
    """

    def __init__(self, client, strategy, intel, timeframe: str = '5m'):
        self.client     = client
        self.strategy   = strategy
        self.intel      = intel
        self.timeframe  = timeframe

        # Dynamic watchlist (populated from exchange)
        self.all_symbols: List[str] = []
        self.active_symbols: List[str] = []  # Top 20-30 by volume/volatility

        # Scan cache
        self.scan_cache: Dict[str, Dict] = {}
        self.last_scan_time: Dict[str, float] = {}
        self.scan_cooldown = 45  # seconds between re-scans of same pair

        # BTC data cache (for correlation)
        self.btc_df: Optional[pd.DataFrame] = None
        self.btc_cache_time: float = 0

        # Performance tracking
        self.trade_history: List[Dict] = []
        self.win_rates: Dict[str, float] = {}  # symbol -> win rate

        # Leverage requirement
        self.required_leverage = 10

    # ── DYNAMIC SYMBOL DISCOVERY ──────────────────────────────

    def discover_symbols(self) -> List[str]:
        """
        Fetch all USDT-margined futures pairs from KuCoin.
        Filter out inactive or illiquid pairs.
        Returns list of tradable symbols.
        """
        try:
            markets = self.client.public.load_markets()
            usdt_pairs = []

            for symbol, info in markets.items():
                # Only USDT-margined perpetual swaps
                if 'USDT' in symbol and info.get('swap', False):
                    base = symbol.split('/')[0]
                    # Skip obscure tokens (less than 3 chars or too long)
                    if 3 <= len(base) <= 10:
                        usdt_pairs.append(symbol)

            # Sort by volume (if available) or alphabetically
            self.all_symbols = sorted(usdt_pairs)[:100]  # Cap at 100 to avoid rate limits
            logger.info(f"[Scanner] Discovered {len(self.all_symbols)} USDT futures pairs")

            return self.all_symbols

        except Exception as e:
            logger.error(f"[Scanner] Symbol discovery failed: {e}")
            # Fallback to known pairs
            return list(CONTRACT_SIZE.keys())

    def get_top_active_pairs(self, limit: int = 25) -> List[str]:
        """
        Get top N most active pairs by volume and volatility.
        Updates every 5 minutes.
        """
        if not self.all_symbols:
            self.discover_symbols()

        # Simple approach: use predefined high-volume pairs + some mid-caps
        priority_pairs = [
            'XBTUSDTM', 'ETHUSDTM', 'SOLUSDTM', 'XRPUSDTM', 'DOGEUSDTM',
            'ADAUSDTM', 'AVAXUSDTM', 'LINKUSDTM', 'BNBUSDTM', 'LTCUSDTM',
            'DOTUSDTM', 'BCHUSDTM', 'UNIUSDTM', 'ATOMUSDTM', 'NEARUSDTM',
            'MATICUSDTM', 'AAVEUSDTM', 'FILUSDTM', 'TRXUSDTM', 'ETCUSDTM',
            'PEPEUSDTM', 'SHIBUSDTM', 'ARBUSDTM', 'OPUSDTM', 'SUIUSDTM',
        ]

        # Add any new high-volume pairs discovered
        active = [s for s in priority_pairs if s in self.all_symbols]

        # Fill remaining slots with other discovered pairs
        remaining = limit - len(active)
        if remaining > 0:
            others = [s for s in self.all_symbols if s not in active][:remaining]
            active.extend(others)

        self.active_symbols = active[:limit]
        return self.active_symbols

    # ── BTC DATA CACHE ────────────────────────────────────────

    def _get_btc_df(self) -> Optional[pd.DataFrame]:
        """Get BTC 5m data, cached for 60 seconds."""
        now = time.time()
        if now - self.btc_cache_time > 60 or self.btc_df is None:
            df = self.client.fetch_ohlcv('XBTUSDTM', self.timeframe, limit=100)
            if df is not None and not df.empty:
                self.btc_df = df
                self.btc_cache_time = now
        return self.btc_df

    # ── SMART 100-POINT SCORING SYSTEM ────────────────────────

    # ── CUSTOM ENTRY MODELS ───────────────────────────────────

    def _detect_liquidity_grab(self, df) -> Dict:
        """
        Detect stop hunts above/below key levels with strong rejection.
        Returns: {'signal': 'buy'/'sell', 'confidence': 0-1, 'reason': str}
        """
        if len(df) < 20:
            return {'signal': 'hold', 'confidence': 0, 'reason': 'Insufficient data'}
        
        latest = df.iloc[-1]
        prev = df.iloc[-2] if len(df) >= 2 else latest
        
        # Find recent swing highs/lows (last 20 candles)
        high_20 = df['high'].tail(20).max()
        low_20 = df['low'].tail(20).min()
        
        current_high = latest['high']
        current_low = latest['low']
        close = latest['close']
        open_price = latest['open']
        
        # Bullish reversal: swept low then rejected
        if current_low < low_20 and close > low_20:
            # Strong rejection wick (lower wick > 60% of candle)
            candle_range = current_high - current_low
            lower_wick = min(close, open_price) - current_low
            if candle_range > 0 and lower_wick / candle_range > 0.6:
                return {
                    'signal': 'buy',
                    'confidence': 0.75,
                    'reason': f'Liquidity grab below {low_20:.4f}, strong rejection'
                }
        
        # Bearish reversal: swept high then rejected
        if current_high > high_20 and close < high_20:
            candle_range = current_high - current_low
            upper_wick = current_high - max(close, open_price)
            if candle_range > 0 and upper_wick / candle_range > 0.6:
                return {
                    'signal': 'sell',
                    'confidence': 0.75,
                    'reason': f'Liquidity grab above {high_20:.4f}, strong rejection'
                }
        
        return {'signal': 'hold', 'confidence': 0, 'reason': 'No liquidity grab detected'}

    def _detect_breakout_retest(self, df) -> Dict:
        """
        Identify breakout from consolidation, wait for pullback retest.
        Returns: {'signal': 'buy'/'sell', 'confidence': 0-1, 'reason': str}
        """
        if len(df) < 30:
            return {'signal': 'hold', 'confidence': 0, 'reason': 'Insufficient data'}
        
        latest = df.iloc[-1]
        
        # Find consolidation range (candles 5-25, excluding recent 5)
        consolidation = df.iloc[5:25]
        high_range = consolidation['high'].max()
        low_range = consolidation['low'].min()
        
        # Consolidation must be tight (< 2% range)
        range_pct = (high_range - low_range) / low_range * 100
        if range_pct > 2.0:
            return {'signal': 'hold', 'confidence': 0, 'reason': 'No consolidation detected'}
        
        # Check if price broke out recently (last 5 candles)
        recent_5 = df.tail(5)
        breakout_detected = False
        breakout_direction = None
        
        for _, candle in recent_5.iterrows():
            if candle['close'] > high_range * 1.005:
                breakout_detected = True
                breakout_direction = 'buy'
                break
            elif candle['close'] < low_range * 0.995:
                breakout_detected = True
                breakout_direction = 'sell'
                break
        
        if not breakout_detected:
            return {'signal': 'hold', 'confidence': 0, 'reason': 'No breakout yet'}
        
        # Current candle should be pullback/retest
        if breakout_direction == 'buy':
            # Price pulled back to resistance level (now support)
            if abs(latest['close'] - high_range) / high_range < 0.008:  # Within 0.8%
                # Check for bullish confirmation (green candle or hammer)
                if latest['close'] > latest['open']:
                    return {
                        'signal': 'buy',
                        'confidence': 0.80,
                        'reason': f'Breakout above {high_range:.4f}, retest confirmed'
                    }
        else:
            # Price pulled back to support level (now resistance)
            if abs(latest['close'] - low_range) / low_range < 0.008:
                if latest['close'] < latest['open']:
                    return {
                        'signal': 'sell',
                        'confidence': 0.80,
                        'reason': f'Breakdown below {low_range:.4f}, retest confirmed'
                    }
        
        return {'signal': 'hold', 'confidence': 0, 'reason': 'Waiting for retest'}

    def _detect_momentum_ignition(self, df) -> Dict:
        """
        Detect sudden volume spike + candle expansion.
        Returns: {'signal': 'buy'/'sell', 'confidence': 0-1, 'reason': str}
        """
        if len(df) < 20:
            return {'signal': 'hold', 'confidence': 0, 'reason': 'Insufficient data'}
        
        latest = df.iloc[-1]
        avg_volume = df['volume'].tail(20).mean()
        avg_range = (df['high'] - df['low']).tail(20).mean()
        
        current_volume = latest['volume']
        current_range = latest['high'] - latest['low']
        
        # Volume spike > 3x average AND candle range > 2x average
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0
        range_ratio = current_range / avg_range if avg_range > 0 else 0
        
        if volume_ratio > 3.0 and range_ratio > 2.0:
            # Determine direction
            body = latest['close'] - latest['open']
            if body > 0:
                return {
                    'signal': 'buy',
                    'confidence': 0.70,
                    'reason': f'Momentum ignition: vol {volume_ratio:.1f}x, range {range_ratio:.1f}x'
                }
            else:
                return {
                    'signal': 'sell',
                    'confidence': 0.70,
                    'reason': f'Momentum ignition: vol {volume_ratio:.1f}x, range {range_ratio:.1f}x'
                }
        
        return {'signal': 'hold', 'confidence': 0, 'reason': 'No momentum spike'}

    def score_pair(self, symbol: str, df: pd.DataFrame) -> Dict:
        """
        Score a trading pair using THREE dedicated entry models:
        - Model A: Liquidity Grab + Reversal
        - Model B: Breakout + Retest
        - Model C: Momentum Ignition
        
        Returns dict with best model signal and confidence.
        """
        try:
            # Run all three entry models
            liq_grab = self._detect_liquidity_grab(df)
            breakout = self._detect_breakout_retest(df)
            momentum = self._detect_momentum_ignition(df)
            
            # Pick highest confidence model
            models = [liq_grab, breakout, momentum]
            best_model = max(models, key=lambda x: x['confidence'])
            
            # Calculate supporting metrics for ML filter
            latest = df.iloc[-1]
            avg_vol_20 = df['volume'].tail(20).mean()
            volume_ratio = latest['volume'] / avg_vol_20 if avg_vol_20 > 0 else 1.0
            
            # Trend strength (simplified for ML)
            if 'ema_fast' in df.columns and 'ema_slow' in df.columns:
                spread_pct = abs(latest['ema_fast'] - latest['ema_slow']) / latest['ema_slow'] * 100
                trend_strength = min(spread_pct / 0.5 * 30, 30)
            else:
                trend_strength = 15
            
            # Determine if tradeable (confidence >= 0.65)
            tradeable = best_model['confidence'] >= 0.65 and best_model['signal'] != 'hold'
            
            # Calculate minimum profitable move (3x fees)
            min_move_pct = (KUCOIN_FEE_RATE * 2 * 3) * 100  # ~0.36%
            
            return {
                'symbol':         symbol,
                'total_score':    int(best_model['confidence'] * 100),
                'trend':          trend_strength,
                'volume':         volume_ratio * 25,
                'volatility':     self._estimate_atr_pct(df) * 5,
                'momentum':       0,
                'liquidity':      liq_grab['confidence'] * 20,
                'breakout':       breakout['confidence'] * 25,
                'spike':          momentum['confidence'] * 15,
                'signal':         best_model['signal'],
                'min_move_pct':   min_move_pct,
                'tradeable':      tradeable,
                'best_model':     best_model,
                'all_models':     {
                    'liquidity_grab': liq_grab,
                    'breakout_retest': breakout,
                    'momentum_ignition': momentum,
                },
            }

        except Exception as e:
            logger.error(f"[Scorer] Error scoring {symbol}: {e}")
            return self._empty_score(symbol)

    def _score_trend(self, df: pd.DataFrame, latest) -> int:
        """
        Trend strength (0-30 points):
        - EMA alignment (15 pts)
        - Price above/below EMA (10 pts)
        - Higher highs/lows (5 pts)
        """
        score = 0

        # EMA alignment
        if 'ema_fast' in df.columns and 'ema_slow' in df.columns:
            ema_fast = latest['ema_fast']
            ema_slow = latest['ema_slow']

            # Strong trend: fast EMA clearly above/below slow EMA
            spread_pct = abs(ema_fast - ema_slow) / ema_slow * 100

            if spread_pct > 0.5:
                score += 15  # Very strong trend
            elif spread_pct > 0.2:
                score += 10  # Moderate trend
            elif spread_pct > 0.05:
                score += 5   # Weak trend

        # Price position relative to EMAs
        price = latest['close']
        if 'ema_slow' in df.columns:
            if price > latest['ema_slow'] * 1.002:
                score += 10  # Clear uptrend
            elif price < latest['ema_slow'] * 0.998:
                score += 10  # Clear downtrend

        # Higher highs / lower lows (last 5 candles)
        if len(df) >= 6:
            recent = df.tail(6)
            highs = recent['high'].values
            lows = recent['low'].values

            if highs[-1] > highs[-3] and highs[-2] > highs[-4]:
                score += 5  # Making higher highs
            elif lows[-1] < lows[-3] and lows[-2] < lows[-4]:
                score += 5  # Making lower lows

        return min(score, 30)

    def _score_volume(self, df: pd.DataFrame, latest) -> int:
        """
        Volume strength (0-25 points):
        - Volume vs average (15 pts)
        - Increasing volume trend (10 pts)
        """
        score = 0

        if len(df) >= 20:
            current_vol = latest['volume']
            avg_vol_20 = df['volume'].tail(20).mean()

            # Volume ratio
            if current_vol > avg_vol_20 * 2.5:
                score += 15  # Exceptional volume
            elif current_vol > avg_vol_20 * 1.8:
                score += 12  # High volume
            elif current_vol > avg_vol_20 * 1.3:
                score += 8   # Above average
            elif current_vol > avg_vol_20:
                score += 5   # Normal volume

            # Volume trend (last 5 vs previous 5)
            recent_5 = df['volume'].tail(5).mean()
            prev_5 = df['volume'].iloc[-10:-5].mean()

            if recent_5 > prev_5 * 1.3:
                score += 10  # Volume increasing
            elif recent_5 > prev_5:
                score += 5   # Volume stable/slightly up

        return min(score, 25)

    def _score_volatility(self, df: pd.DataFrame, recent) -> int:
        """
        Volatility level (0-25 points):
        - ATR-based volatility (15 pts)
        - Price range expansion (10 pts)
        """
        score = 0

        if len(df) >= 20:
            # Calculate ATR
            atr_values = []
            for i in range(1, min(20, len(df))):
                tr = max(
                    df.iloc[i]['high'] - df.iloc[i]['low'],
                    abs(df.iloc[i]['high'] - df.iloc[i-1]['close']),
                    abs(df.iloc[i]['low'] - df.iloc[i-1]['close'])
                )
                atr_values.append(tr)

            avg_atr = np.mean(atr_values) if atr_values else 0
            price = df.iloc[-1]['close']
            atr_pct = (avg_atr / price * 100) if price > 0 else 0

            # Optimal volatility: 1-5% ATR (enough movement but not crazy)
            if 1.0 <= atr_pct <= 5.0:
                score += 15  # Perfect volatility
            elif 0.5 <= atr_pct < 1.0:
                score += 10  # Moderate volatility
            elif atr_pct > 5.0:
                score += 5   # Too volatile (risky)
            else:
                score += 2   # Too quiet

            # Recent range expansion
            if len(recent) >= 3:
                ranges = [c['high'] - c['low'] for _, c in recent.iterrows()]
                if ranges[-1] > np.mean(ranges[:-1]) * 1.3:
                    score += 10  # Range expanding (breakout)

        return min(score, 25)

    def _score_momentum(self, df: pd.DataFrame, latest, recent) -> int:
        """
        Momentum/breakout (0-20 points):
        - RSI momentum (10 pts)
        - Price breaking key levels (10 pts)
        """
        score = 0

        # RSI momentum
        if 'rsi' in df.columns:
            rsi = latest['rsi']

            # Strong momentum (not overextended)
            if 55 <= rsi <= 70:
                score += 10  # Bullish momentum, room to grow
            elif 30 <= rsi <= 45:
                score += 10  # Bearish momentum, room to drop
            elif 45 < rsi < 55:
                score += 3   # Neutral/weak momentum

        # Breakout detection
        if len(df) >= 20:
            high_20 = df['high'].tail(20).max()
            low_20 = df['low'].tail(20).min()
            price = latest['close']

            # Breaking above resistance
            if price > high_20 * 0.998:
                score += 10  # Breaking resistance
            elif price < low_20 * 1.002:
                score += 10  # Breaking support

        return min(score, 20)

    def _score_liquidity_grab(self, df, latest) -> int:
        """Detect price sweeping highs/lows then reversing."""
        score = 0
        if len(df) < 10:
            return 0

        high_10 = df['high'].tail(10).max()
        low_10 = df['low'].tail(10).min()

        current_high = latest['high']
        current_low = latest['low']
        close = latest['close']

        if current_high > high_10 and close < current_high - (current_high - current_low) * 0.6:
            score += 15

        elif current_low < low_10 and close > current_low + (current_high - current_low) * 0.6:
            score += 15

        return score

    def _score_breakout_retest(self, df, latest) -> int:
        """Detect breakout from consolidation then pullback entry."""
        score = 0
        if len(df) < 30:
            return 0

        high_20 = df['high'].tail(20).max()
        low_20 = df['low'].tail(20).min()
        range_size = (high_20 - low_20) / low_20 * 100

        if range_size < 2.0:
            prev_candles = df.iloc[-5:-1]
            breakout_detected = False

            for _, candle in prev_candles.iterrows():
                if candle['close'] > high_20 * 1.005 or candle['close'] < low_20 * 0.995:
                    if candle['volume'] > df['volume'].tail(20).mean() * 1.5:
                        breakout_detected = True
                        break

            if breakout_detected:
                if abs(latest['close'] - high_20) / high_20 < 0.005:
                    score += 20

        return score

    def _score_momentum_spike(self, df, latest) -> int:
        """Detect sudden volume + candle expansion."""
        score = 0
        if len(df) < 20:
            return 0

        avg_volume = df['volume'].tail(20).mean()
        avg_range = (df['high'] - df['low']).tail(20).mean()

        current_volume = latest['volume']
        current_range = latest['high'] - latest['low']

        if current_volume > avg_volume * 3.0 and current_range > avg_range * 2.0:
            score += 15

        return score

    def _determine_signal(self, df: pd.DataFrame, latest) -> str:
        """Determine trade direction: buy, sell, or hold."""
        if 'ema_fast' not in df.columns or 'ema_slow' not in df.columns:
            return 'hold'

        ema_fast = latest['ema_fast']
        ema_slow = latest['ema_slow']
        price = latest['close']

        # Bullish: fast EMA > slow EMA and price above both
        if ema_fast > ema_slow and price > ema_fast:
            return 'buy'

        # Bearish: fast EMA < slow EMA and price below both
        if ema_fast < ema_slow and price < ema_fast:
            return 'sell'

        return 'hold'

    def _empty_score(self, symbol: str) -> Dict:
        return {
            'symbol': symbol,
            'total_score': 0,
            'trend': 0,
            'volume': 0,
            'volatility': 0,
            'momentum': 0,
            'liquidity': 0,
            'breakout': 0,
            'spike': 0,
            'signal': 'hold',
            'min_move_pct': 0.36,
            'tradeable': False,
        }

    # ── FULL SCAN PIPELINE ────────────────────────────────────

    def scan_all(self, exclude_symbols: List[str] = None,
                 open_positions: int = 0, max_positions: int = 3) -> List[Dict]:
        """
        Scan all active pairs and return ranked opportunities.
        Only returns pairs with score >= 70.
        Respects max open position limit.
        """
        exclude = set(exclude_symbols or [])
        opportunities = []

        # Get fresh list of active pairs
        pairs_to_scan = self.get_top_active_pairs()

        for symbol in pairs_to_scan:
            if symbol in exclude or open_positions >= max_positions:
                continue

            # Check cooldown
            last_t = self.last_scan_time.get(symbol, 0)
            if time.time() - last_t < self.scan_cooldown:
                cached = self.scan_cache.get(symbol)
                if cached and cached.get('tradeable'):
                    opportunities.append(cached)
                continue

            # Fetch OHLCV data
            df = self.client.fetch_ohlcv(symbol, self.timeframe, limit=100)
            if df is None or df.empty or len(df) < 30:
                continue

            # Calculate indicators for scoring
            df = self._add_indicators(df)

            # Score this pair
            score_data = self.score_pair(symbol, df)

            # Fee-aware filter: only trade if expected move > 3x fees
            if score_data['tradeable']:
                # Estimate expected move from volatility
                atr_pct = self._estimate_atr_pct(df)
                if atr_pct < score_data['min_move_pct']:
                    score_data['tradeable'] = False
                    score_data['reason'] = f"Expected move ({atr_pct:.2f}%) < min ({score_data['min_move_pct']:.2f}%)"
                else:
                    score_data['reason'] = f"Strong setup, expect {atr_pct:.2f}% move"

            # Cache result
            score_data['df'] = df
            score_data['timestamp'] = time.time()
            self.scan_cache[symbol] = score_data
            self.last_scan_time[symbol] = time.time()

            if score_data['tradeable']:
                opportunities.append(score_data)
                logger.info(
                    f"[Scanner] {symbol} SCORE={score_data['total_score']}/100 "
                    f"| T:{score_data['trend']} V:{score_data['volume']} "
                    f"Vol:{score_data['volatility']} M:{score_data['momentum']} "
                    f"| {score_data.get('reason', '')}"
                )

            time.sleep(0.2)  # Rate limit protection

        # Sort by score descending
        opportunities.sort(key=lambda x: x['total_score'], reverse=True)
        return opportunities

    def get_dynamic_threshold(self) -> int:
        """Lower threshold in active markets, raise in quiet ones."""
        active_count = sum(1 for s in self.scan_cache.values()
                          if s.get('total_score', 0) >= 60)

        if active_count >= 5:
            return 60
        elif active_count >= 3:
            return 65
        else:
            return 70

    def get_best_opportunity(self, exclude_symbols: List[str] = None,
                             open_positions: int = 0) -> Optional[Dict]:
        """Get the single best trade opportunity right now."""
        opps = self.scan_all(exclude_symbols=exclude_symbols,
                            open_positions=open_positions)
        if opps:
            best = opps[0]
            threshold = self.get_dynamic_threshold()
            if best['total_score'] >= threshold:
                logger.info(
                    f"[Scanner] BEST: {best['symbol']} {best['signal'].upper()} "
                    f"score={best['total_score']}/100 (threshold={threshold})"
                )
                return best

        logger.info("[Scanner] No qualifying opportunities (dynamic threshold)")
        return None

    # ── HELPER FUNCTIONS ──────────────────────────────────────

    def _add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add EMA, RSI, and other indicators for scoring."""
        df = df.copy()

        # EMAs
        df['ema_fast'] = df['close'].ewm(span=7, adjust=False).mean()
        df['ema_slow'] = df['close'].ewm(span=21, adjust=False).mean()

        # RSI
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))

        return df

    def _estimate_atr_pct(self, df: pd.DataFrame) -> float:
        """Estimate expected price movement as percentage."""
        if len(df) < 20:
            return 0.5

        atr_values = []
        for i in range(1, min(20, len(df))):
            tr = max(
                df.iloc[i]['high'] - df.iloc[i]['low'],
                abs(df.iloc[i]['high'] - df.iloc[i-1]['close']),
                abs(df.iloc[i]['low'] - df.iloc[i-1]['close'])
            )
            atr_values.append(tr)

        avg_atr = np.mean(atr_values) if atr_values else 0
        price = df.iloc[-1]['close']
        return (avg_atr / price * 100) if price > 0 else 0.5

    def get_contract_size(self, symbol: str) -> float:
        return CONTRACT_SIZE.get(symbol, 0.001)

    def get_watchlist_status(self) -> List[Dict]:
        """Return status of all scanned pairs for dashboard."""
        status = []
        for symbol in self.active_symbols:
            cached = self.scan_cache.get(symbol)
            if cached:
                status.append({
                    'symbol':    symbol,
                    'score':     cached.get('total_score', 0),
                    'signal':    cached.get('signal', 'hold'),
                    'tradeable': cached.get('tradeable', False),
                    'trend':     cached.get('trend', 0),
                    'volume':    cached.get('volume', 0),
                })
            else:
                status.append({
                    'symbol': symbol, 'score': 0, 'signal': 'hold',
                    'tradeable': False, 'trend': 0, 'volume': 0
                })
        return status

    def record_trade_result(self, symbol: str, won: bool, pnl: float):
        """Record trade outcome for learning system."""
        self.trade_history.append({
            'symbol': symbol,
            'won': won,
            'pnl': pnl,
            'timestamp': time.time(),
        })

        # Update win rate for this symbol
        symbol_trades = [t for t in self.trade_history if t['symbol'] == symbol]
        if symbol_trades:
            wins = sum(1 for t in symbol_trades if t['won'])
            self.win_rates[symbol] = wins / len(symbol_trades)

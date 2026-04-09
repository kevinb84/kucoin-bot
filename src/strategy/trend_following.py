import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from src.utils.logger import get_logger

logger = get_logger(__name__)

class TrendFollowingStrategy:
    """
    Enhanced trend-following strategy for 5-minute scalping.
    Combines EMA crossovers, RSI, volume analysis, and multi-timeframe confirmation.
    Supports both trend following and mean reversion modes.
    """
    
    def __init__(self, config: Dict):
        self.config = config
        
        # EMA parameters (optimized for scalping)
        self.ema_fast = config.get('ema_fast', 9)
        self.ema_slow = config.get('ema_slow', 21)
        self.ema_signal_threshold = config.get('ema_signal_threshold', 0.3)
        
        # RSI parameters
        self.rsi_period = config.get('rsi_period', 14)
        self.rsi_overbought = config.get('rsi_overbought', 65)
        self.rsi_oversold = config.get('rsi_oversold', 35)
        self.rsi_extreme_overbought = config.get('rsi_extreme_overbought', 80)
        self.rsi_extreme_oversold = config.get('rsi_extreme_oversold', 20)
        
        # Volume parameters
        self.volume_threshold = config.get('volume_threshold', 1.5)
        self.volume_period = config.get('volume_period', 20)
        
        # Multi-timeframe
        self.multi_timeframe_enabled = config.get('multi_timeframe_enabled', True)
        self.higher_timeframe_1 = config.get('higher_timeframe_1', '15m')
        self.higher_timeframe_2 = config.get('higher_timeframe_2', '1h')
        
        # Strategy modes
        self.trend_following_enabled = config.get('trend_following_enabled', True)
        self.mean_reversion_enabled = config.get('mean_reversion_enabled', True)
        
        # Signal settings
        self.min_signal_strength = config.get('min_signal_strength', 6)
        self.confirm_with_higher_tf = config.get('confirm_with_higher_tf', True)
        
        # Market regime
        self.regime_detection = config.get('regime_detection', True)
        self.trend_strength_threshold = config.get('trend_strength_threshold', 0.6)
        
        # State
        self.last_signal = "hold"
        self.last_strength = 0
        self.market_regime = "unknown"  # trending, ranging, volatile
        
    def analyze(self, df: pd.DataFrame, higher_tf_data: Dict = None) -> Dict:
        """
        Analyze market and generate trading signal.
        
        Args:
            df: DataFrame with OHLCV data (5-minute candles)
            higher_tf_data: Optional dict with higher timeframe data
        
        Returns:
            Dict with signal, strength, and reasoning
        """
        if len(df) < max(self.ema_slow, self.rsi_period) + 10:
            return {
                'signal': 'hold',
                'strength': 0,
                'reason': 'Insufficient data'
            }
        
        # Calculate indicators
        df = self._calculate_indicators(df)
        
        # Detect market regime
        if self.regime_detection:
            self.market_regime = self._detect_market_regime(df)
        
        # Generate signals
        trend_signal = self._generate_trend_signal(df) if self.trend_following_enabled else None
        mean_rev_signal = self._generate_mean_reversion_signal(df) if self.mean_reversion_enabled else None
        
        # Combine signals
        if trend_signal and mean_rev_signal:
            # Use the signal with higher strength
            if trend_signal['strength'] >= mean_rev_signal['strength']:
                final_signal = trend_signal
            else:
                final_signal = mean_rev_signal
        elif trend_signal:
            final_signal = trend_signal
        elif mean_rev_signal:
            final_signal = mean_rev_signal
        else:
            final_signal = {'signal': 'hold', 'strength': 0, 'reason': 'No clear signal'}
        
        # Multi-timeframe confirmation
        if self.multi_timeframe_enabled and self.confirm_with_higher_tf and higher_tf_data:
            final_signal = self._apply_multi_timeframe_filter(final_signal, higher_tf_data)
        
        # Volume confirmation
        volume_confirmed = self._confirm_with_volume(df)
        if volume_confirmed:
            final_signal['strength'] = min(final_signal['strength'] + 1, 10)
            final_signal['reason'] += ' [Volume confirmed]'
        
        # Check minimum strength
        if final_signal['strength'] < self.min_signal_strength:
            final_signal['signal'] = 'hold'
            final_signal['reason'] += f' [Below min strength {self.min_signal_strength}]'
        
        # Update state
        self.last_signal = final_signal['signal']
        self.last_strength = final_signal['strength']
        
        return final_signal
    
    def _calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate all technical indicators."""
        df = df.copy()
        
        # EMAs
        df['ema_fast'] = df['close'].ewm(span=self.ema_fast, adjust=False).mean()
        df['ema_slow'] = df['close'].ewm(span=self.ema_slow, adjust=False).mean()
        
        # RSI
        df['rsi'] = self._calculate_rsi(df['close'], self.rsi_period)
        
        # MACD
        ema12 = df['close'].ewm(span=12, adjust=False).mean()
        ema26 = df['close'].ewm(span=26, adjust=False).mean()
        df['macd'] = ema12 - ema26
        df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
        df['macd_hist'] = df['macd'] - df['macd_signal']
        
        # Bollinger Bands
        sma20 = df['close'].rolling(window=20).mean()
        std20 = df['close'].rolling(window=20).std()
        df['bb_upper'] = sma20 + (std20 * 2)
        df['bb_lower'] = sma20 - (std20 * 2)
        df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / sma20
        
        # Volume SMA
        df['volume_sma'] = df['volume'].rolling(window=self.volume_period).mean()
        df['volume_ratio'] = df['volume'] / df['volume_sma']
        
        # ATR (for volatility)
        df['atr'] = self._calculate_atr(df, period=14)
        
        return df
    
    def _calculate_rsi(self, prices: pd.Series, period: int) -> pd.Series:
        """Calculate RSI."""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    def _calculate_atr(self, df: pd.DataFrame, period: int) -> pd.Series:
        """Calculate Average True Range."""
        high = df['high']
        low = df['low']
        close = df['close']
        
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        
        atr = tr.rolling(window=period).mean()
        return atr
    
    def _generate_trend_signal(self, df: pd.DataFrame) -> Dict:
        """Generate trend-following signal based on EMA crossover."""
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        signal = 'hold'
        strength = 0
        reason = ''
        
        # EMA crossover
        ema_fast_curr = latest['ema_fast']
        ema_slow_curr = latest['ema_slow']
        ema_fast_prev = prev['ema_fast']
        ema_slow_prev = prev['ema_slow']
        
        # Bullish crossover
        if ema_fast_prev <= ema_slow_prev and ema_fast_curr > ema_slow_curr:
            signal = 'buy'
            strength = 7
            reason = f'Bullish EMA crossover ({self.ema_fast}/{self.ema_slow})'
        
        # Bearish crossover
        elif ema_fast_prev >= ema_slow_prev and ema_fast_curr < ema_slow_curr:
            signal = 'sell'
            strength = 7
            reason = f'Bearish EMA crossover ({self.ema_fast}/{self.ema_slow})'
        
        # Trend continuation (already in trend)
        elif ema_fast_curr > ema_slow_curr:
            # Uptrend
            pullback = (ema_fast_curr - ema_slow_curr) / ema_slow_curr * 100
            if pullback < self.ema_signal_threshold:
                signal = 'buy'
                strength = 5
                reason = f'Uptrend pullback (diff: {pullback:.2f}%)'
        
        elif ema_fast_curr < ema_slow_curr:
            # Downtrend
            bounce = (ema_slow_curr - ema_fast_curr) / ema_slow_curr * 100
            if bounce < self.ema_signal_threshold:
                signal = 'sell'
                strength = 5
                reason = f'Downtrend bounce (diff: {bounce:.2f}%)'
        
        # Adjust strength based on RSI
        rsi = latest['rsi']
        if signal == 'buy':
            if rsi < self.rsi_oversold:
                strength += 2
                reason += f', RSI oversold ({rsi:.1f})'
            elif rsi > self.rsi_overbought:
                strength -= 3
                reason += f', RSI overbought ({rsi:.1f})'
        
        elif signal == 'sell':
            if rsi > self.rsi_overbought:
                strength += 2
                reason += f', RSI overbought ({rsi:.1f})'
            elif rsi < self.rsi_oversold:
                strength -= 3
                reason += f', RSI oversold ({rsi:.1f})'
        
        # MACD confirmation
        macd_hist = latest['macd_hist']
        macd_hist_prev = prev['macd_hist']
        
        if signal == 'buy' and macd_hist > macd_hist_prev:
            strength += 1
            reason += ', MACD bullish'
        elif signal == 'sell' and macd_hist < macd_hist_prev:
            strength += 1
            reason += ', MACD bearish'
        
        strength = max(0, min(strength, 10))
        
        return {
            'signal': signal,
            'strength': strength,
            'reason': reason
        }
    
    def _generate_mean_reversion_signal(self, df: pd.DataFrame) -> Dict:
        """Generate mean reversion signal based on RSI extremes and Bollinger Bands."""
        latest = df.iloc[-1]
        
        signal = 'hold'
        strength = 0
        reason = ''
        
        rsi = latest['rsi']
        price = latest['close']
        bb_upper = latest['bb_upper']
        bb_lower = latest['bb_lower']
        
        # Oversold + below lower BB = buy signal
        if rsi < self.rsi_extreme_oversold and price < bb_lower:
            signal = 'buy'
            strength = 6
            reason = f'Mean reversion: RSI extremely oversold ({rsi:.1f}), price below BB lower'
        
        # Overbought + above upper BB = sell signal
        elif rsi > self.rsi_extreme_overbought and price > bb_upper:
            signal = 'sell'
            strength = 6
            reason = f'Mean reversion: RSI extremely overbought ({rsi:.1f}), price above BB upper'
        
        # Adjust based on distance from bands
        if signal != 'hold':
            bb_range = bb_upper - bb_lower
            if signal == 'buy':
                distance_from_lower = (price - bb_lower) / bb_range * 100
                if distance_from_lower < -5:  # Well below lower band
                    strength += 2
            elif signal == 'sell':
                distance_from_upper = (bb_upper - price) / bb_range * 100
                if distance_from_upper < -5:  # Well above upper band
                    strength += 2
        
        strength = max(0, min(strength, 10))
        
        return {
            'signal': signal,
            'strength': strength,
            'reason': reason
        }
    
    def _detect_market_regime(self, df: pd.DataFrame) -> str:
        """Detect current market regime: trending, ranging, or volatile."""
        latest = df.iloc[-1]
        
        # Use Bollinger Band width as volatility indicator
        bb_width = latest['bb_width']
        bb_width_avg = df['bb_width'].rolling(window=50).mean().iloc[-1]
        
        # Use ADX-like metric (simplified)
        ema_fast = latest['ema_fast']
        ema_slow = latest['ema_slow']
        trend_strength = abs(ema_fast - ema_slow) / ema_slow
        
        if bb_width > bb_width_avg * 1.5:
            return 'volatile'
        elif trend_strength > self.trend_strength_threshold:
            return 'trending'
        else:
            return 'ranging'
    
    def _confirm_with_volume(self, df: pd.DataFrame) -> bool:
        """Confirm signal with volume analysis."""
        latest = df.iloc[-1]
        volume_ratio = latest['volume_ratio']
        
        return volume_ratio >= self.volume_threshold
    
    def _apply_multi_timeframe_filter(self, signal: Dict, higher_tf_data: Dict) -> Dict:
        """
        Apply multi-timeframe confirmation.
        
        Args:
            signal: Current signal
            higher_tf_data: Dict with '15m' and '1h' data
        
        Returns:
            Adjusted signal
        """
        if not higher_tf_data:
            return signal
        
        # Check 15m trend
        tf_15m = higher_tf_data.get('15m')
        if tf_15m is not None and len(tf_15m) > 0:
            tf_15m_trend = self._get_trend_direction(tf_15m)
            
            # If signal aligns with higher timeframe trend, boost strength
            if signal['signal'] == 'buy' and tf_15m_trend == 'up':
                signal['strength'] = min(signal['strength'] + 2, 10)
                signal['reason'] += ', 15m trend confirms'
            elif signal['signal'] == 'sell' and tf_15m_trend == 'down':
                signal['strength'] = min(signal['strength'] + 2, 10)
                signal['reason'] += ', 15m trend confirms'
            elif signal['signal'] in ['buy', 'sell']:
                # Opposite to higher timeframe - reduce strength
                signal['strength'] = max(signal['strength'] - 3, 0)
                signal['reason'] += ', 15m trend opposes'
        
        # Check 1h trend (stronger filter)
        tf_1h = higher_tf_data.get('1h')
        if tf_1h is not None and len(tf_1h) > 0:
            tf_1h_trend = self._get_trend_direction(tf_1h)
            
            if signal['signal'] == 'buy' and tf_1h_trend == 'up':
                signal['strength'] = min(signal['strength'] + 3, 10)
                signal['reason'] += ', 1h trend confirms'
            elif signal['signal'] == 'sell' and tf_1h_trend == 'down':
                signal['strength'] = min(signal['strength'] + 3, 10)
                signal['reason'] += ', 1h trend confirms'
            elif signal['signal'] in ['buy', 'sell']:
                signal['strength'] = max(signal['strength'] - 4, 0)
                signal['reason'] += ', 1h trend opposes'
        
        return signal
    
    def _get_trend_direction(self, df: pd.DataFrame) -> str:
        """Determine trend direction from EMA alignment."""
        if len(df) < 2:
            return 'unknown'
        
        latest = df.iloc[-1]
        
        # Simple: check if fast EMA > slow EMA
        if 'ema_fast' in df.columns and 'ema_slow' in df.columns:
            if latest['ema_fast'] > latest['ema_slow']:
                return 'up'
            else:
                return 'down'
        
        # Fallback: check price momentum
        if len(df) >= 10:
            momentum = (latest['close'] - df.iloc[-10]['close']) / df.iloc[-10]['close']
            if momentum > 0.005:
                return 'up'
            elif momentum < -0.005:
                return 'down'
        
        return 'neutral'
    
    def get_market_regime(self) -> str:
        """Get current market regime."""
        return self.market_regime
    
    def get_last_signal(self) -> Dict:
        """Get last generated signal."""
        return {
            'signal': self.last_signal,
            'strength': self.last_strength
        }

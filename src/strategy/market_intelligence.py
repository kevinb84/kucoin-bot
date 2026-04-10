"""
Market Intelligence Module
Adds IQ to the trading bot:
- Order book depth analysis (bid/ask walls)
- Funding rate awareness (avoid costly funding)
- BTC-altcoin correlation (SIREN follows BTC)
- Flash crash / black swan detection
- Volatility regime detection
"""
import time
import traceback
from typing import Dict, Optional, Tuple
from datetime import datetime
import numpy as np
import pandas as pd


class MarketIntelligence:
    """
    Smart market analysis layer that sits on top of technical analysis.
    Provides additional signals and filters to improve trade quality.
    """

    def __init__(self, client):
        """
        Args:
            client: KuCoinClient instance for fetching market data
        """
        self.client = client
        self.btc_prices = []        # Rolling BTC price history
        self.siren_prices = []      # Rolling SIREN price history
        self.funding_cache = {}     # symbol -> {rate, next_time}
        self.last_orderbook = {}    # symbol -> orderbook data
        self.flash_crash_cooldown = 0  # Seconds until we trade again after crash
        
    # ── ORDER BOOK ANALYSIS ───────────────────────────────────
    
    def analyze_orderbook(self, symbol: str) -> Dict:
        """
        Analyze order book depth to detect buy/sell walls.
        Returns bias: 'bullish', 'bearish', or 'neutral'
        """
        try:
            from src.api.kucoin_client import to_ccxt_symbol
            ccxt_symbol = to_ccxt_symbol(symbol)
            orderbook = self.client.public.fetch_order_book(ccxt_symbol, limit=20)
            
            if not orderbook:
                return {'bias': 'neutral', 'strength': 0, 'reason': 'No orderbook data'}
            
            bids = orderbook.get('bids', [])
            asks = orderbook.get('asks', [])
            
            if not bids or not asks:
                return {'bias': 'neutral', 'strength': 0, 'reason': 'Empty orderbook'}
            
            # Sum up bid/ask volume (top 20 levels)
            bid_volume = sum(b[1] for b in bids[:20])
            ask_volume = sum(a[1] for a in asks[:20])
            
            total = bid_volume + ask_volume
            if total == 0:
                return {'bias': 'neutral', 'strength': 0, 'reason': 'Zero volume'}
            
            bid_pct = bid_volume / total
            ask_pct = ask_volume / total
            
            # Detect walls (large orders > 3x average)
            avg_bid = bid_volume / len(bids[:20]) if bids else 0
            avg_ask = ask_volume / len(asks[:20]) if asks else 0
            
            bid_walls = sum(1 for b in bids[:20] if b[1] > avg_bid * 3)
            ask_walls = sum(1 for a in asks[:20] if a[1] > avg_ask * 3)
            
            # Spread analysis
            best_bid = bids[0][0]
            best_ask = asks[0][0]
            spread_pct = (best_ask - best_bid) / best_bid * 100
            
            # Determine bias
            if bid_pct > 0.60:
                bias = 'bullish'
                strength = min(int((bid_pct - 0.5) * 20), 5)
                reason = f'Strong bid support ({bid_pct:.0%} bids, {bid_walls} walls)'
            elif ask_pct > 0.60:
                bias = 'bearish'
                strength = min(int((ask_pct - 0.5) * 20), 5)
                reason = f'Heavy sell pressure ({ask_pct:.0%} asks, {ask_walls} walls)'
            else:
                bias = 'neutral'
                strength = 0
                reason = f'Balanced book ({bid_pct:.0%}/{ask_pct:.0%})'
            
            # Wide spread = low liquidity = dangerous
            if spread_pct > 0.1:
                reason += f', WIDE spread ({spread_pct:.3f}%)'
                strength = max(strength - 1, 0)
            
            self.last_orderbook[symbol] = {
                'bid_volume': bid_volume,
                'ask_volume': ask_volume,
                'bid_pct': bid_pct,
                'spread_pct': spread_pct,
                'bias': bias,
                'timestamp': time.time()
            }
            
            return {'bias': bias, 'strength': strength, 'reason': reason, 'spread_pct': spread_pct}
            
        except Exception as e:
            print(f"[Intelligence] Orderbook error {symbol}: {e}")
            return {'bias': 'neutral', 'strength': 0, 'reason': f'Error: {str(e)[:50]}'}
    
    # ── FUNDING RATE ──────────────────────────────────────────
    
    def check_funding_rate(self, symbol: str) -> Dict:
        """
        Check funding rate for the symbol.
        High funding = costly to hold positions.
        SIREN has 1h funding intervals = very costly.
        
        Returns: {'rate': float, 'expensive': bool, 'direction': str}
        """
        try:
            from src.api.kucoin_client import to_ccxt_symbol
            ccxt_symbol = to_ccxt_symbol(symbol)
            
            # Fetch funding rate
            funding = self.client.public.fetch_funding_rate(ccxt_symbol)
            
            if not funding:
                return {'rate': 0, 'expensive': False, 'direction': 'neutral'}
            
            rate = float(funding.get('fundingRate', 0) or 0)
            
            # SIREN has 1h funding = 24x per day (very expensive)
            is_siren = 'SIREN' in symbol
            threshold = 0.0005 if is_siren else 0.001  # Stricter for SIREN
            
            expensive = abs(rate) > threshold
            
            # Positive rate = longs pay shorts (bearish pressure)
            # Negative rate = shorts pay longs (bullish pressure)
            if rate > threshold:
                direction = 'bearish'  # Expensive to be long
            elif rate < -threshold:
                direction = 'bullish'  # Expensive to be short
            else:
                direction = 'neutral'
            
            self.funding_cache[symbol] = {
                'rate': rate,
                'expensive': expensive,
                'direction': direction,
                'timestamp': time.time()
            }
            
            return {
                'rate': rate,
                'rate_pct': rate * 100,
                'expensive': expensive,
                'direction': direction,
                'is_siren': is_siren,
                'reason': f"Funding: {rate*100:.4f}% ({'1h' if is_siren else '8h'})"
            }
            
        except Exception as e:
            print(f"[Intelligence] Funding rate error {symbol}: {e}")
            return {'rate': 0, 'expensive': False, 'direction': 'neutral'}
    
    # ── BTC-ALTCOIN CORRELATION ───────────────────────────────
    
    def check_btc_correlation(self, btc_df: pd.DataFrame, alt_df: pd.DataFrame) -> Dict:
        """
        Check correlation between BTC and altcoin (e.g., SIREN).
        If BTC dumps, SIREN likely dumps harder.
        
        Returns: {'correlation': float, 'btc_trend': str, 'warning': str}
        """
        try:
            if btc_df is None or alt_df is None:
                return {'correlation': 0, 'btc_trend': 'unknown', 'warning': ''}
            
            if len(btc_df) < 20 or len(alt_df) < 20:
                return {'correlation': 0, 'btc_trend': 'unknown', 'warning': 'Insufficient data'}
            
            # Calculate returns
            btc_returns = btc_df['close'].pct_change().dropna().tail(20)
            alt_returns = alt_df['close'].pct_change().dropna().tail(20)
            
            # Align lengths
            min_len = min(len(btc_returns), len(alt_returns))
            btc_returns = btc_returns.tail(min_len).values
            alt_returns = alt_returns.tail(min_len).values
            
            # Correlation
            if len(btc_returns) > 5:
                correlation = float(np.corrcoef(btc_returns, alt_returns)[0, 1])
            else:
                correlation = 0
            
            # BTC short-term trend (last 5 candles)
            btc_change_5 = (btc_df['close'].iloc[-1] - btc_df['close'].iloc[-6]) / btc_df['close'].iloc[-6] * 100
            
            if btc_change_5 > 0.3:
                btc_trend = 'bullish'
            elif btc_change_5 < -0.3:
                btc_trend = 'bearish'
            else:
                btc_trend = 'neutral'
            
            # Warning if BTC is dumping and correlation is high
            warning = ''
            if btc_trend == 'bearish' and correlation > 0.5:
                warning = f'BTC dropping {btc_change_5:.2f}%, high correlation ({correlation:.2f}) - risky for longs'
            elif btc_trend == 'bullish' and correlation > 0.5:
                warning = f'BTC rising {btc_change_5:.2f}%, correlated - good for longs'
            
            return {
                'correlation': round(correlation, 3),
                'btc_trend': btc_trend,
                'btc_change_5': round(btc_change_5, 3),
                'warning': warning
            }
            
        except Exception as e:
            print(f"[Intelligence] Correlation error: {e}")
            return {'correlation': 0, 'btc_trend': 'unknown', 'warning': ''}
    
    # ── FLASH CRASH / BLACK SWAN DETECTION ────────────────────
    
    def detect_flash_crash(self, df: pd.DataFrame) -> Dict:
        """
        Detect sudden large price moves (flash crash / black swan).
        If detected, pause trading for safety.
        
        Returns: {'detected': bool, 'severity': str, 'drop_pct': float}
        """
        try:
            if df is None or len(df) < 10:
                return {'detected': False, 'severity': 'none', 'drop_pct': 0}
            
            # Check last 3 candles for extreme moves
            recent = df.tail(5)
            
            # Max single-candle move
            max_move = 0
            for i in range(1, len(recent)):
                candle_move = abs(recent.iloc[i]['close'] - recent.iloc[i-1]['close']) / recent.iloc[i-1]['close'] * 100
                max_move = max(max_move, candle_move)
            
            # Check for large wick (rejection)
            latest = df.iloc[-1]
            body = abs(latest['close'] - latest['open'])
            wick_up = latest['high'] - max(latest['close'], latest['open'])
            wick_down = min(latest['close'], latest['open']) - latest['low']
            total_range = latest['high'] - latest['low']
            
            if total_range > 0:
                wick_ratio = max(wick_up, wick_down) / total_range
            else:
                wick_ratio = 0
            
            # 5-candle total move
            move_5 = abs(recent.iloc[-1]['close'] - recent.iloc[0]['close']) / recent.iloc[0]['close'] * 100
            
            # ATR-based detection (is this move abnormal?)
            if len(df) >= 20:
                atr_values = []
                for i in range(1, min(20, len(df))):
                    tr = max(
                        df.iloc[i]['high'] - df.iloc[i]['low'],
                        abs(df.iloc[i]['high'] - df.iloc[i-1]['close']),
                        abs(df.iloc[i]['low'] - df.iloc[i-1]['close'])
                    )
                    atr_values.append(tr)
                avg_atr = np.mean(atr_values) if atr_values else 0
                current_range = latest['high'] - latest['low']
                atr_multiple = current_range / avg_atr if avg_atr > 0 else 1
            else:
                atr_multiple = 1
            
            # Classify severity
            detected = False
            severity = 'none'
            
            if max_move > 3.0 or move_5 > 5.0 or atr_multiple > 4:
                detected = True
                severity = 'extreme'
                self.flash_crash_cooldown = 300  # 5 min cooldown
            elif max_move > 1.5 or move_5 > 3.0 or atr_multiple > 3:
                detected = True
                severity = 'high'
                self.flash_crash_cooldown = 120  # 2 min cooldown
            elif max_move > 0.8 or atr_multiple > 2.5:
                detected = True
                severity = 'moderate'
                self.flash_crash_cooldown = 60  # 1 min cooldown
            
            return {
                'detected': detected,
                'severity': severity,
                'max_candle_move': round(max_move, 3),
                'move_5_candles': round(move_5, 3),
                'atr_multiple': round(atr_multiple, 2),
                'wick_ratio': round(wick_ratio, 3),
                'cooldown_seconds': self.flash_crash_cooldown
            }
            
        except Exception as e:
            print(f"[Intelligence] Flash crash detection error: {e}")
            return {'detected': False, 'severity': 'none', 'drop_pct': 0}
    
    def is_safe_to_trade(self) -> Tuple[bool, str]:
        """
        Check if it's safe to trade right now.
        Combines all intelligence checks.
        """
        if self.flash_crash_cooldown > 0:
            self.flash_crash_cooldown = max(0, self.flash_crash_cooldown - 10)
            if self.flash_crash_cooldown > 0:
                return False, f"Flash crash cooldown: {self.flash_crash_cooldown}s remaining"
        
        return True, "Safe to trade"
    
    # ── COMBINED INTELLIGENCE SCORE ───────────────────────────
    
    def get_trade_intelligence(self, symbol: str, signal: Dict, 
                                btc_df: pd.DataFrame = None, 
                                alt_df: pd.DataFrame = None) -> Dict:
        """
        Get combined intelligence score for a trade signal.
        Adjusts signal strength based on all smart factors.
        
        Args:
            symbol: Trading symbol (e.g., 'XBTUSDTM')
            signal: Original signal dict from strategy
            btc_df: BTC OHLCV dataframe (for correlation)
            alt_df: Alt OHLCV dataframe (for correlation)
        
        Returns:
            Modified signal dict with intelligence adjustments
        """
        adjustments = []
        strength_mod = 0
        
        # 1. Safety check
        safe, safe_reason = self.is_safe_to_trade()
        if not safe:
            signal['signal'] = 'hold'
            signal['reason'] += f' | BLOCKED: {safe_reason}'
            return signal
        
        # 2. Flash crash check on current data
        if alt_df is not None:
            crash = self.detect_flash_crash(alt_df)
            if crash['detected']:
                if crash['severity'] == 'extreme':
                    signal['signal'] = 'hold'
                    signal['reason'] += f" | FLASH CRASH ({crash['severity']})"
                    return signal
                elif crash['severity'] == 'high':
                    strength_mod -= 3
                    adjustments.append(f"Volatile ({crash['severity']})")
                else:
                    strength_mod -= 1
                    adjustments.append(f"Elevated volatility")
        
        # 3. Order book analysis
        ob = self.analyze_orderbook(symbol)
        if ob['bias'] != 'neutral':
            if (signal['signal'] == 'buy' and ob['bias'] == 'bullish') or \
               (signal['signal'] == 'sell' and ob['bias'] == 'bearish'):
                strength_mod += ob['strength']
                adjustments.append(f"OB confirms ({ob['bias']})")
            elif (signal['signal'] == 'buy' and ob['bias'] == 'bearish') or \
                 (signal['signal'] == 'sell' and ob['bias'] == 'bullish'):
                strength_mod -= ob['strength']
                adjustments.append(f"OB opposes ({ob['bias']})")
        
        # 4. Funding rate check
        funding = self.check_funding_rate(symbol)
        if funding['expensive']:
            if (signal['signal'] == 'buy' and funding['direction'] == 'bearish') or \
               (signal['signal'] == 'sell' and funding['direction'] == 'bullish'):
                strength_mod -= 2
                adjustments.append(f"Funding costly ({funding['rate_pct']:.3f}%)")
            else:
                strength_mod += 1
                adjustments.append(f"Funding favors trade")
        
        # 5. BTC correlation (only for altcoins)
        if 'SIREN' in symbol and btc_df is not None and alt_df is not None:
            corr = self.check_btc_correlation(btc_df, alt_df)
            if corr['correlation'] > 0.5:
                if signal['signal'] == 'buy' and corr['btc_trend'] == 'bearish':
                    strength_mod -= 2
                    adjustments.append(f"BTC bearish, high corr ({corr['correlation']:.2f})")
                elif signal['signal'] == 'buy' and corr['btc_trend'] == 'bullish':
                    strength_mod += 1
                    adjustments.append(f"BTC bullish, confirms")
                elif signal['signal'] == 'sell' and corr['btc_trend'] == 'bullish':
                    strength_mod -= 2
                    adjustments.append(f"BTC bullish, opposes short")
                elif signal['signal'] == 'sell' and corr['btc_trend'] == 'bearish':
                    strength_mod += 1
                    adjustments.append(f"BTC bearish, confirms short")
        
        # Apply adjustments
        original_strength = signal['strength']
        signal['strength'] = max(0, min(10, signal['strength'] + strength_mod))
        
        if adjustments:
            signal['reason'] += ' | IQ: ' + ', '.join(adjustments)
        
        signal['intelligence'] = {
            'adjustments': adjustments,
            'strength_mod': strength_mod,
            'original_strength': original_strength,
            'final_strength': signal['strength']
        }
        
        return signal

"""
Order Flow & Liquidity Intelligence
Analyzes order book imbalance, liquidity zones, absorption, fake breakouts.
"""
import time
from typing import Dict, Optional
import numpy as np

class OrderFlowAnalyzer:
    def __init__(self, client):
        self.client = client
    
    def analyze_orderbook_imbalance(self, symbol: str) -> Dict:
        """Detect bid vs ask pressure."""
        try:
            from src.api.kucoin_client import to_ccxt_symbol
            ccxt_symbol = to_ccxt_symbol(symbol)
            orderbook = self.client.public.fetch_order_book(ccxt_symbol, limit=20)
            
            if not orderbook:
                return {'imbalance': 0, 'bias': 'neutral'}
            
            bids = orderbook.get('bids', [])
            asks = orderbook.get('asks', [])
            
            bid_volume = sum(b[1] for b in bids[:20])
            ask_volume = sum(a[1] for a in asks[:20])
            
            total = bid_volume + ask_volume
            if total == 0:
                return {'imbalance': 0, 'bias': 'neutral'}
            
            imbalance = (bid_volume - ask_volume) / total
            
            if imbalance > 0.3:
                bias = 'bullish'
            elif imbalance < -0.3:
                bias = 'bearish'
            else:
                bias = 'neutral'
            
            return {
                'imbalance': round(imbalance, 3),
                'bid_volume': bid_volume,
                'ask_volume': ask_volume,
                'bias': bias
            }
        except Exception as e:
            return {'imbalance': 0, 'bias': 'neutral', 'error': str(e)}
    
    def detect_liquidity_zones(self, df) -> Dict:
        """Find equal highs/lows where stops cluster."""
        if len(df) < 20:
            return {'zones': [], 'nearest_zone': None}
        
        highs = df['high'].tail(20).values
        lows = df['low'].tail(20).values
        
        # Find clusters of similar highs/lows (within 0.5%)
        zones = []
        
        for i in range(len(highs)):
            for j in range(i+1, len(highs)):
                if abs(highs[i] - highs[j]) / highs[i] < 0.005:
                    zones.append({'price': highs[i], 'type': 'resistance', 'touches': 2})
        
        for i in range(len(lows)):
            for j in range(i+1, len(lows)):
                if abs(lows[i] - lows[j]) / lows[i] < 0.005:
                    zones.append({'price': lows[i], 'type': 'support', 'touches': 2})
        
        # Get nearest zone to current price
        current_price = df.iloc[-1]['close']
        nearest = None
        min_distance = float('inf')
        
        for zone in zones:
            distance = abs(zone['price'] - current_price) / current_price
            if distance < min_distance:
                min_distance = distance
                nearest = zone
        
        return {'zones': zones, 'nearest_zone': nearest}
    
    def detect_fake_breakout(self, df) -> bool:
        """Detect breakouts with no volume confirmation."""
        if len(df) < 10:
            return False
        
        latest = df.iloc[-1]
        avg_volume = df['volume'].tail(10).mean()
        
        # Check if price broke recent high/low
        high_10 = df['high'].tail(10).max()
        low_10 = df['low'].tail(10).min()
        
        broke_high = latest['close'] > high_10
        broke_low = latest['close'] < low_10
        
        if broke_high or broke_low:
            # But volume is LOW (< 80% of average)
            if latest['volume'] < avg_volume * 0.8:
                return True  # Fake breakout
        
        return False

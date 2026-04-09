"""
Multi-Pair Trading Manager
Scans multiple trading pairs for opportunities.
DISABLED by default - enable only when ready to trade multiple pairs.
"""

from typing import List, Dict, Optional
from src.utils.logger import get_logger

logger = get_logger(__name__)

class MultiPairManager:
    """Manages multiple trading pairs for the bot."""
    
    # Default: Single pair mode (recommended for $50 capital)
    DEFAULT_PAIRS = ["XBTUSDTM"]

    EXTENDED_PAIRS = [
        "XBTUSDTM",   # Bitcoin
        "ETHUSDTM",   # Ethereum
        "SOLUSDTM",   # Solana
        "XRPUSDTM",   # Ripple
        "DOGEUSDTM",  # Dogecoin
        "ADAUSDTM",   # Cardano
        "MATICUSDTM", # Polygon
        "DOTUSDTM",   # Polkadot
    ]
    
    def __init__(self, enabled: bool = False, pairs: List[str] = None):
        """
        Initialize multi-pair manager.
        
        Args:
            enabled: If False, only uses primary_pair (single-pair mode)
            pairs: Custom list of pairs (uses DEFAULT_PAIRS if None)
        """
        self.enabled = enabled
        self.pairs = pairs or self.DEFAULT_PAIRS
        
        if not enabled:
            logger.info(f"Multi-pair mode: DISABLED (using single pair: {self.pairs[0]})")
        else:
            logger.info(f"Multi-pair mode: ENABLED with {len(self.pairs)} pairs")
            logger.info(f"Pairs: {', '.join(self.pairs)}")
    
    def get_active_pairs(self) -> List[str]:
        """Get list of pairs to trade."""
        if not self.enabled:
            return [self.pairs[0]]  # Return only primary pair
        return self.pairs
    
    def is_multi_pair(self) -> bool:
        """Check if multi-pair mode is enabled."""
        return self.enabled
    
    def get_pair_count(self) -> int:
        """Get number of active pairs."""
        return len(self.get_active_pairs())
    
    @staticmethod
    def enable_extended_pairs() -> 'MultiPairManager':
        """Factory method to create manager with extended pairs enabled."""
        return MultiPairManager(enabled=True, pairs=MultiPairManager.EXTENDED_PAIRS)
    
    @staticmethod
    def enable_custom_pairs(pairs: List[str]) -> 'MultiPairManager':
        """Factory method to create manager with custom pairs."""
        return MultiPairManager(enabled=True, pairs=pairs)
    
    def should_trade_pair(self, symbol: str) -> bool:
        """Check if a symbol should be traded."""
        return symbol in self.get_active_pairs()
    
    def get_position_limits(self, balance: float) -> Dict[str, float]:
        """
        Calculate position size limits per pair.
        
        For single pair: Can use full allocation
        For multi-pair: Split allocation across pairs
        
        Args:
            balance: Account balance
            
        Returns:
            Dict of symbol -> max_position_size
        """
        active_pairs = self.get_active_pairs()
        num_pairs = len(active_pairs)
        
        # Risk management: Don't allocate more than 30% per pair in multi-pair mode
        if num_pairs == 1:
            # Single pair: Can use up to 30% of balance
            max_per_pair = balance * 0.30
        else:
            # Multi-pair: Split risk, max 15% per pair
            max_per_pair = balance * 0.15
        
        return {pair: max_per_pair for pair in active_pairs}
    
    def get_next_opportunity(self, signals: Dict[str, Dict]) -> Optional[Dict]:
        """
        Get the best trading opportunity from multiple pairs.
        
        Args:
            signals: Dict of symbol -> signal data
            
        Returns:
            Best signal or None
        """
        if not signals:
            return None
        
        # Filter to active pairs only
        active_signals = {
            symbol: signal 
            for symbol, signal in signals.items() 
            if self.should_trade_pair(symbol) and signal.get('signal') != 'hold'
        }
        
        if not active_signals:
            return None
        
        # Return signal with highest strength
        best_symbol = max(
            active_signals.keys(),
            key=lambda s: active_signals[s].get('strength', 0)
        )
        
        return {
            'symbol': best_symbol,
            **active_signals[best_symbol]
        }

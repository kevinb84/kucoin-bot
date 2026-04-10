import pandas as pd
import numpy as np
from typing import Dict, Optional, List
from datetime import datetime, timedelta
from src.utils.logger import get_logger

logger = get_logger(__name__)

class AdvancedRiskManager:
    """
    Advanced risk management with:
    - ATR-based position sizing
    - Trailing stop losses
    - Daily loss circuit breakers
    - Maximum drawdown protection
    - Dynamic leverage adjustment
    """
    
    def __init__(self, config: Dict):
        self.config = config
        
        # Position sizing
        self.risk_per_trade = config.get('risk_per_trade', 2.0)  # % of balance
        self.max_position_size = config.get('max_position_size', 1000)  # USDT
        self.leverage = config.get('leverage', 10)
        self.max_leverage = config.get('max_leverage', 20)
        
        # Stop loss / Take profit
        self.stop_loss_percent = config.get('stop_loss_percent', 0.5)
        self.take_profit_percent = config.get('take_profit_percent', 1.0)
        
        # Trailing stop
        self.trailing_stop_enabled = config.get('trailing_stop', True)
        self.trailing_stop_distance = config.get('trailing_stop_distance', 0.3)  # %
        
        # Circuit breakers
        self.max_daily_loss = config.get('max_daily_loss', 5.0)  # % of balance
        self.max_drawdown = config.get('max_drawdown', 10.0)  # % of balance
        
        # State tracking
        self.daily_pnl = 0.0
        self.daily_trades = 0
        self.total_trades = 0
        self.peak_balance = 0.0
        self.current_balance = 0.0
        self.open_position: Optional[Dict] = None
        self.trade_history: List[Dict] = []
        
        # ATR tracking
        self.atr_values: List[float] = []
        
    def calculate_position_size(self, balance: float, entry_price: float, 
                                 stop_loss_price: float, signal_strength: int = 5) -> float:
        """
        Calculate position size using ATR-based risk management.
        
        Args:
            balance: Account balance
            entry_price: Entry price
            stop_loss_price: Stop loss price
            signal_strength: Signal strength (0-10)
        
        Returns:
            Position size in base currency
        """
        # Risk amount per trade (percentage of balance)
        risk_amount = balance * (self.risk_per_trade / 100.0)
        
        # Adjust based on signal strength (stronger signals = larger position)
        strength_multiplier = 0.5 + (signal_strength / 10.0) * 0.5  # 0.5 to 1.0
        risk_amount *= strength_multiplier
        
        # Calculate risk per unit (distance to stop loss)
        risk_per_unit = abs(entry_price - stop_loss_price)
        
        if risk_per_unit == 0:
            logger.warning("Stop loss equals entry price, using minimum distance")
            risk_per_unit = entry_price * 0.001  # 0.1% minimum
        
        # Position size based on risk
        position_size = risk_amount / risk_per_unit
        
        # Convert to USDT value
        position_value = position_size * entry_price
        
        # Apply maximum position size limit
        if position_value > self.max_position_size:
            position_size = self.max_position_size / entry_price
            logger.info(f"Position size capped at max: {self.max_position_size} USDT")
        
        # Apply leverage
        margin_required = position_value / self.leverage
        
        # Ensure we have enough balance
        if margin_required > balance * 0.9:  # Leave 10% buffer
            position_size = (balance * 0.9 * self.leverage) / entry_price
            logger.warning(f"Insufficient balance, reducing position size")
        
        logger.info(f"Position size calculated: {position_size:.6f} (Value: ${position_value:.2f}, Risk: ${risk_amount:.2f})")
        
        return position_size
    
    def calculate_stop_loss(self, entry_price: float, side: str, 
                             atr: float = None) -> float:
        """
        Calculate stop loss price.
        
        Args:
            entry_price: Entry price
            side: 'buy' or 'sell'
            atr: Average True Range for dynamic stops
        
        Returns:
            Stop loss price
        """
        if atr and self.trailing_stop_enabled:
            # ATR-based stop loss (tighter for scalping)
            stop_distance = atr * 1.5  # 1.5x ATR
        else:
            # Fixed percentage stop loss
            stop_distance = entry_price * (self.stop_loss_percent / 100.0)
        
        if side == 'buy':
            stop_loss = entry_price - stop_distance
        else:  # sell
            stop_loss = entry_price + stop_distance
        
        return stop_loss
    
    def calculate_take_profit(self, entry_price: float, side: str) -> float:
        """
        Calculate take profit price.
        
        Args:
            entry_price: Entry price
            side: 'buy' or 'sell'
        
        Returns:
            Take profit price
        """
        tp_distance = entry_price * (self.take_profit_percent / 100.0)
        
        if side == 'buy':
            take_profit = entry_price + tp_distance
        else:  # sell
            take_profit = entry_price - tp_distance
        
        return take_profit
    
    def update_trailing_stop(self, current_price: float, side: str) -> Optional[float]:
        """
        Update trailing stop based on current price.
        
        Args:
            current_price: Current market price
            side: 'buy' or 'sell'
        
        Returns:
            New trailing stop price or None if not triggered
        """
        if not self.trailing_stop_enabled or not self.open_position:
            return None
        
        position = self.open_position
        current_stop = position.get('current_stop_loss', position['stop_loss'])
        
        # Calculate trailing distance
        trailing_distance = current_price * (self.trailing_stop_distance / 100.0)
        
        new_stop = None
        
        if side == 'buy':
            # For long positions, trail stop upward
            potential_stop = current_price - trailing_distance
            if potential_stop > current_stop:
                new_stop = potential_stop
        else:  # sell
            # For short positions, trail stop downward
            potential_stop = current_price + trailing_distance
            if potential_stop < current_stop or current_stop == position['stop_loss']:
                new_stop = potential_stop
        
        if new_stop:
            logger.info(f"Trailing stop updated: {current_stop:.2f} -> {new_stop:.2f}")
            position['current_stop_loss'] = new_stop
            return new_stop
        
        return None
    
    def check_stop_loss_triggered(self, current_price: float) -> bool:
        """Check if stop loss has been triggered."""
        if not self.open_position:
            return False
        
        position = self.open_position
        current_stop = position.get('current_stop_loss', position['stop_loss'])
        
        if position['side'] == 'buy':
            return current_price <= current_stop
        else:  # sell
            return current_price >= current_stop
    
    def check_take_profit_triggered(self, current_price: float) -> bool:
        """Check if take profit has been triggered."""
        if not self.open_position:
            return False
        
        position = self.open_position
        
        if position['side'] == 'buy':
            return current_price >= position['take_profit']
        else:  # sell
            return current_price <= position['take_profit']
    
    def check_circuit_breakers(self, balance: float) -> Dict:
        """
        Check if any circuit breakers have been triggered.
        
        Returns:
            Dict with status and reason
        """
        # Update balance tracking
        self.current_balance = balance
        
        if balance > self.peak_balance:
            self.peak_balance = balance
        
        # Calculate drawdown
        if self.peak_balance > 0:
            drawdown = (self.peak_balance - balance) / self.peak_balance * 100
        else:
            drawdown = 0.0
        
        # Check daily loss limit
        if self.daily_pnl < -(balance * self.max_daily_loss / 100.0):
            logger.error(f"CIRCUIT BREAKER: Daily loss limit reached! PnL: ${self.daily_pnl:.2f}")
            return {
                'triggered': True,
                'reason': f'Daily loss limit reached (${self.daily_pnl:.2f})',
                'action': 'stop_trading'
            }
        
        # Check maximum drawdown
        if drawdown > self.max_drawdown:
            logger.error(f"CIRCUIT BREAKER: Maximum drawdown reached! Drawdown: {drawdown:.2f}%")
            return {
                'triggered': True,
                'reason': f'Maximum drawdown reached ({drawdown:.2f}%)',
                'action': 'stop_trading'
            }
        
        return {
            'triggered': False,
            'reason': 'All checks passed',
            'action': 'continue',
            'daily_pnl': self.daily_pnl,
            'drawdown': drawdown
        }
    
    def open_trade(self, trade_data: Dict):
        """Record an opened trade."""
        self.open_position = {
            **trade_data,
            'open_time': datetime.now(),
            'current_stop_loss': trade_data['stop_loss'],
            'max_profit': 0.0,
            'max_drawdown': 0.0
        }
        self.daily_trades += 1
        self.total_trades += 1
        
        logger.info(f"Trade opened: {trade_data['side']} {trade_data['quantity']} @ {trade_data['entry_price']}")
    
    def close_trade(self, exit_price: float, exit_reason: str = 'unknown') -> Dict:
        """
        Record a closed trade and calculate PnL.
        
        Args:
            exit_price: Exit price
            exit_reason: Reason for exit (stop_loss, take_profit, signal, etc.)
        
        Returns:
            Trade result dictionary
        """
        if not self.open_position:
            logger.warning("No open position to close")
            return {}
        
        position = self.open_position
        entry_price = position['entry_price']
        quantity = position['quantity']
        side = position['side']
        
        # Calculate PnL (account for contract size)
        # XBTUSDTM: 1 contract = 0.001 BTC
        # SIRENUSDTM: 1 contract = 10 SIREN
        CONTRACT_SIZES = {
            'XBTUSDTM': 0.001,
            'SIRENUSDTM': 10.0,
            'ETHUSDTM': 0.01,
            'SOLUSDTM': 1.0,
        }
        symbol = position.get('symbol', 'XBTUSDTM')
        contract_size = CONTRACT_SIZES.get(symbol, 0.001)
        
        if side == 'buy':
            pnl = (exit_price - entry_price) * quantity * contract_size
            pnl_percent = (exit_price / entry_price - 1) * 100
        else:  # sell
            pnl = (entry_price - exit_price) * quantity * contract_size
            pnl_percent = (1 - exit_price / entry_price) * 100
        
        # Update daily PnL
        self.daily_pnl += pnl
        
        # Create trade record
        trade_result = {
            'timestamp': datetime.now().isoformat(),
            'symbol': position.get('symbol', 'UNKNOWN'),
            'side': side,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'quantity': quantity,
            'leverage': position.get('leverage', 1),
            'pnl': pnl,
            'pnl_percent': pnl_percent,
            'exit_reason': exit_reason,
            'duration_minutes': (datetime.now() - position['open_time']).total_seconds() / 60,
            'max_profit': position['max_profit'],
            'max_drawdown': position['max_drawdown'],
            'signal_strength': position.get('signal_strength', 0)
        }
        
        # Add to history
        self.trade_history.append(trade_result)
        
        # Clear open position
        self.open_position = None
        
        logger.info(f"Trade closed: {exit_reason} | PnL: ${pnl:.2f} ({pnl_percent:.2f}%)")
        
        return trade_result
    
    def update_position_tracking(self, current_price: float):
        """Update max profit and drawdown for open position."""
        if not self.open_position:
            return
        
        position = self.open_position
        entry_price = position['entry_price']
        side = position['side']
        
        # Calculate current PnL
        if side == 'buy':
            current_pnl = (current_price - entry_price) / entry_price * 100
        else:  # sell
            current_pnl = (entry_price - current_price) / entry_price * 100
        
        # Track max profit
        if current_pnl > position['max_profit']:
            position['max_profit'] = current_pnl
        
        # Track max drawdown
        if current_pnl < position['max_drawdown']:
            position['max_drawdown'] = current_pnl
    
    def update_atr(self, df: pd.DataFrame):
        """Update ATR values from DataFrame."""
        if 'atr' in df.columns and len(df) > 0:
            latest_atr = df.iloc[-1]['atr']
            if not pd.isna(latest_atr):
                self.atr_values.append(latest_atr)
                # Keep last 100 ATR values
                if len(self.atr_values) > 100:
                    self.atr_values = self.atr_values[-100:]
    
    def get_current_atr(self) -> float:
        """Get current ATR value."""
        if self.atr_values:
            return self.atr_values[-1]
        return 0.0
    
    def get_daily_stats(self) -> Dict:
        """Get daily trading statistics."""
        winning_trades = sum(1 for t in self.trade_history if t['pnl'] > 0)
        total_trades_today = self.daily_trades
        
        return {
            'daily_pnl': self.daily_pnl,
            'daily_trades': self.daily_trades,
            'total_trades': self.total_trades,
            'daily_win_rate': (winning_trades / total_trades_today * 100) if total_trades_today > 0 else 0,
            'peak_balance': self.peak_balance,
            'current_balance': self.current_balance
        }
    
    def reset_daily_stats(self):
        """Reset daily statistics (call at start of new trading day)."""
        self.daily_pnl = 0.0
        self.daily_trades = 0
        logger.info("Daily statistics reset")
    
    def should_stop_trading(self, balance: float) -> bool:
        """Check if trading should be stopped due to risk limits."""
        circuit_check = self.check_circuit_breakers(balance)
        return circuit_check['triggered']

import numpy as np
from typing import List, Dict
from datetime import datetime

class PerformanceAnalyzer:
    """Analyze trading performance and calculate key metrics."""
    
    def __init__(self, trades: List[Dict]):
        self.trades = trades
        self.pnls = [t.get('pnl', 0) for t in trades if t.get('pnl') is not None]
        self.pnl_percents = [t.get('pnl_percent', 0) for t in trades if t.get('pnl_percent') is not None]
    
    def calculate_win_rate(self) -> float:
        """Calculate win rate percentage."""
        if not self.pnls:
            return 0.0
        wins = sum(1 for pnl in self.pnls if pnl > 0)
        return (wins / len(self.pnls)) * 100
    
    def calculate_profit_factor(self) -> float:
        """Calculate profit factor (gross profit / gross loss)."""
        if not self.pnls:
            return 0.0
        
        gross_profit = sum(pnl for pnl in self.pnls if pnl > 0)
        gross_loss = abs(sum(pnl for pnl in self.pnls if pnl < 0))
        
        if gross_loss == 0:
            return float('inf') if gross_profit > 0 else 0
        
        return gross_profit / gross_loss
    
    def calculate_sharpe_ratio(self, risk_free_rate: float = 0.0) -> float:
        """Calculate Sharpe ratio."""
        if len(self.pnl_percents) < 2:
            return 0.0
        
        returns = np.array(self.pnl_percents)
        excess_returns = returns - risk_free_rate
        
        if np.std(excess_returns) == 0:
            return 0.0
        
        return np.mean(excess_returns) / np.std(excess_returns) * np.sqrt(252)
    
    def calculate_max_drawdown(self) -> float:
        """Calculate maximum drawdown percentage."""
        if not self.pnl_percents:
            return 0.0
        
        cumulative = np.cumsum(self.pnl_percents)
        peak = np.maximum.accumulate(cumulative)
        drawdown = (cumulative - peak) / (peak + 1e-10) * 100
        
        return float(np.min(drawdown))
    
    def calculate_avg_win_loss_ratio(self) -> float:
        """Calculate average win to average loss ratio."""
        if not self.pnls:
            return 0.0
        
        wins = [pnl for pnl in self.pnls if pnl > 0]
        losses = [pnl for pnl in self.pnls if pnl < 0]
        
        avg_win = np.mean(wins) if wins else 0
        avg_loss = abs(np.mean(losses)) if losses else 0
        
        if avg_loss == 0:
            return float('inf') if avg_win > 0 else 0
        
        return avg_win / avg_loss
    
    def calculate_expectancy(self) -> float:
        """Calculate trading expectancy (expected profit per trade)."""
        if not self.pnls:
            return 0.0
        
        win_rate = self.calculate_win_rate() / 100
        avg_win = np.mean([pnl for pnl in self.pnls if pnl > 0]) if any(pnl > 0 for pnl in self.pnls) else 0
        avg_loss = abs(np.mean([pnl for pnl in self.pnls if pnl < 0])) if any(pnl < 0 for pnl in self.pnls) else 0
        
        return (win_rate * avg_win) - ((1 - win_rate) * avg_loss)
    
    def calculate_consecutive_wins_losses(self) -> Dict:
        """Calculate max consecutive wins and losses."""
        if not self.pnls:
            return {'max_consecutive_wins': 0, 'max_consecutive_losses': 0}
        
        max_consecutive_wins = 0
        max_consecutive_losses = 0
        current_wins = 0
        current_losses = 0
        
        for pnl in self.pnls:
            if pnl > 0:
                current_wins += 1
                current_losses = 0
                max_consecutive_wins = max(max_consecutive_wins, current_wins)
            else:
                current_losses += 1
                current_wins = 0
                max_consecutive_losses = max(max_consecutive_losses, current_losses)
        
        return {
            'max_consecutive_wins': max_consecutive_wins,
            'max_consecutive_losses': max_consecutive_losses
        }
    
    def get_full_report(self) -> Dict:
        """Generate complete performance report."""
        if not self.pnls:
            return {
                'total_trades': 0,
                'win_rate': 0,
                'profit_factor': 0,
                'sharpe_ratio': 0,
                'max_drawdown': 0,
                'avg_win_loss_ratio': 0,
                'expectancy': 0,
                'total_pnl': 0,
                'avg_pnl': 0,
                'consecutive_stats': {'max_consecutive_wins': 0, 'max_consecutive_losses': 0}
            }
        
        return {
            'total_trades': len(self.pnls),
            'win_rate': self.calculate_win_rate(),
            'profit_factor': self.calculate_profit_factor(),
            'sharpe_ratio': self.calculate_sharpe_ratio(),
            'max_drawdown': self.calculate_max_drawdown(),
            'avg_win_loss_ratio': self.calculate_avg_win_loss_ratio(),
            'expectancy': self.calculate_expectancy(),
            'total_pnl': sum(self.pnls),
            'avg_pnl': np.mean(self.pnls),
            'consecutive_stats': self.calculate_consecutive_wins_losses()
        }
    
    def is_profitable(self) -> bool:
        """Check if trading is profitable overall."""
        return sum(self.pnls) > 0
    
    def needs_improvement(self, min_win_rate: float = 50.0, min_profit_factor: float = 1.5) -> bool:
        """Check if strategy needs improvement based on thresholds."""
        win_rate = self.calculate_win_rate()
        profit_factor = self.calculate_profit_factor()
        
        return win_rate < min_win_rate or profit_factor < min_profit_factor

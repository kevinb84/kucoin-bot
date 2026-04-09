from typing import Dict, List, Tuple
import numpy as np
from itertools import product


class ParameterOptimizer:
    """Automatically optimize strategy parameters based on historical performance."""

    def __init__(self, trades: List[Dict], param_ranges: Dict):
        """
        Initialize optimizer.

        Args:
            trades: List of historical trades
            param_ranges: Dictionary of parameter names to their possible values
                         e.g., {'ema_fast': [8, 10, 12, 15], 'ema_slow': [20, 26, 30]}
        """
        self.trades = trades
        self.param_ranges = param_ranges

    def _calculate_score(self, trades_subset: List[Dict]) -> float:
        """Calculate performance score for a set of trades."""
        if not trades_subset:
            return 0.0

        pnls = [t.get('pnl', 0) for t in trades_subset if t.get('pnl') is not None]

        if not pnls:
            return 0.0

        total_pnl = sum(pnls)
        wins = sum(1 for pnl in pnls if pnl > 0)
        win_rate = wins / len(pnls) if pnls else 0

        # Weighted score: 40% win rate, 40% total PnL, 20% consistency
        gross_profit = sum(pnl for pnl in pnls if pnl > 0)
        gross_loss = abs(sum(pnl for pnl in pnls if pnl < 0))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0

        score = (win_rate * 40) + (min(total_pnl, 100) * 0.4) + (min(profit_factor, 3) * 20 / 3)

        return score

    def grid_search(self, top_n: int = 5) -> List[Dict]:
        """
        Perform grid search over parameter space.

        Returns:
            List of parameter combinations sorted by performance score
        """
        param_names = list(self.param_ranges.keys())
        param_values = [self.param_ranges[name] for name in param_names]

        all_combinations = list(product(*param_values))
        results = []

        for combo in all_combinations:
            params = dict(zip(param_names, combo))

            # Simulate trades with these parameters (simplified - in reality you'd backtest)
            # For now, we'll use a heuristic based on existing trades
            score = self._evaluate_parameters(params)

            results.append({
                'params': params,
                'score': score
            })

        # Sort by score descending
        results.sort(key=lambda x: x['score'], reverse=True)

        return results[:top_n]

    def _evaluate_parameters(self, params: Dict) -> float:
        """
        Evaluate how good a parameter set is.
        This is a simplified version - in production you'd run a full backtest.
        """
        # Extract parameters
        ema_fast = params.get('ema_fast', 12)
        ema_slow = params.get('ema_slow', 26)
        rsi_period = params.get('rsi_period', 14)

        # Simple heuristic: prefer balanced parameters
        # Fast EMA should be significantly faster than slow EMA
        if ema_fast >= ema_slow:
            return 0.0

        # Prefer reasonable RSI periods
        if rsi_period < 5 or rsi_period > 30:
            return 0.0

        # Score based on parameter balance
        ema_ratio = ema_slow / ema_fast
        score = 50.0  # Base score

        # Bonus for good EMA ratio (1.5-3.0 is ideal)
        if 1.5 <= ema_ratio <= 3.0:
            score += 30
        elif 1.2 <= ema_ratio <= 4.0:
            score += 15

        # Bonus for reasonable RSI
        if 10 <= rsi_period <= 20:
            score += 20

        return score

    def recommend_params(self, current_params: Dict) -> Dict:
        """
        Recommend improved parameters based on current settings.

        Returns:
            Dictionary of recommended parameters
        """
        top_params = self.grid_search(top_n=1)

        if not top_params:
            return current_params

        recommended = top_params[0]['params']

        # Blend with current params to avoid drastic changes
        blended = {}
        for key in current_params:
            if key in recommended:
                # 70% new recommendation, 30% current
                if isinstance(current_params[key], (int, float)):
                    blended[key] = int(recommended[key] * 0.7 + current_params[key] * 0.3)
                else:
                    blended[key] = recommended[key]
            else:
                blended[key] = current_params[key]

        return blended

    def adaptive_adjustment(self, performance_metrics: Dict) -> Dict:
        """
        Adjust parameters based on performance metrics.

        Args:
            performance_metrics: Dictionary with win_rate, profit_factor, etc.

        Returns:
            Dictionary of adjustment recommendations
        """
        adjustments = {}

        win_rate = performance_metrics.get('win_rate', 50)
        profit_factor = performance_metrics.get('profit_factor', 1.0)

        # If win rate is low, suggest tighter entry criteria
        if win_rate < 45:
            adjustments['entry_threshold'] = 'increase'  # More selective entries
            adjustments['rsi_overbought'] = 'decrease'  # Exit winners earlier
        elif win_rate > 65:
            adjustments['entry_threshold'] = 'decrease'  # Can be less selective
            adjustments['rsi_overbought'] = 'increase'  # Let winners run

        # If profit factor is low, suggest tighter risk management
        if profit_factor < 1.2:
            adjustments['stop_loss_pct'] = 'decrease'  # Tighter stops
            adjustments['take_profit_pct'] = 'increase'  # Larger targets
        elif profit_factor > 2.0:
            adjustments['stop_loss_pct'] = 'increase'  # Can afford wider stops
            adjustments['take_profit_pct'] = 'decrease'  # Take profits quicker

        return adjustments

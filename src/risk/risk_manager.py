from typing import Dict, Optional
from dataclasses import dataclass


@dataclass
class PositionInfo:
    symbol: str
    size: float
    entry_price: float
    current_price: float
    unrealized_pnl: float
    leverage: int


class RiskManager:
    def __init__(self, max_position_size: float, stop_loss_percent: float,
                 take_profit_percent: float, max_leverage: int = 20):
        self.max_position_size = max_position_size
        self.stop_loss_percent = stop_loss_percent
        self.take_profit_percent = take_profit_percent
        self.max_leverage = max_leverage

    def calculate_position_size(self, balance: float, signal_strength: float,
                                current_price: float) -> float:
        risk_amount = balance * 0.02
        position_size = min(
            self.max_position_size,
            (risk_amount * signal_strength) / 100
        )
        contracts = position_size / current_price
        return max(contracts, 0.001)

    def calculate_stop_loss(self, entry_price: float, side: str) -> float:
        if side == 'buy':
            return entry_price * (1 - self.stop_loss_percent / 100)
        else:
            return entry_price * (1 + self.stop_loss_percent / 100)

    def calculate_take_profit(self, entry_price: float, side: str) -> float:
        if side == 'buy':
            return entry_price * (1 + self.take_profit_percent / 100)
        else:
            return entry_price * (1 - self.take_profit_percent / 100)

    def check_stop_loss(self, position: PositionInfo) -> bool:
        if position.size == 0:
            return False
        if position.size > 0:
            return position.current_price <= position.entry_price * (1 - self.stop_loss_percent / 100)
        else:
            return position.current_price >= position.entry_price * (1 + self.stop_loss_percent / 100)

    def check_take_profit(self, position: PositionInfo) -> bool:
        if position.size == 0:
            return False
        if position.size > 0:
            return position.current_price >= position.entry_price * (1 + self.take_profit_percent / 100)
        else:
            return position.current_price <= position.entry_price * (1 - self.take_profit_percent / 100)

    def validate_leverage(self, leverage: int) -> bool:
        return 1 <= leverage <= self.max_leverage

    def get_max_position_value(self, balance: float) -> float:
        return self.max_position_size

    def check_risk_limits(self, balance: float, proposed_position_size: float) -> Dict[str, any]:
        if proposed_position_size > self.max_position_size:
            return {
                'allowed': False,
                'reason': f'Position size {proposed_position_size} exceeds max {self.max_position_size}'
            }
        position_value = proposed_position_size
        if position_value > balance * 0.5:
            return {
                'allowed': False,
                'reason': f'Position value exceeds 50% of balance'
            }
        return {
            'allowed': True,
            'reason': 'Within risk limits'
        }

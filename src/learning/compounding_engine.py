"""
Compounding Engine
Automatically increases position size as balance grows.
Target: 1000 trades/week with compounding reinvestment.
"""
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List


class CompoundingEngine:
    """
    Manages compounding position sizing.
    As balance grows, position size grows proportionally.
    Tracks weekly targets and milestones.
    """

    # Milestones to celebrate and log
    MILESTONES = [50, 100, 200, 500, 1000, 2000, 5000, 10000]

    def __init__(self, starting_balance: float = 45.0, risk_pct: float = 10.0):
        """
        Args:
            starting_balance: Starting capital in USDT
            risk_pct: % of balance to risk per trade (10% recommended)
        """
        self.starting_balance  = starting_balance
        self.current_balance   = starting_balance
        self.risk_pct          = risk_pct          # 10% default
        self.peak_balance      = starting_balance
        self.total_trades      = 0
        self.winning_trades    = 0
        self.total_profit      = 0.0
        self.week_start_bal    = starting_balance
        self.week_start_time   = datetime.now()
        self.trade_history: List[Dict] = []
        self.milestones_hit: List[float] = []
        self.state_file        = 'compounding_state.json'
        self._load_state()

    # ── STATE PERSISTENCE ─────────────────────────────────────

    def _load_state(self):
        """Load saved state from disk."""
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    data = json.load(f)
                self.current_balance  = data.get('current_balance',  self.starting_balance)
                self.peak_balance     = data.get('peak_balance',     self.starting_balance)
                self.total_trades     = data.get('total_trades',     0)
                self.winning_trades   = data.get('winning_trades',   0)
                self.total_profit     = data.get('total_profit',     0.0)
                self.week_start_bal   = data.get('week_start_bal',   self.starting_balance)
                self.milestones_hit   = data.get('milestones_hit',   [])
                print(f"[Compounding] Loaded state: balance=${self.current_balance:.2f}, trades={self.total_trades}")
        except Exception as e:
            print(f"[Compounding] Could not load state: {e}")

    def _save_state(self):
        """Save state to disk."""
        try:
            data = {
                'current_balance': self.current_balance,
                'peak_balance':    self.peak_balance,
                'total_trades':    self.total_trades,
                'winning_trades':  self.winning_trades,
                'total_profit':    self.total_profit,
                'week_start_bal':  self.week_start_bal,
                'milestones_hit':  self.milestones_hit,
                'last_saved':      datetime.now().isoformat(),
            }
            with open(self.state_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[Compounding] Could not save state: {e}")

    # ── POSITION SIZING ───────────────────────────────────────

    def get_position_size_usd(self) -> float:
        """
        Calculate position margin in USDT based on current balance.
        This is the core of compounding: bigger balance = bigger trades.
        """
        margin = self.current_balance * (self.risk_pct / 100)
        # Safety cap: never risk more than 20% in one trade
        max_margin = self.current_balance * 0.20
        return min(margin, max_margin)

    def get_risk_amount(self) -> float:
        """How much USDT we risk per trade (for stop loss sizing)."""
        return self.current_balance * (self.risk_pct / 100) * 0.3  # 30% of margin

    # ── TRADE RECORDING ───────────────────────────────────────

    def record_trade(self, pnl: float, side: str, symbol: str):
        """
        Record completed trade and update balance.
        pnl: profit/loss in USDT (negative for losses)
        """
        self.current_balance += pnl
        self.total_trades    += 1
        self.total_profit    += pnl

        if pnl > 0:
            self.winning_trades += 1

        if self.current_balance > self.peak_balance:
            self.peak_balance = self.current_balance

        # Log trade
        self.trade_history.append({
            'timestamp': datetime.now().isoformat(),
            'pnl':       pnl,
            'side':      side,
            'symbol':    symbol,
            'balance':   self.current_balance,
        })
        if len(self.trade_history) > 1000:
            self.trade_history = self.trade_history[-1000:]

        # Check milestones
        for milestone in self.MILESTONES:
            if self.current_balance >= milestone and milestone not in self.milestones_hit:
                self.milestones_hit.append(milestone)
                print(f"[Compounding] MILESTONE HIT: ${milestone}!")

        self._save_state()

    def update_balance(self, real_balance: float):
        """Sync with real KuCoin balance."""
        if real_balance > 0:
            self.current_balance = real_balance
            if real_balance > self.peak_balance:
                self.peak_balance = real_balance
            self._save_state()

    # ── TARGETS & PROJECTIONS ─────────────────────────────────

    def get_weekly_target(self) -> Dict:
        """
        Calculate weekly target based on compounding.
        Assumes 1000 trades/week, 60% win rate.
        """
        trades_per_week = 1000
        win_rate        = 0.60
        avg_win_pct     = self.risk_pct * 1.5   # 1.5x risk on wins
        avg_loss_pct    = self.risk_pct * 0.5   # 0.5x risk on losses

        bal = self.current_balance
        for _ in range(trades_per_week):
            margin = bal * (self.risk_pct / 100)
            if True:  # simulate average
                bal += margin * (win_rate * avg_win_pct/100 - (1-win_rate) * avg_loss_pct/100)

        weekly_profit = bal - self.current_balance
        target_bal    = self.current_balance + weekly_profit

        return {
            'current_balance':  round(self.current_balance, 2),
            'target_balance':   round(target_bal, 2),
            'weekly_profit':    round(weekly_profit, 2),
            'weekly_return_pct': round((weekly_profit / self.current_balance) * 100, 1),
            'trades_per_week':  trades_per_week,
            'trades_today':     self._trades_today(),
            'trades_this_week': self.total_trades,
        }

    def get_projection_table(self) -> List[Dict]:
        """
        Generate compounding projection table.
        Shows balance growth over 1000, 5000, 10000 trades.
        """
        rows = []
        bal  = self.current_balance
        win_rate   = 0.60
        risk       = self.risk_pct / 100
        checkpoints = [100, 250, 500, 750, 1000, 2000, 5000, 10000]

        for i, checkpoint in enumerate(checkpoints):
            prev = checkpoints[i-1] if i > 0 else 0
            trades_to_run = checkpoint - prev
            for _ in range(trades_to_run):
                margin = bal * risk
                # Expected value per trade
                ev = margin * (win_rate * 1.5 * risk - (1-win_rate) * 0.5 * risk)
                bal += margin * (win_rate * 0.015 - (1-win_rate) * 0.005)
            rows.append({
                'trades':  checkpoint,
                'balance': round(bal, 2),
                'profit':  round(bal - self.current_balance, 2),
                'multiplier': round(bal / self.current_balance, 1),
            })
        return rows

    def get_stats(self) -> Dict:
        """Get current compounding stats."""
        win_rate = (self.winning_trades / self.total_trades * 100) if self.total_trades > 0 else 0
        drawdown = ((self.peak_balance - self.current_balance) / self.peak_balance * 100) if self.peak_balance > 0 else 0
        weekly   = self.get_weekly_target()

        return {
            'current_balance':   round(self.current_balance, 2),
            'starting_balance':  round(self.starting_balance, 2),
            'peak_balance':      round(self.peak_balance, 2),
            'total_profit':      round(self.total_profit, 2),
            'total_return_pct':  round((self.current_balance - self.starting_balance) / self.starting_balance * 100, 1),
            'total_trades':      self.total_trades,
            'win_rate':          round(win_rate, 1),
            'drawdown_pct':      round(drawdown, 1),
            'risk_per_trade_pct': self.risk_pct,
            'next_trade_margin': round(self.get_position_size_usd(), 2),
            'weekly_target':     weekly,
            'milestones_hit':    self.milestones_hit,
            'projection':        self.get_projection_table(),
        }

    def _trades_today(self) -> int:
        today = datetime.now().date()
        return sum(1 for t in self.trade_history
                   if datetime.fromisoformat(t['timestamp']).date() == today)

    def needs_reset_weekly(self) -> bool:
        """Check if a week has passed and reset weekly stats."""
        now = datetime.now()
        if (now - self.week_start_time).days >= 7:
            self.week_start_bal  = self.current_balance
            self.week_start_time = now
            self._save_state()
            return True
        return False

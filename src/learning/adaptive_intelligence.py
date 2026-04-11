"""
Adaptive Intelligence Engine
Active learning system that:
1. Tracks performance per strategy/symbol/session
2. Auto-selects best strategies for current market conditions
3. Blacklists underperforming symbols
4. Generates weekly performance reports
5. Dynamically adjusts trading parameters
"""
import time
import json
import os
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from collections import defaultdict
import numpy as np

from src.utils.logger import get_logger

logger = get_logger(__name__)


class AdaptiveIntelligenceEngine:
    """
    Active adaptive learning engine that evolves based on trade results.
    
    Core capabilities:
    - Strategy ranking and auto-selection
    - Symbol blacklisting/whitelisting
    - Market regime detection + strategy rotation
    - Fee-aware optimization
    - Weekly performance reports with actionable insights
    - Correlation-aware trade filtering
    """

    def __init__(self, journal, scanner, config: Dict):
        self.journal = journal
        self.scanner = scanner
        self.config = config

        # Performance tracking
        self.strategy_performance: Dict[str, Dict] = defaultdict(lambda: {
            'trades': 0,
            'wins': 0,
            'losses': 0,
            'total_pnl': 0.0,
            'avg_pnl': 0.0,
            'win_rate': 0.0,
            'last_used': 0,
        })

        self.symbol_performance: Dict[str, Dict] = defaultdict(lambda: {
            'trades': 0,
            'wins': 0,
            'losses': 0,
            'total_pnl': 0.0,
            'win_rate': 0.0,
            'blacklisted': False,
            'blacklist_until': 0,
            'last_trade_time': 0,
        })

        self.session_performance: Dict[str, Dict] = defaultdict(lambda: {
            'trades': 0,
            'wins': 0,
            'total_pnl': 0.0,
            'win_rate': 0.0,
        })

        # Market regime tracking
        self.market_regime_history: List[Dict] = []
        self.current_regime = 'unknown'

        # BTC correlation cache
        self.btc_correlations: Dict[str, float] = {}

        # Trade history for analysis
        self.recent_trades: List[Dict] = []
        self.max_trade_history = 500

        # Report generation
        self.last_report_time = time.time()
        self.report_interval = 7 * 24 * 3600  # 7 days

        # State file
        self.state_file = 'adaptive_intelligence_state.json'
        self._load_state()

    # ── STATE PERSISTENCE ─────────────────────────────────────

    def _load_state(self):
        """Load learned state from disk."""
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    data = json.load(f)

                # Restore strategy performance
                for strat, perf in data.get('strategy_performance', {}).items():
                    self.strategy_performance[strat].update(perf)

                # Restore symbol performance
                for sym, perf in data.get('symbol_performance', {}).items():
                    self.symbol_performance[sym].update(perf)

                # Restore session performance
                for sess, perf in data.get('session_performance', {}).items():
                    self.session_performance[sess].update(perf)

                self.recent_trades = data.get('recent_trades', [])
                self.current_regime = data.get('current_regime', 'unknown')

                logger.info(f"[Adaptive IQ] Loaded state: {len(self.strategy_performance)} strategies, "
                           f"{len(self.symbol_performance)} symbols tracked")
        except Exception as e:
            logger.error(f"[Adaptive IQ] Could not load state: {e}")

    def _save_state(self):
        """Save learned state to disk."""
        try:
            data = {
                'strategy_performance': dict(self.strategy_performance),
                'symbol_performance': dict(self.symbol_performance),
                'session_performance': dict(self.session_performance),
                'recent_trades': self.recent_trades[-100:],  # Keep last 100
                'current_regime': self.current_regime,
                'last_saved': datetime.now().isoformat(),
            }
            with open(self.state_file, 'w') as f:
                json.dump(data, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"[Adaptive IQ] Could not save state: {e}")

    # ── TRADE RECORDING & ANALYSIS ────────────────────────────

    def record_trade(self, trade_data: Dict):
        """
        Record a completed trade and update all learning systems.
        
        Args:
            trade_data: Dict with keys:
                - symbol, side, entry_price, exit_price, pnl, pnl_percent
                - strategy_used (e.g., 'trend_following', 'mean_reversion')
                - signal_strength, session (asian/eu/us/etc)
                - market_regime (trending/ranging/volatile)
                - btc_trend_at_entry (bullish/bearish/neutral)
        """
        symbol = trade_data.get('symbol', 'UNKNOWN')
        strategy = trade_data.get('strategy_used', 'unknown')
        session = trade_data.get('session', 'unknown')
        pnl = trade_data.get('pnl', 0)
        won = pnl > 0

        # Update strategy performance
        strat_perf = self.strategy_performance[strategy]
        strat_perf['trades'] += 1
        if won:
            strat_perf['wins'] += 1
        else:
            strat_perf['losses'] += 1
        strat_perf['total_pnl'] += pnl
        strat_perf['avg_pnl'] = strat_perf['total_pnl'] / strat_perf['trades']
        strat_perf['win_rate'] = strat_perf['wins'] / strat_perf['trades'] if strat_perf['trades'] > 0 else 0
        strat_perf['last_used'] = time.time()

        # Update symbol performance
        sym_perf = self.symbol_performance[symbol]
        sym_perf['trades'] += 1
        sym_perf['last_trade_time'] = time.time()
        if won:
            sym_perf['wins'] += 1
        else:
            sym_perf['losses'] += 1
        sym_perf['total_pnl'] += pnl
        sym_perf['win_rate'] = sym_perf['wins'] / sym_perf['trades'] if sym_perf['trades'] > 0 else 0

        # Check if symbol should be blacklisted (< 40% win rate after 10+ trades)
        if sym_perf['trades'] >= 10 and sym_perf['win_rate'] < 0.40:
            if not sym_perf['blacklisted']:
                sym_perf['blacklisted'] = True
                sym_perf['blacklist_until'] = time.time() + 3600 * 3  # 3 hours only
                logger.warning(f"[Adaptive IQ] BLACKLISTED {symbol}: win rate {sym_perf['win_rate']:.1%} after {sym_perf['trades']} trades")

        # Check if blacklist expired
        if sym_perf['blacklisted'] and time.time() > sym_perf['blacklist_until']:
            sym_perf['blacklisted'] = False
            logger.info(f"[Adaptive IQ] Removed blacklist from {symbol} (cooldown expired)")

        # Update session performance
        sess_perf = self.session_performance[session]
        sess_perf['trades'] += 1
        if won:
            sess_perf['wins'] += 1
        sess_perf['total_pnl'] += pnl
        sess_perf['win_rate'] = sess_perf['wins'] / sess_perf['trades'] if sess_perf['trades'] > 0 else 0

        # Track BTC correlation
        btc_trend = trade_data.get('btc_trend_at_entry', 'neutral')
        if btc_trend != 'neutral':
            key = f"{symbol}_{btc_trend}"
            if key not in self.btc_correlations:
                self.btc_correlations[key] = {'trades': 0, 'wins': 0}
            self.btc_correlations[key]['trades'] += 1
            if won:
                self.btc_correlations[key]['wins'] += 1

        # Add to recent trades
        self.recent_trades.append({
            'timestamp': time.time(),
            'symbol': symbol,
            'strategy': strategy,
            'session': session,
            'pnl': pnl,
            'won': won,
            'market_regime': trade_data.get('market_regime', 'unknown'),
        })
        if len(self.recent_trades) > self.max_trade_history:
            self.recent_trades = self.recent_trades[-self.max_trade_history:]

        # Save state
        self._save_state()

        logger.info(
            f"[Adaptive IQ] Recorded trade: {symbol} {strategy} | "
            f"{'WIN' if won else 'LOSS'} ${pnl:.2f} | "
            f"Strat WR: {strat_perf['win_rate']:.1%} | Sym WR: {sym_perf['win_rate']:.1%}"
        )

    # ── STRATEGY RANKING & SELECTION ──────────────────────────

    def get_best_strategies(self, market_regime: str = None, limit: int = 3) -> List[str]:
        """
        Rank strategies by performance and return top N.
        Optionally filter by current market regime.
        
        Ranking formula:
        Score = (win_rate × 40) + (avg_pnl_normalized × 30) + (consistency × 20) + (recency × 10)
        """
        if not self.strategy_performance:
            return ['trend_following']  # Default fallback

        scored_strategies = []

        for strat_name, perf in self.strategy_performance.items():
            if perf['trades'] < 5:
                continue  # Need minimum data

            # Win rate component (40 pts)
            wr_score = perf['win_rate'] * 40

            # Avg PnL component (30 pts) - normalize by typical trade size
            avg_pnl_abs = abs(perf['avg_pnl'])
            pnl_score = min(avg_pnl_abs / 10.0, 1.0) * 30  # Cap at $10 avg

            # Consistency component (20 pts) - lower variance = better
            wins = perf['wins']
            losses = perf['losses']
            total = wins + losses
            if total > 0:
                consistency = 1.0 - abs(wins/total - 0.5) * 2  # 1.0 = perfect 50/50 or better
            else:
                consistency = 0
            consistency_score = consistency * 20

            # Recency component (10 pts) - prefer recently used
            time_since_last = time.time() - perf.get('last_used', 0)
            recency = max(0, 1.0 - time_since_last / 86400)  # Decay over 24h
            recency_score = recency * 10

            total_score = wr_score + pnl_score + consistency_score + recency_score

            scored_strategies.append((strat_name, total_score, perf))

        # Sort by score descending
        scored_strategies.sort(key=lambda x: x[1], reverse=True)

        # Return top N strategy names
        top_strategies = [s[0] for s in scored_strategies[:limit]]

        if top_strategies:
            logger.info(f"[Adaptive IQ] Top strategies: {', '.join(top_strategies)}")

        return top_strategies if top_strategies else ['trend_following']

    def should_use_strategy(self, strategy_name: str, market_regime: str) -> bool:
        """
        Check if a strategy should be used given current market conditions.
        
        Rules:
        - Don't use trend_following in ranging markets
        - Don't use mean_reversion in strong trends
        - Don't use any strategy with < 40% win rate
        """
        perf = self.strategy_performance.get(strategy_name)
        if not perf or perf['trades'] < 5:
            return True  # Allow untested strategies

        # Hard blacklist for low win rates
        recent_trades_for_strat = [t for t in self.recent_trades[-20:]
                                   if t.get('strategy') == strategy_name]
        if len(recent_trades_for_strat) >= 5:
            recent_wr = sum(1 for t in recent_trades_for_strat if t['won']) / len(recent_trades_for_strat)
            if recent_wr < 0.40:
                logger.warning(f"[Adaptive IQ] STRATEGY DISABLED: {strategy_name} recent WR {recent_wr:.1%}")
                return False

        if perf['win_rate'] < 0.40:
            logger.warning(f"[Adaptive IQ] Blocking {strategy_name}: win rate {perf['win_rate']:.1%} too low")
            return False

        # Market regime filtering
        if market_regime == 'ranging' and 'trend' in strategy_name.lower():
            logger.info(f"[Adaptive IQ] Skipping {strategy_name} in ranging market")
            return False

        if market_regime == 'trending' and 'reversion' in strategy_name.lower():
            logger.info(f"[Adaptive IQ] Skipping {strategy_name} in trending market")
            return False

        return True

    # ── SYMBOL INTELLIGENCE ───────────────────────────────────

    def is_symbol_tradeable(self, symbol: str) -> Tuple[bool, str]:
        """
        Check if a symbol should be traded based on historical performance.
        
        Returns: (tradeable: bool, reason: str)
        """
        perf = self.symbol_performance.get(symbol)

        if not perf:
            return True, "New symbol, no history"

        # Check blacklist
        if perf.get('blacklisted', False):
            remaining_hours = (perf['blacklist_until'] - time.time()) / 3600
            return False, f"Blacklisted ({remaining_hours:.1f}h remaining, WR: {perf['win_rate']:.1%})"

        # Low win rate warning (but not blacklisted yet)
        if perf['trades'] >= 10 and perf['win_rate'] < 0.45:
            return False, f"Poor performance (WR: {perf['win_rate']:.1%} after {perf['trades']} trades)"

        # Strong performer - boost confidence
        if perf['trades'] >= 10 and perf['win_rate'] > 0.60:
            return True, f"Strong performer (WR: {perf['win_rate']:.1%})"

        return True, f"Acceptable (WR: {perf['win_rate']:.1%}, {perf['trades']} trades)"

    def get_preferred_symbols(self, limit: int = 10) -> List[str]:
        """
        Get symbols ranked by historical performance.
        Returns list of symbols sorted by win rate (best first).
        """
        ranked = []

        for sym, perf in self.symbol_performance.items():
            if perf['trades'] < 3:
                continue  # Need minimum data
            if perf.get('blacklisted', False):
                continue

            ranked.append((sym, perf['win_rate'], perf['trades']))

        ranked.sort(key=lambda x: x[1], reverse=True)
        return [r[0] for r in ranked[:limit]]

    # ── SESSION OPTIMIZATION ──────────────────────────────────

    def get_best_sessions(self) -> List[str]:
        """Return trading sessions sorted by profitability."""
        sessions = []

        for sess, perf in self.session_performance.items():
            if perf['trades'] < 5:
                continue
            sessions.append((sess, perf['win_rate'], perf['total_pnl']))

        sessions.sort(key=lambda x: x[1], reverse=True)
        return [s[0] for s in sessions]

    def should_trade_this_session(self, current_session: str) -> Tuple[bool, str]:
        """
        Check if we should be trading during the current session.
        
        Returns: (should_trade: bool, reason: str)
        """
        perf = self.session_performance.get(current_session)

        if not perf or perf['trades'] < 5:
            return True, "No session data, defaulting to trade"

        if perf['win_rate'] < 0.35:
            return False, f"Avoid {current_session} session (WR: {perf['win_rate']:.1%})"

        if perf['win_rate'] > 0.55:
            return True, f"Preferred session {current_session} (WR: {perf['win_rate']:.1%})"

        return True, f"Neutral session {current_session} (WR: {perf['win_rate']:.1%})"

    # ── MARKET REGIME DETECTION ───────────────────────────────

    def detect_market_regime(self, btc_df) -> str:
        """
        Detect current market regime using BTC data.
        
        Returns: 'trending', 'ranging', 'volatile', or 'quiet'
        """
        if btc_df is None or len(btc_df) < 20:
            return 'unknown'

        latest = btc_df.iloc[-1]

        # ATR-based volatility
        atr_values = []
        for i in range(1, min(20, len(btc_df))):
            tr = max(
                btc_df.iloc[i]['high'] - btc_df.iloc[i]['low'],
                abs(btc_df.iloc[i]['high'] - btc_df.iloc[i-1]['close']),
                abs(btc_df.iloc[i]['low'] - btc_df.iloc[i-1]['close'])
            )
            atr_values.append(tr)

        avg_atr = np.mean(atr_values) if atr_values else 0
        price = latest['close']
        atr_pct = (avg_atr / price * 100) if price > 0 else 0

        # Trend strength (EMA spread)
        if 'ema_fast' in btc_df.columns and 'ema_slow' in btc_df.columns:
            ema_spread = abs(latest['ema_fast'] - latest['ema_slow']) / latest['ema_slow'] * 100
        else:
            ema_spread = 0

        # Classify regime
        if atr_pct > 3.0:
            regime = 'volatile'
        elif ema_spread > 0.5:
            regime = 'trending'
        elif atr_pct < 0.5:
            regime = 'quiet'
        else:
            regime = 'ranging'

        # Track regime changes
        if regime != self.current_regime:
            logger.info(f"[Adaptive IQ] Market regime changed: {self.current_regime} → {regime}")
            self.current_regime = regime

        self.market_regime_history.append({
            'regime': regime,
            'timestamp': time.time(),
            'atr_pct': atr_pct,
            'ema_spread': ema_spread,
        })
        if len(self.market_regime_history) > 100:
            self.market_regime_history = self.market_regime_history[-100:]

        return regime

    def get_recommended_strategies_for_regime(self, regime: str) -> List[str]:
        """
        Return strategies recommended for current market regime.
        """
        recommendations = {
            'trending': ['trend_following', 'breakout'],
            'ranging': ['mean_reversion', 'support_resistance'],
            'volatile': ['breakout', 'momentum'],
            'quiet': [],  # Don't trade in quiet markets
            'unknown': ['trend_following'],  # Default
        }

        return recommendations.get(regime, ['trend_following'])

    # ── WEEKLY PERFORMANCE REPORT ─────────────────────────────

    def generate_performance_report(self) -> str:
        """
        Generate comprehensive weekly performance report.
        
        Includes:
        - Best/worst symbols
        - Best/worst strategies
        - Session analysis
        - Recommendations for improvement
        """
        now = time.time()

        # Filter trades from last 7 days
        week_ago = now - 7 * 24 * 3600
        recent_trades = [t for t in self.recent_trades if t['timestamp'] > week_ago]

        if not recent_trades:
            return "No trades in the last 7 days."

        # Calculate overall stats
        total_trades = len(recent_trades)
        wins = sum(1 for t in recent_trades if t['won'])
        losses = total_trades - wins
        win_rate = wins / total_trades if total_trades > 0 else 0
        total_pnl = sum(t['pnl'] for t in recent_trades)

        # Best/worst symbols
        symbol_stats = defaultdict(lambda: {'trades': 0, 'wins': 0, 'pnl': 0})
        for t in recent_trades:
            sym = t['symbol']
            symbol_stats[sym]['trades'] += 1
            if t['won']:
                symbol_stats[sym]['wins'] += 1
            symbol_stats[sym]['pnl'] += t['pnl']

        best_symbols = sorted(symbol_stats.items(), key=lambda x: x[1]['pnl'], reverse=True)[:5]
        worst_symbols = sorted(symbol_stats.items(), key=lambda x: x[1]['pnl'])[:5]

        # Best/worst strategies
        strategy_stats = defaultdict(lambda: {'trades': 0, 'wins': 0, 'pnl': 0})
        for t in recent_trades:
            strat = t['strategy']
            strategy_stats[strat]['trades'] += 1
            if t['won']:
                strategy_stats[strat]['wins'] += 1
            strategy_stats[strat]['pnl'] += t['pnl']

        best_strategies = sorted(strategy_stats.items(), key=lambda x: x[1]['pnl'], reverse=True)[:5]
        worst_strategies = sorted(strategy_stats.items(), key=lambda x: x[1]['pnl'])[:5]

        # Build report
        report = f"""
╔═══════════════════════════════════════════════════════════╗
║        WEEKLY PERFORMANCE REPORT                         ║
║        {datetime.now().strftime('%Y-%m-%d')}                            
╠═══════════════════════════════════════════════════════════╣

📊 OVERALL PERFORMANCE
   Total Trades:  {total_trades}
   Wins:          {wins}
   Losses:        {losses}
   Win Rate:      {win_rate:.1%}
   Total PnL:     ${total_pnl:.2f}

🏆 BEST PERFORMING SYMBOLS
"""
        for sym, stats in best_symbols:
            wr = stats['wins'] / stats['trades'] if stats['trades'] > 0 else 0
            report += f"   • {sym:15s} WR:{wr:.1%}  PnL:${stats['pnl']:+.2f}  ({stats['trades']} trades)\n"

        report += "\n⚠️  WORST PERFORMING SYMBOLS\n"
        for sym, stats in worst_symbols:
            wr = stats['wins'] / stats['trades'] if stats['trades'] > 0 else 0
            report += f"   • {sym:15s} WR:{wr:.1%}  PnL:${stats['pnl']:+.2f}  ({stats['trades']} trades)\n"

        report += "\n🎯 BEST STRATEGIES\n"
        for strat, stats in best_strategies:
            wr = stats['wins'] / stats['trades'] if stats['trades'] > 0 else 0
            report += f"   • {strat:20s} WR:{wr:.1%}  PnL:${stats['pnl']:+.2f}  ({stats['trades']} trades)\n"

        report += "\n❌ WORST STRATEGIES\n"
        for strat, stats in worst_strategies:
            wr = stats['wins'] / stats['trades'] if stats['trades'] > 0 else 0
            report += f"   • {strat:20s} WR:{wr:.1%}  PnL:${stats['pnl']:+.2f}  ({stats['trades']} trades)\n"

        # Recommendations
        report += "\n💡 RECOMMENDATIONS\n"

        # Blacklist recommendations
        for sym, stats in symbol_stats.items():
            if stats['trades'] >= 10 and stats['wins'] / stats['trades'] < 0.40:
                report += f"   ⚠ Consider blacklisting {sym} (WR: {stats['wins']/stats['trades']:.1%})\n"

        # Strategy recommendations
        for strat, stats in strategy_stats.items():
            if stats['trades'] >= 10 and stats['wins'] / stats['trades'] < 0.40:
                report += f"   ⚠ Reduce usage of {strat} strategy (WR: {stats['wins']/stats['trades']:.1%})\n"

        if win_rate < 0.45:
            report += "   ⚠ Overall win rate below 45% - consider tightening entry criteria\n"

        if total_pnl < 0:
            report += "   ⚠ Negative PnL this week - review risk management settings\n"

        report += "\n═══════════════════════════════════════════════════════════\n"

        # Save report to file
        report_file = f"performance_report_{datetime.now().strftime('%Y%m%d')}.txt"
        try:
            with open(report_file, 'w') as f:
                f.write(report)
            logger.info(f"[Adaptive IQ] Report saved to {report_file}")
        except Exception as e:
            logger.error(f"[Adaptive IQ] Could not save report: {e}")

        self.last_report_time = now
        return report

    def check_and_generate_report(self) -> Optional[str]:
        """Check if it's time for a weekly report and generate if needed."""
        if time.time() - self.last_report_time > self.report_interval:
            return self.generate_performance_report()
        return None

    # ── BTC CORRELATION INSIGHTS ──────────────────────────────

    def get_btc_correlation_advice(self, symbol: str, btc_trend: str) -> Tuple[bool, str]:
        """
        Get advice on trading a symbol given current BTC trend.
        
        Returns: (should_trade: bool, advice: str)
        """
        key = f"{symbol}_{btc_trend}"
        corr_data = self.btc_correlations.get(key)

        if not corr_data or corr_data['trades'] < 5:
            return True, f"No correlation data for {symbol} when BTC is {btc_trend}"

        win_rate = corr_data['wins'] / corr_data['trades']

        if win_rate < 0.35:
            return False, f"Avoid {symbol} when BTC is {btc_trend} (WR: {win_rate:.1%})"

        if win_rate > 0.60:
            return True, f"Strong setup: {symbol} when BTC is {btc_trend} (WR: {win_rate:.1%})"

        return True, f"Neutral: {symbol} when BTC is {btc_trend} (WR: {win_rate:.1%})"

    # ── PARAMETER OPTIMIZATION SUGGESTIONS ────────────────────

    def get_parameter_suggestions(self) -> Dict:
        """
        Analyze recent trades and suggest parameter adjustments.
        
        Returns dict with recommended changes.
        """
        if len(self.recent_trades) < 20:
            return {}

        recent = self.recent_trades[-50:]

        # Analyze average winning vs losing trade duration
        win_durations = []
        loss_durations = []

        for t in recent:
            # Would need duration tracking - simplified version
            if t['won']:
                pass  # Would track actual duration
            else:
                pass

        # Suggest TP/SL adjustments based on actual outcomes
        avg_win_pct = np.mean([t['pnl'] for t in recent if t['won']]) if any(t['won'] for t in recent) else 0
        avg_loss_pct = abs(np.mean([t['pnl'] for t in recent if not t['won']])) if any(not t['won'] for t in recent) else 0

        suggestions = {}

        if avg_win_pct > 0 and avg_loss_pct > 0:
            current_rr = avg_win_pct / avg_loss_pct
            if current_rr < 1.5:
                suggestions['take_profit_percent'] = 'Consider increasing TP or tightening SL for better R:R'
            elif current_rr > 3.0:
                suggestions['take_profit_percent'] = 'Consider taking profits earlier (R:R very high)'

        # Win rate analysis
        overall_wr = sum(1 for t in recent if t['won']) / len(recent)
        if overall_wr < 0.40:
            suggestions['min_signal_score'] = 'Increase minimum signal threshold (current WR too low)'
        elif overall_wr > 0.65:
            suggestions['min_signal_score'] = 'Could potentially lower signal threshold (WR very strong)'

        return suggestions

    # ── SUMMARY FOR DASHBOARD ─────────────────────────────────

    def get_learning_summary(self) -> Dict:
        """Get concise summary of learning state for dashboard display."""
        top_strats = self.get_best_strategies(limit=3)

        preferred_syms = self.get_preferred_symbols(limit=5)

        blacklisted_count = sum(1 for s in self.symbol_performance.values() if s.get('blacklisted', False))

        regime = self.current_regime

        if self.recent_trades:
            recent_wr = sum(1 for t in self.recent_trades[-20:] if t['won']) / min(len(self.recent_trades), 20)
        else:
            recent_wr = 0

        edge_scores = self.get_edge_quality_scores()

        return {
            'top_strategies': top_strats,
            'preferred_symbols': preferred_syms,
            'blacklisted_symbols': blacklisted_count,
            'current_regime': regime,
            'recent_win_rate': recent_wr,
            'total_trades_tracked': len(self.recent_trades),
            'edge_quality_scores': edge_scores,
        }

    def get_edge_quality_scores(self) -> Dict[str, float]:
        """
        Calculate edge score = total_profit / total_trades for each strategy.
        Returns dict of strategy -> edge score.
        """
        edge_scores = {}

        for strat_name, perf in self.strategy_performance.items():
            if perf['trades'] > 0:
                edge_scores[strat_name] = perf['total_pnl'] / perf['trades']
            else:
                edge_scores[strat_name] = 0.0

        return edge_scores

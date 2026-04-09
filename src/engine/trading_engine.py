import time
import yaml
import os
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, Optional
from src.utils.logger import get_logger
from src.api.kucoin_client import KuCoinClient
from src.api.websocket_client import WebSocketClient
from src.strategy.trend_following import TrendFollowingStrategy
from src.risk.risk_manager import RiskManager, PositionInfo
from src.risk.advanced_risk_manager import AdvancedRiskManager
from src.learning.trade_journal import TradeJournal
from src.learning.performance_analyzer import PerformanceAnalyzer
from src.ml.price_predictor import PricePredictor
from src.learning.parameter_optimizer import ParameterOptimizer

logger = get_logger(__name__)

class TradingEngine:
    """
    Enhanced trading engine with self-learning capabilities.
    Integrates ML predictions, real-time WebSocket data, and adaptive parameter optimization.
    """
    
    def __init__(self, config_path: str = 'config/config.yaml'):
        # Load configuration
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
        
        # Initialize API clients
        self.client = KuCoinClient()
        self.websocket = None
        
        # Initialize strategy
        self.strategy = TrendFollowingStrategy(self.config)
        
        # Initialize risk managers
        self.risk_manager = RiskManager(
            max_position_size=self.config.get('max_position_size', 1000),
            stop_loss_percent=self.config.get('stop_loss_percent', 2.0),
            take_profit_percent=self.config.get('take_profit_percent', 5.0),
            max_leverage=self.config.get('leverage', 10)
        )
        self.advanced_risk = AdvancedRiskManager(self.config)
        
        # Initialize learning components
        self.journal = TradeJournal(db_path=self.config.get('journal_db_path', 'trading_journal.db'))
        self.price_predictor = None
        self.param_optimizer = None
        
        # ML configuration
        self.ml_enabled = self.config.get('ml_enabled', True)
        if self.ml_enabled:
            try:
                self.price_predictor = PricePredictor(
                    model_type=self.config.get('ml_model_type', 'random_forest'),
                    n_features=self.config.get('ml_feature_count', 10)
                )
                logger.info("ML price predictor initialized")
            except Exception as e:
                logger.error(f"Failed to initialize ML predictor: {e}")
                self.ml_enabled = False
        
        # Configuration
        self.symbol = self.config.get('symbol', 'XBTUSDTM')
        self.timeframe = self.config.get('timeframe', '5m')
        self.check_interval = self.config.get('check_interval', 30)
        self.learning_enabled = self.config.get('learning_enabled', True)
        self.optimization_interval = self.config.get('optimization_interval', 100)
        self.min_trades_for_optimization = self.config.get('min_trades_for_optimization', 20)
        
        # WebSocket configuration
        self.websocket_enabled = self.config.get('websocket_enabled', True)
        
        # Performance tracking
        self.cycle_count = 0
        self.last_optimization_trade_count = 0
        self.is_running = False
        
    def initialize(self):
        """Initialize trading engine components."""
        # Set leverage
        leverage = self.config.get('leverage', 10)
        self.client.set_leverage(self.symbol, leverage)
        
        # Initialize WebSocket if enabled
        if self.websocket_enabled:
            try:
                self._init_websocket()
            except Exception as e:
                logger.warning(f"WebSocket initialization failed: {e}, falling back to REST polling")
                self.websocket_enabled = False
        
        logger.info(f"Trading engine initialized for {self.symbol} on {self.timeframe}")
        logger.info(f"Learning enabled: {self.learning_enabled}, ML enabled: {self.ml_enabled}")
    
    def _init_websocket(self):
        """Initialize WebSocket connection for real-time data."""
        self.websocket = WebSocketClient(symbol=self.symbol)
        self.websocket.connect()
        logger.info("WebSocket connected for real-time data")
    
    def fetch_market_data(self) -> Optional[pd.DataFrame]:
        """
        Fetch market data from WebSocket or REST API.
        
        Returns:
            DataFrame with OHLCV data
        """
        # Try WebSocket first if available
        if self.websocket and self.websocket.is_connected():
            candles = self.websocket.get_latest_candles(count=100)
            if candles and len(candles) > 0:
                # Convert WebSocket format to DataFrame
                df = pd.DataFrame(candles)
                df.rename(columns={
                    'time': 'timestamp',
                    'open': 'open',
                    'high': 'high',
                    'low': 'low',
                    'close': 'close',
                    'volume': 'volume'
                }, inplace=True)
                return df
        
        # Fallback to REST API
        df = self.client.fetch_ohlcv(self.symbol, self.timeframe)
        return df
    
    def fetch_higher_timeframe_data(self) -> Dict:
        """Fetch data from higher timeframes for multi-timeframe analysis."""
        if not self.config.get('multi_timeframe_enabled', True):
            return {}
        
        higher_tf_data = {}
        
        # Fetch 15m data
        try:
            df_15m = self.client.fetch_ohlcv(self.symbol, '15m')
            if df_15m is not None and not df_15m.empty:
                higher_tf_data['15m'] = df_15m
        except Exception as e:
            logger.error(f"Failed to fetch 15m data: {e}")
        
        # Fetch 1h data
        try:
            df_1h = self.client.fetch_ohlcv(self.symbol, '1h')
            if df_1h is not None and not df_1h.empty:
                higher_tf_data['1h'] = df_1h
        except Exception as e:
            logger.error(f"Failed to fetch 1h data: {e}")
        
        return higher_tf_data
    
    def get_ml_prediction(self, df: pd.DataFrame) -> Dict:
        """
        Get ML-based price prediction.
        
        Args:
            df: OHLCV DataFrame
        
        Returns:
            Prediction dictionary
        """
        if not self.ml_enabled or not self.price_predictor:
            return {'prediction': 'hold', 'confidence': 0.0}
        
        # Check if model is trained
        if not self.price_predictor.is_trained:
            # Try to train with historical data
            if len(df) >= 100:
                logger.info("Training ML model with historical data...")
                try:
                    metrics = self.price_predictor.train(df)
                    logger.info(f"ML model trained: {metrics.get('accuracy', 0):.2%} accuracy")
                except Exception as e:
                    logger.error(f"Failed to train ML model: {e}")
                    return {'prediction': 'hold', 'confidence': 0.0}
            else:
                return {'prediction': 'hold', 'confidence': 0.0}
        
        # Get prediction
        try:
            prediction = self.price_predictor.predict(df)
            return prediction
        except Exception as e:
            logger.error(f"ML prediction failed: {e}")
            return {'prediction': 'hold', 'confidence': 0.0}
    
    def analyze_market(self) -> Dict:
        """
        Comprehensive market analysis combining strategy signals and ML predictions.
        
        Returns:
            Analysis dictionary with signal, strength, and reasoning
        """
        # Fetch market data
        df = self.fetch_market_data()
        if df is None or df.empty:
            logger.warning("No market data available")
            return {'signal': 'hold', 'strength': 0, 'reason': 'No market data'}
        
        # Fetch higher timeframe data
        higher_tf_data = self.fetch_higher_timeframe_data()
        
        # Get strategy signal
        strategy_signal = self.strategy.analyze(df, higher_tf_data)
        
        # Get ML prediction
        ml_prediction = self.get_ml_prediction(df)
        
        # Combine signals
        final_signal = self._combine_signals(strategy_signal, ml_prediction)
        
        # Add market regime info
        final_signal['market_regime'] = self.strategy.get_market_regime()
        final_signal['ml_prediction'] = ml_prediction
        
        return final_signal
    
    def _combine_signals(self, strategy_signal: Dict, ml_prediction: Dict) -> Dict:
        """
        Combine strategy signal with ML prediction.
        
        Args:
            strategy_signal: Signal from technical strategy
            ml_prediction: ML-based prediction
        
        Returns:
            Combined signal
        """
        # If strategy says hold, respect it
        if strategy_signal['signal'] == 'hold':
            return strategy_signal
        
        # If ML is disabled, use strategy signal
        if not self.ml_enabled or ml_prediction['prediction'] == 'hold':
            return strategy_signal
        
        # Check if ML agrees with strategy
        ml_agrees = False
        if strategy_signal['signal'] == 'buy' and ml_prediction['prediction'] == 'up':
            ml_agrees = True
        elif strategy_signal['signal'] == 'sell' and ml_prediction['prediction'] == 'down':
            ml_agrees = True
        
        # Adjust strength based on ML agreement
        if ml_agrees and ml_prediction['confidence'] > self.config.get('ml_confidence_threshold', 0.6):
            # Boost signal strength
            boosted_strength = min(strategy_signal['strength'] + 2, 10)
            strategy_signal['strength'] = boosted_strength
            strategy_signal['reason'] += f', ML confirms ({ml_prediction["confidence"]:.0%})'
        else:
            # Reduce strength if ML disagrees or low confidence
            reduced_strength = max(strategy_signal['strength'] - 2, 0)
            strategy_signal['strength'] = reduced_strength
            strategy_signal['reason'] += f', ML uncertain ({ml_prediction["prediction"]}, {ml_prediction["confidence"]:.0%})'
        
        return strategy_signal
    
    def execute_trade(self, signal: Dict):
        """
        Execute trade with advanced risk management and journaling.
        """
        if signal['signal'] == 'hold':
            logger.info(f"Signal: HOLD - {signal['reason']}")
            return
        
        logger.info(f"Trade signal: {signal['signal'].upper()} (Strength: {signal['strength']}/10)")
        logger.info(f"Reason: {signal['reason']}")
        
        # Fetch balance and current price
        balance_info = self.client.fetch_balance()
        if balance_info is None:
            logger.error("Cannot fetch balance, skipping trade")
            return
        
        usdt_balance = balance_info.get('USDT', {}).get('total', 0)
        
        ticker = self.client.fetch_ticker(self.symbol)
        if ticker is None:
            logger.error("Cannot fetch ticker, skipping trade")
            return
        
        current_price = ticker['last']
        
        # Check circuit breakers
        if self.advanced_risk.should_stop_trading(usdt_balance):
            logger.error("Circuit breaker triggered! Trading halted.")
            return
        
        # Calculate position size
        df = self.fetch_market_data()
        if df is not None and not df.empty:
            self.advanced_risk.update_atr(df)
            atr = self.advanced_risk.get_current_atr()
        else:
            atr = None
        
        stop_loss = self.advanced_risk.calculate_stop_loss(current_price, signal['signal'], atr)
        take_profit = self.advanced_risk.calculate_take_profit(current_price, signal['signal'])
        
        position_size = self.advanced_risk.calculate_position_size(
            usdt_balance, current_price, stop_loss, signal['strength']
        )
        
        if position_size <= 0:
            logger.warning("Invalid position size, skipping trade")
            return
        
        # Check if we already have an open position
        existing_position = self.client.fetch_position(self.symbol)
        if existing_position and existing_position.get('contracts', 0) != 0:
            logger.warning("Position already open, skipping new trade")
            return
        
        # Execute order
        try:
            if signal['signal'] == 'buy':
                order = self.client.create_order(
                    symbol=self.symbol,
                    order_type='market',
                    side='buy',
                    amount=position_size
                )
            else:  # sell
                order = self.client.create_order(
                    symbol=self.symbol,
                    order_type='market',
                    side='sell',
                    amount=position_size
                )
            
            if order:
                logger.info(f"Order executed successfully: {order.get('id', 'N/A')}")
                
                # Record in journal
                trade_data = {
                    'symbol': self.symbol,
                    'side': signal['signal'],
                    'entry_price': current_price,
                    'exit_price': None,
                    'quantity': position_size,
                    'leverage': self.config.get('leverage', 10),
                    'pnl': 0,
                    'pnl_percent': 0,
                    'signal_strength': signal['strength'],
                    'strategy_params': {
                        'ema_fast': self.config.get('ema_fast', 9),
                        'ema_slow': self.config.get('ema_slow', 21),
                        'rsi_period': self.config.get('rsi_period', 14),
                        'market_regime': signal.get('market_regime', 'unknown')
                    },
                    'exit_reason': None,
                    'duration_minutes': 0,
                    'max_profit': 0,
                    'max_drawdown': 0
                }
                
                # Open in risk manager
                self.advanced_risk.open_trade({
                    **trade_data,
                    'stop_loss': stop_loss,
                    'take_profit': take_profit
                })
                
                logger.info(f"Trade recorded: {signal['signal']} {position_size:.6f} @ {current_price:.2f}")
                logger.info(f"Stop Loss: {stop_loss:.2f}, Take Profit: {take_profit:.2f}")
            else:
                logger.error("Order execution failed")
        
        except Exception as e:
            logger.error(f"Trade execution error: {e}")
    
    def monitor_open_position(self):
        """Monitor and manage open position with trailing stops and exits."""
        position = self.client.fetch_position(self.symbol)
        
        if position is None or position.get('contracts', 0) == 0:
            return
        
        ticker = self.client.fetch_ticker(self.symbol)
        if ticker is None:
            return
        
        current_price = ticker['last']
        
        # Update position tracking
        self.advanced_risk.update_position_tracking(current_price)
        
        # Update trailing stop
        if self.advanced_risk.open_position:
            new_stop = self.advanced_risk.update_trailing_stop(
                current_price,
                self.advanced_risk.open_position['side']
            )
            if new_stop:
                logger.info(f"Trailing stop updated to: {new_stop:.2f}")
        
        # Check for exit conditions
        if self.advanced_risk.check_stop_loss_triggered(current_price):
            logger.info("Stop loss triggered! Closing position...")
            self._close_position(current_price, 'stop_loss')
        elif self.advanced_risk.check_take_profit_triggered(current_price):
            logger.info("Take profit triggered! Closing position...")
            self._close_position(current_price, 'take_profit')
        
        # Check for opposite signal (exit on signal reversal)
        if self.config.get('exit_on_opposite_signal', True):
            current_side = self.advanced_risk.open_position['side'] if self.advanced_risk.open_position else None
            if current_side:
                analysis = self.analyze_market()
                opposite_signal = (
                    (current_side == 'buy' and analysis['signal'] == 'sell') or
                    (current_side == 'sell' and analysis['signal'] == 'buy')
                )
                if opposite_signal and analysis['strength'] >= 7:
                    logger.info(f"Opposite signal detected ({analysis['signal']}), closing position...")
                    self._close_position(current_price, 'opposite_signal')
    
    def _close_position(self, exit_price: float, exit_reason: str):
        """
        Close open position and record in journal.
        
        Args:
            exit_price: Exit price
            exit_reason: Reason for closing
        """
        if not self.advanced_risk.open_position:
            return
        
        position = self.advanced_risk.open_position
        side = position['side']
        
        # Execute close order
        try:
            close_side = 'sell' if side == 'buy' else 'buy'
            order = self.client.create_order(
                symbol=self.symbol,
                order_type='market',
                side=close_side,
                amount=abs(position['quantity'])
            )
            
            if order:
                # Record trade result
                trade_result = self.advanced_risk.close_trade(exit_price, exit_reason)
                
                # Save to journal
                if trade_result:
                    self.journal.record_trade(trade_result)
                    logger.info(f"Trade journal updated: {exit_reason} | PnL: ${trade_result['pnl']:.2f}")
                
                # Check if optimization is needed
                if self.learning_enabled:
                    self._check_and_optimize()
            else:
                logger.error("Failed to close position")
        
        except Exception as e:
            logger.error(f"Error closing position: {e}")
    
    def _check_and_optimize(self):
        """Check if parameter optimization should run and execute if needed."""
        stats = self.advanced_risk.get_daily_stats()
        total_trades = stats['total_trades']
        
        # Check if enough trades have occurred
        if total_trades - self.last_optimization_trade_count < self.optimization_interval:
            return
        
        if total_trades < self.min_trades_for_optimization:
            return
        
        logger.info(f"Running parameter optimization after {total_trades} trades...")
        
        try:
            # Get trade statistics
            trade_stats = self.journal.get_trade_statistics(self.symbol)
            
            if trade_stats['total_trades'] < self.min_trades_for_optimization:
                logger.info("Not enough trades in journal for optimization")
                return
            
            # Get all trades
            all_trades = self.journal.get_all_trades(self.symbol)
            
            # Initialize optimizer
            param_ranges = {
                'ema_fast': [7, 9, 11, 13, 15],
                'ema_slow': [18, 21, 24, 27, 30],
                'rsi_period': [10, 12, 14, 16, 18]
            }
            
            optimizer = ParameterOptimizer(all_trades, param_ranges)
            
            # Get recommendations
            current_params = {
                'ema_fast': self.config.get('ema_fast', 9),
                'ema_slow': self.config.get('ema_slow', 21),
                'rsi_period': self.config.get('rsi_period', 14)
            }
            
            recommended = optimizer.recommend_params(current_params)
            
            logger.info(f"Current params: {current_params}")
            logger.info(f"Recommended params: {recommended}")
            
            # Apply recommendations (with user confirmation in production)
            if recommended != current_params:
                logger.info("Auto-updating parameters...")
                self.config.update(recommended)
                
                # Reinitialize strategy with new params
                self.strategy = TrendFollowingStrategy(self.config)
                
                # Save to journal
                self.journal.save_strategy_params(self.symbol, recommended, trade_stats['win_rate'])
                
                logger.info("Parameters updated successfully!")
            
            self.last_optimization_trade_count = total_trades
        
        except Exception as e:
            logger.error(f"Optimization failed: {e}")
    
    def print_performance_report(self):
        """Print comprehensive performance report."""
        stats = self.journal.get_trade_statistics(self.symbol)
        
        if stats['total_trades'] == 0:
            logger.info("No trades recorded yet")
            return
        
        logger.info("=" * 60)
        logger.info("PERFORMANCE REPORT")
        logger.info("=" * 60)
        logger.info(f"Total Trades: {stats['total_trades']}")
        logger.info(f"Winning Trades: {stats['winning_trades']}")
        logger.info(f"Losing Trades: {stats['losing_trades']}")
        logger.info(f"Win Rate: {stats['win_rate']:.2f}%")
        logger.info(f"Average Win: ${stats['avg_win']:.2f}")
        logger.info(f"Average Loss: ${stats['avg_loss']:.2f}")
        logger.info(f"Profit Factor: {stats['profit_factor']:.2f}")
        logger.info(f"Total PnL: ${stats['total_pnl']:.2f}")
        logger.info("=" * 60)
        
        # Print daily stats
        daily_stats = self.advanced_risk.get_daily_stats()
        logger.info(f"Today's PnL: ${daily_stats['daily_pnl']:.2f}")
        logger.info(f"Today's Trades: {daily_stats['daily_trades']}")
        logger.info(f"Today's Win Rate: {daily_stats['daily_win_rate']:.2f}%")
    
    def run_cycle(self):
        """Run one complete trading cycle."""
        self.cycle_count += 1
        
        logger.info(f"\n{'='*60}")
        logger.info(f"Trading Cycle #{self.cycle_count} - {datetime.now()}")
        logger.info(f"{'='*60}")
        
        try:
            # Check for open position first
            self.monitor_open_position()
            
            # Analyze market
            analysis = self.analyze_market()
            
            if analysis['signal'] != 'hold':
                logger.info(f"Signal: {analysis['signal'].upper()}")
                logger.info(f"Strength: {analysis['strength']}/10")
                logger.info(f"Reason: {analysis['reason']}")
                logger.info(f"Market Regime: {analysis.get('market_regime', 'unknown')}")
                
                # Execute trade
                self.execute_trade(analysis)
            else:
                logger.info(f"No trade signal: {analysis['reason']}")
            
            # Print performance report periodically
            report_interval = self.config.get('performance_report_interval', 3600)
            if self.cycle_count % (report_interval // self.check_interval) == 0:
                self.print_performance_report()
        
        except Exception as e:
            logger.error(f"Error in trading cycle: {e}", exc_info=True)
    
    def start(self):
        """Start the trading engine."""
        self.is_running = True
        self.initialize()
        
        logger.info(f"Starting trading engine for {self.symbol}")
        logger.info(f"Timeframe: {self.timeframe}, Check interval: {self.check_interval}s")
        logger.info(f"Learning: {self.learning_enabled}, ML: {self.ml_enabled}")
        
        try:
            while self.is_running:
                self.run_cycle()
                time.sleep(self.check_interval)
        
        except KeyboardInterrupt:
            logger.info("Trading engine stopped by user")
            self.stop()
        
        except Exception as e:
            logger.error(f"Trading engine error: {e}", exc_info=True)
            self.stop()
    
    def stop(self):
        """Stop the trading engine."""
        logger.info("Stopping trading engine...")
        self.is_running = False
        
        # Close WebSocket
        if self.websocket:
            self.websocket.disconnect()
        
        # Print final report
        self.print_performance_report()
        
        logger.info("Trading engine stopped")

#!/usr/bin/env python3
"""
KuCoin Self-Improving 5-Minute Scalping Trading Agent

A sophisticated trading bot with:
- 5-minute scalping strategy
- Machine learning price predictions
- Self-learning and parameter optimization
- Advanced risk management with trailing stops
- Real-time WebSocket data
- Comprehensive performance tracking
"""

import os
import sys
import signal
import argparse
from dotenv import load_dotenv

load_dotenv()

from src.engine.trading_engine import TradingEngine
from src.utils.logger import setup_logger

# Global reference for signal handler
trading_engine = None

def signal_handler(sig, frame):
    """Handle Ctrl+C gracefully."""
    print("\n\nShutdown signal received...")
    if trading_engine:
        trading_engine.stop()
    sys.exit(0)

def main():
    global trading_engine
    
    # Parse command-line arguments
    parser = argparse.ArgumentParser(
        description='KuCoin Self-Improving Scalping Trading Agent',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                          # Start with default config
  python main.py --config custom.yaml     # Use custom config
  python main.py --symbol ETH-USDT        # Trade ETH instead of BTC
  python main.py --paper                  # Paper trading mode (sandbox)
  python main.py --backtest               # Run backtest mode
        """
    )
    
    parser.add_argument(
        '--config', '-c',
        default='config/config.yaml',
        help='Path to configuration file (default: config/config.yaml)'
    )
    
    parser.add_argument(
        '--symbol', '-s',
        default=None,
        help='Trading symbol (e.g., BTC-USDT-M, ETH-USDT-M)'
    )
    
    parser.add_argument(
        '--timeframe', '-t',
        default=None,
        choices=['1m', '3m', '5m', '15m', '30m', '1h'],
        help='Candlestick timeframe'
    )
    
    parser.add_argument(
        '--interval', '-i',
        type=int,
        default=None,
        help='Check interval in seconds (overrides config)'
    )
    
    parser.add_argument(
        '--paper', '-p',
        action='store_true',
        help='Enable paper trading (sandbox mode)'
    )
    
    parser.add_argument(
        '--backtest', '-b',
        action='store_true',
        help='Run in backtest mode (not yet implemented)'
    )
    
    parser.add_argument(
        '--show-report', '-r',
        action='store_true',
        help='Show performance report and exit'
    )
    
    args = parser.parse_args()
    
    # Setup logging
    logger = setup_logger()
    
    # Print banner
    print("=" * 70)
    print("  KuCoin Self-Improving 5-Minute Scalping Trading Agent")
    print("  With ML Predictions & Adaptive Learning")
    print("=" * 70)
    print()
    
    # Check config file
    config_path = args.config
    if not os.path.exists(config_path):
        print(f"❌ Error: Configuration file '{config_path}' not found.")
        print(f"   Please ensure the file exists or specify with --config")
        sys.exit(1)
    
    print(f"✓ Config: {config_path}")
    
    # Register signal handler for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Initialize trading engine
    try:
        trading_engine = TradingEngine(config_path=config_path)
        
        # Override config with command-line arguments
        if args.symbol:
            trading_engine.symbol = args.symbol
            print(f"✓ Symbol override: {args.symbol}")
        
        if args.timeframe:
            trading_engine.timeframe = args.timeframe
            print(f"✓ Timeframe override: {args.timeframe}")
        
        if args.paper:
            print("✓ Paper trading mode enabled (sandbox)")
        
        # Show report mode
        if args.show_report:
            print("\n📊 Performance Report:")
            trading_engine.print_performance_report()
            sys.exit(0)
        
        # Backtest mode (placeholder)
        if args.backtest:
            print("\n⚠️  Backtest mode not yet implemented")
            print("   Coming soon: Historical backtesting with performance metrics")
            sys.exit(0)
        
        # Get check interval
        check_interval = args.interval or trading_engine.check_interval
        
        print(f"\n{'='*70}")
        print(f"  Starting Trading Engine")
        print(f"{'='*70}")
        print(f"  Symbol:        {trading_engine.symbol}")
        print(f"  Timeframe:     {trading_engine.timeframe}")
        print(f"  Check Interval: {check_interval}s")
        print(f"  Learning:      {'Enabled' if trading_engine.learning_enabled else 'Disabled'}")
        print(f"  ML Predictions:{'Enabled' if trading_engine.ml_enabled else 'Disabled'}")
        print(f"  WebSocket:     {'Enabled' if trading_engine.websocket_enabled else 'Disabled'}")
        print(f"{'='*70}")
        print()
        print("Press Ctrl+C to stop\n")
        
        # Start trading
        trading_engine.start()
    
    except KeyboardInterrupt:
        print("\n\nShutdown requested...")
        if trading_engine:
            trading_engine.stop()
    
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)

if __name__ == '__main__':
    main()

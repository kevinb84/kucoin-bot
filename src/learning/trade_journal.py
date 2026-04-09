import sqlite3
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from pathlib import Path
import json

class TradeJournal:
    """Persistent storage for all trades with performance tracking."""
    
    def __init__(self, db_path: str = "trading_journal.db"):
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """Create database tables if they don't exist."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                entry_price REAL NOT NULL,
                exit_price REAL,
                quantity REAL NOT NULL,
                leverage INTEGER DEFAULT 1,
                pnl REAL DEFAULT 0,
                pnl_percent REAL DEFAULT 0,
                signal_strength REAL,
                strategy_params TEXT,
                exit_reason TEXT,
                duration_minutes REAL,
                max_profit REAL,
                max_drawdown REAL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS strategy_params (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                symbol TEXT NOT NULL,
                params TEXT NOT NULL,
                performance_score REAL,
                win_rate REAL,
                total_trades INTEGER DEFAULT 0
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS market_conditions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                symbol TEXT NOT NULL,
                timeframe TEXT,
                volatility REAL,
                trend_strength REAL,
                volume_profile REAL
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def record_trade(self, trade_data: Dict):
        """Record a completed trade in the journal."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO trades (
                timestamp, symbol, side, entry_price, exit_price,
                quantity, leverage, pnl, pnl_percent, signal_strength,
                strategy_params, exit_reason, duration_minutes,
                max_profit, max_drawdown
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            trade_data.get('timestamp', datetime.now().isoformat()),
            trade_data['symbol'],
            trade_data['side'],
            trade_data['entry_price'],
            trade_data.get('exit_price'),
            trade_data['quantity'],
            trade_data.get('leverage', 1),
            trade_data.get('pnl', 0),
            trade_data.get('pnl_percent', 0),
            trade_data.get('signal_strength'),
            json.dumps(trade_data.get('strategy_params', {})),
            trade_data.get('exit_reason'),
            trade_data.get('duration_minutes'),
            trade_data.get('max_profit'),
            trade_data.get('max_drawdown')
        ))
        
        conn.commit()
        conn.close()
    
    def get_recent_trades(self, symbol: str, limit: int = 100) -> List[Dict]:
        """Get recent trades for a symbol."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM trades 
            WHERE symbol = ? 
            ORDER BY timestamp DESC 
            LIMIT ?
        ''', (symbol, limit))
        
        trades = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return trades
    
    def get_winning_trades(self, symbol: str, limit: int = 50) -> List[Dict]:
        """Get winning trades for analysis."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM trades 
            WHERE symbol = ? AND pnl > 0
            ORDER BY timestamp DESC 
            LIMIT ?
        ''', (symbol, limit))
        
        trades = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return trades
    
    def get_losing_trades(self, symbol: str, limit: int = 50) -> List[Dict]:
        """Get losing trades for analysis."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM trades 
            WHERE symbol = ? AND pnl <= 0
            ORDER BY timestamp DESC 
            LIMIT ?
        ''', (symbol, limit))
        
        trades = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return trades
    
    def get_trade_statistics(self, symbol: str) -> Dict:
        """Calculate basic trade statistics."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT 
                COUNT(*) as total_trades,
                SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as winning_trades,
                SUM(CASE WHEN pnl <= 0 THEN 1 ELSE 0 END) as losing_trades,
                AVG(pnl) as avg_pnl,
                SUM(pnl) as total_pnl,
                AVG(CASE WHEN pnl > 0 THEN pnl ELSE NULL END) as avg_win,
                AVG(CASE WHEN pnl <= 0 THEN pnl ELSE NULL END) as avg_loss,
                MAX(pnl) as max_win,
                MIN(pnl) as max_loss
            FROM trades
            WHERE symbol = ?
        ''', (symbol,))
        
        row = cursor.fetchone()
        conn.close()
        
        if row[0] == 0:
            return {
                'total_trades': 0,
                'winning_trades': 0,
                'losing_trades': 0,
                'win_rate': 0,
                'avg_pnl': 0,
                'total_pnl': 0,
                'avg_win': 0,
                'avg_loss': 0,
                'profit_factor': 0,
                'max_win': 0,
                'max_loss': 0
            }
        
        win_rate = (row[1] / row[0]) * 100 if row[0] > 0 else 0
        profit_factor = abs(row[5] / row[6]) if row[6] != 0 else 0
        
        return {
            'total_trades': row[0],
            'winning_trades': row[1],
            'losing_trades': row[2],
            'win_rate': win_rate,
            'avg_pnl': row[3],
            'total_pnl': row[4],
            'avg_win': row[5],
            'avg_loss': row[6],
            'profit_factor': profit_factor,
            'max_win': row[7],
            'max_loss': row[8]
        }
    
    def save_strategy_params(self, symbol: str, params: Dict, performance_score: float = None):
        """Save strategy parameters with performance score."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        stats = self.get_trade_statistics(symbol)
        
        cursor.execute('''
            INSERT INTO strategy_params (symbol, params, performance_score, win_rate, total_trades)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            symbol,
            json.dumps(params),
            performance_score,
            stats['win_rate'],
            stats['total_trades']
        ))
        
        conn.commit()
        conn.close()
    
    def get_best_params(self, symbol: str, limit: int = 5) -> List[Dict]:
        """Get best performing strategy parameters."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM strategy_params
            WHERE symbol = ?
            ORDER BY performance_score DESC
            LIMIT ?
        ''', (symbol, limit))
        
        params = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return params
    
    def record_market_condition(self, symbol: str, timeframe: str, 
                                 volatility: float, trend_strength: float, 
                                 volume_profile: float):
        """Record market conditions for later analysis."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO market_conditions (symbol, timeframe, volatility, trend_strength, volume_profile)
            VALUES (?, ?, ?, ?, ?)
        ''', (symbol, timeframe, volatility, trend_strength, volume_profile))
        
        conn.commit()
        conn.close()
    
    def get_all_trades(self, symbol: str = None) -> List[Dict]:
        """Get all trades, optionally filtered by symbol."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        if symbol:
            cursor.execute('SELECT * FROM trades WHERE symbol = ? ORDER BY timestamp', (symbol,))
        else:
            cursor.execute('SELECT * FROM trades ORDER BY timestamp')
        
        trades = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return trades

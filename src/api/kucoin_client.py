import ccxt
import os
import time
import traceback
from dotenv import load_dotenv
import pandas as pd

load_dotenv()

# KuCoin Futures ccxt unified symbol format
SYMBOL_MAP = {
    'XBTUSDTM':   'BTC/USDT:USDT',
    'ETHUSDTM':   'ETH/USDT:USDT',
    'SOLUSDTM':   'SOL/USDT:USDT',
    'XRPUSDTM':   'XRP/USDT:USDT',
    'DOGEUSDTM':  'DOGE/USDT:USDT',
    'ADAUSDTM':   'ADA/USDT:USDT',
    'MATICUSDTM': 'MATIC/USDT:USDT',
    'DOTUSDTM':   'DOT/USDT:USDT',
}

def to_ccxt_symbol(symbol: str) -> str:
    return SYMBOL_MAP.get(symbol, symbol)


class KuCoinClient:
    def __init__(self):
        self.exchange = ccxt.kucoinfutures({
            'apiKey':   os.getenv('KUCOIN_API_KEY'),
            'secret':   os.getenv('KUCOIN_API_SECRET'),
            'password': os.getenv('KUCOIN_API_PASSPHRASE'),
            'enableRateLimit': True,
        })
        self._margin_mode = None  # cached margin mode

    # ── MARKET DATA ───────────────────────────────────────────

    def fetch_ohlcv(self, symbol, timeframe, limit=100):
        try:
            ccxt_symbol = to_ccxt_symbol(symbol)
            ohlcv = self.exchange.fetch_ohlcv(ccxt_symbol, timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=['timestamp','open','high','low','close','volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            return df
        except Exception as e:
            print(f"[KuCoin] fetch_ohlcv error: {e}")
            return None

    def fetch_ticker(self, symbol):
        try:
            ccxt_symbol = to_ccxt_symbol(symbol)
            return self.exchange.fetch_ticker(ccxt_symbol)
        except Exception as e:
            print(f"[KuCoin] fetch_ticker error: {e}")
            return None

    # ── ACCOUNT ───────────────────────────────────────────────

    def get_margin_mode(self, symbol) -> str:
        """Fetch the actual margin mode set on the account for this symbol."""
        try:
            if self._margin_mode:
                return self._margin_mode
            ccxt_symbol = to_ccxt_symbol(symbol)
            result = self.exchange.fetch_margin_mode(ccxt_symbol)
            mode = result.get('marginMode', 'isolated').lower()
            self._margin_mode = mode
            print(f"[KuCoin] Account margin mode: {mode}")
            return mode
        except Exception as e:
            print(f"[KuCoin] Could not fetch margin mode: {e} — defaulting to isolated")
            self._margin_mode = 'isolated'
            return 'isolated'

    def fetch_balance(self):
        try:
            raw = self.exchange.fetch_balance()
            usdt_free  = 0.0
            usdt_total = 0.0

            if 'USDT' in raw:
                usdt_free  = float(raw['USDT'].get('free',  0) or 0)
                usdt_total = float(raw['USDT'].get('total', 0) or 0)

            info = raw.get('info', {})
            if isinstance(info, dict):
                avail = info.get('availableBalance', info.get('available', 0))
                if avail:
                    usdt_free = float(avail)

            return {'USDT': {'free': usdt_free, 'total': max(usdt_total, usdt_free)}}

        except Exception as e:
            print(f"[KuCoin] fetch_balance error: {e}")
            traceback.print_exc()
            return None

    def fetch_position(self, symbol):
        try:
            ccxt_symbol = to_ccxt_symbol(symbol)
            positions = self.exchange.fetch_positions([ccxt_symbol])
            for p in positions:
                contracts = float(p.get('contracts', 0) or 0)
                if contracts != 0:
                    return p
            return None
        except Exception as e:
            print(f"[KuCoin] fetch_position error: {e}")
            return None

    def set_leverage(self, symbol, leverage):
        try:
            ccxt_symbol = to_ccxt_symbol(symbol)
            return self.exchange.set_leverage(leverage, ccxt_symbol)
        except Exception as e:
            print(f"[KuCoin] set_leverage (non-fatal): {e}")
            return None

    # ── ORDERS ────────────────────────────────────────────────

    def create_order(self, symbol, order_type, side, amount, price=None, params=None):
        """
        Place a futures market order on KuCoin.
        Auto-detects margin mode from account settings.
        """
        try:
            ccxt_symbol = to_ccxt_symbol(symbol)
            amount = max(1, int(amount))
            leverage = int(os.getenv('LEVERAGE', 10))

            # Detect account margin mode
            margin_mode = self.get_margin_mode(symbol)

            extra = {
                'leverage':   leverage,
                'hedged':     True,
                'marginMode': margin_mode,   # match account setting exactly
            }

            if params and params.get('reduceOnly'):
                extra['reduceOnly'] = True

            if params:
                for k, v in params.items():
                    if k not in ('hedged', 'marginMode'):
                        extra[k] = v

            print(f"[KuCoin] {order_type.upper()} {side.upper()} {amount}x {ccxt_symbol} | margin={margin_mode} hedged=True lev={leverage}")

            order = self.exchange.create_order(
                symbol = ccxt_symbol,
                type   = order_type,
                side   = side,
                amount = amount,
                price  = price,
                params = extra,
            )
            print(f"[KuCoin] Order OK: id={order.get('id')} status={order.get('status')}")
            return order

        except ccxt.InvalidOrder as e:
            err = str(e)
            print(f"[KuCoin] Invalid order: {err}")
            # If margin mode mismatch, flip and retry once
            if '330005' in err:
                return self._retry_opposite_margin(symbol, order_type, side, amount, price, params)
        except ccxt.InsufficientFunds as e:
            print(f"[KuCoin] Insufficient funds: {e}")
        except ccxt.AuthenticationError as e:
            print(f"[KuCoin] Auth error: {e}")
        except ccxt.NetworkError as e:
            print(f"[KuCoin] Network error: {e}")
        except Exception as e:
            print(f"[KuCoin] Order error: {e}")
            traceback.print_exc()
        return None

    def _retry_opposite_margin(self, symbol, order_type, side, amount, price, params):
        """Retry order with opposite margin mode if 330005 error."""
        try:
            ccxt_symbol = to_ccxt_symbol(symbol)
            amount  = max(1, int(amount))
            leverage = int(os.getenv('LEVERAGE', 10))

            # Flip margin mode
            current = self._margin_mode or 'isolated'
            flipped = 'cross' if current == 'isolated' else 'isolated'
            self._margin_mode = flipped  # update cache

            print(f"[KuCoin] Retrying with marginMode={flipped} ...")

            extra = {
                'leverage':   leverage,
                'hedged':     True,
                'marginMode': flipped,
            }
            if params and params.get('reduceOnly'):
                extra['reduceOnly'] = True

            order = self.exchange.create_order(
                symbol = ccxt_symbol,
                type   = order_type,
                side   = side,
                amount = amount,
                price  = price,
                params = extra,
            )
            print(f"[KuCoin] Retry OK: id={order.get('id')} status={order.get('status')}")
            return order

        except Exception as e:
            print(f"[KuCoin] Retry also failed: {e}")
            traceback.print_exc()
            return None

    def cancel_order(self, order_id, symbol):
        try:
            ccxt_symbol = to_ccxt_symbol(symbol)
            return self.exchange.cancel_order(order_id, ccxt_symbol)
        except Exception as e:
            print(f"[KuCoin] cancel_order error: {e}")
            return None

    def fetch_open_orders(self, symbol):
        try:
            ccxt_symbol = to_ccxt_symbol(symbol)
            return self.exchange.fetch_open_orders(ccxt_symbol)
        except Exception as e:
            print(f"[KuCoin] fetch_open_orders error: {e}")
            return None

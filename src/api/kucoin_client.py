import ccxt
import os
import time
import traceback
from dotenv import load_dotenv
import pandas as pd

load_dotenv()

# KuCoin Futures ccxt unified symbol format
SYMBOL_MAP = {
    'XBTUSDTM':    'BTC/USDT:USDT',
    'ETHUSDTM':    'ETH/USDT:USDT',
    'SOLUSDTM':    'SOL/USDT:USDT',
    'XRPUSDTM':    'XRP/USDT:USDT',
    'DOGEUSDTM':   'DOGE/USDT:USDT',
    'ADAUSDTM':    'ADA/USDT:USDT',
    'MATICUSDTM':  'MATIC/USDT:USDT',
    'DOTUSDTM':    'DOT/USDT:USDT',
    'SIRENUSDTM':  'SIREN/USDT:USDT',
}

def to_ccxt_symbol(symbol: str) -> str:
    return SYMBOL_MAP.get(symbol, symbol)


class KuCoinClient:
    def __init__(self):
        api_key        = os.getenv('KUCOIN_API_KEY', '')
        api_secret     = os.getenv('KUCOIN_API_SECRET', '')
        api_passphrase = os.getenv('KUCOIN_API_PASSPHRASE', '')

        # Authenticated exchange for trading
        self.exchange = ccxt.kucoinfutures({
            'apiKey':          api_key,
            'secret':          api_secret,
            'password':        api_passphrase,
            'enableRateLimit': True,
        })

        # Public exchange for market data (no API keys needed)
        # This works even without credentials - avoids auth errors on Railway
        self.public = ccxt.kucoinfutures({
            'enableRateLimit': True,
        })

        self._margin_mode = None
        print(f"[KuCoin] Client initialized | API key set: {bool(api_key)}")

    # ── MARKET DATA (uses public endpoint) ───────────────────

    def fetch_ohlcv(self, symbol, timeframe, limit=100):
        try:
            ccxt_symbol = to_ccxt_symbol(symbol)
            print(f"[KuCoin] OHLCV {ccxt_symbol} {timeframe} ...")
            ohlcv = self.public.fetch_ohlcv(ccxt_symbol, timeframe, limit=limit)
            if not ohlcv:
                print(f"[KuCoin] Empty response for {ccxt_symbol}")
                return None
            df = pd.DataFrame(ohlcv, columns=['timestamp','open','high','low','close','volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            print(f"[KuCoin] Got {len(df)} candles for {ccxt_symbol}")
            return df
        except ccxt.BadSymbol as e:
            print(f"[KuCoin] Bad symbol {ccxt_symbol}: {e}")
            return None
        except ccxt.NetworkError as e:
            print(f"[KuCoin] Network error {ccxt_symbol}: {e}")
            return None
        except Exception as e:
            print(f"[KuCoin] fetch_ohlcv {ccxt_symbol}: {type(e).__name__}: {e}")
            return None

    def fetch_ticker(self, symbol):
        try:
            ccxt_symbol = to_ccxt_symbol(symbol)
            return self.public.fetch_ticker(ccxt_symbol)
        except Exception as e:
            print(f"[KuCoin] fetch_ticker {symbol}: {e}")
            return None

    # ── ACCOUNT (uses authenticated endpoint) ────────────────

    def get_margin_mode(self, symbol) -> str:
        try:
            if self._margin_mode:
                return self._margin_mode
            ccxt_symbol = to_ccxt_symbol(symbol)
            result = self.exchange.fetch_margin_mode(ccxt_symbol)
            mode = result.get('marginMode', 'isolated').lower()
            self._margin_mode = mode
            print(f"[KuCoin] Margin mode: {mode}")
            return mode
        except Exception as e:
            print(f"[KuCoin] get_margin_mode error: {e} - defaulting to isolated")
            self._margin_mode = 'isolated'
            return 'isolated'

    def fetch_balance(self):
        try:
            raw        = self.exchange.fetch_balance()
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
            print(f"[KuCoin] fetch_balance: {e}")
            traceback.print_exc()
            return None

    def fetch_position(self, symbol):
        try:
            ccxt_symbol = to_ccxt_symbol(symbol)
            positions   = self.exchange.fetch_positions([ccxt_symbol])
            for p in positions:
                if float(p.get('contracts', 0) or 0) != 0:
                    return p
            return None
        except Exception as e:
            print(f"[KuCoin] fetch_position {symbol}: {e}")
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
        try:
            ccxt_symbol = to_ccxt_symbol(symbol)
            amount      = max(1, int(amount))
            leverage    = int(os.getenv('LEVERAGE', 10))

            margin_mode = self.get_margin_mode(symbol)

            extra = {
                'leverage':   leverage,
                'hedged':     True,
                'marginMode': margin_mode,
            }

            if params and params.get('reduceOnly'):
                extra['reduceOnly'] = True

            if params:
                for k, v in params.items():
                    if k not in ('hedged', 'marginMode'):
                        extra[k] = v

            print(f"[KuCoin] ORDER {order_type.upper()} {side.upper()} {amount}x {ccxt_symbol} margin={margin_mode} lev={leverage}")

            order = self.exchange.create_order(
                symbol=ccxt_symbol, type=order_type,
                side=side, amount=amount, price=price, params=extra,
            )
            print(f"[KuCoin] Order OK: id={order.get('id')} status={order.get('status')}")
            return order

        except ccxt.InvalidOrder as e:
            err = str(e)
            print(f"[KuCoin] Invalid order: {err}")
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
        try:
            ccxt_symbol = to_ccxt_symbol(symbol)
            amount      = max(1, int(amount))
            leverage    = int(os.getenv('LEVERAGE', 10))
            current     = self._margin_mode or 'isolated'
            flipped     = 'cross' if current == 'isolated' else 'isolated'
            self._margin_mode = flipped
            print(f"[KuCoin] Retrying with marginMode={flipped}")
            extra = {'leverage': leverage, 'hedged': True, 'marginMode': flipped}
            if params and params.get('reduceOnly'):
                extra['reduceOnly'] = True
            order = self.exchange.create_order(
                symbol=ccxt_symbol, type=order_type,
                side=side, amount=amount, price=price, params=extra,
            )
            print(f"[KuCoin] Retry OK: id={order.get('id')}")
            return order
        except Exception as e:
            print(f"[KuCoin] Retry failed: {e}")
            return None

    def cancel_order(self, order_id, symbol):
        try:
            return self.exchange.cancel_order(order_id, to_ccxt_symbol(symbol))
        except Exception as e:
            print(f"[KuCoin] cancel_order: {e}")
            return None

    def fetch_open_orders(self, symbol):
        try:
            return self.exchange.fetch_open_orders(to_ccxt_symbol(symbol))
        except Exception as e:
            print(f"[KuCoin] fetch_open_orders: {e}")
            return None

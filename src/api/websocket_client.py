import websocket
import json
import time
import threading
from typing import Callable, Dict, List, Optional
from src.utils.logger import get_logger

logger = get_logger(__name__)

class WebSocketClient:
    """Real-time market data via KuCoin WebSocket."""
    
    def __init__(self, symbol: str = "BTC-USDT-M", channels: List[str] = None):
        self.symbol = symbol
        self.channels = channels or ["tickers", "candles5"]
        self.ws = None
        self.connected = False
        self.reconnect_delay = 5
        self.max_reconnects = 10
        self.reconnect_count = 0
        self.callbacks: Dict[str, Callable] = {}
        self.latest_data: Dict = {
            'ticker': {},
            'candles': [],
            'orderbook': {}
        }
        self._token = None
        self._server_url = None
        
    def set_callback(self, channel: str, callback: Callable):
        """Set callback function for specific channel."""
        self.callbacks[channel] = callback
        
    def connect(self):
        """Connect to KuCoin WebSocket."""
        try:
            # Get WebSocket token and server URL
            self._get_token()
            
            # WebSocket URL
            ws_url = f"{self._server_url}?token={self._token}"
            
            logger.info(f"Connecting to KuCoin WebSocket: {ws_url}")
            self.ws = websocket.WebSocketApp(
                ws_url,
                on_open=self._on_open,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close
            )
            
            # Run in separate thread
            self.ws_thread = threading.Thread(target=self.ws.run_forever, daemon=True)
            self.ws_thread.start()
            
            # Subscribe to channels after connection
            time.sleep(2)
            self._subscribe()
            
            self.connected = True
            self.reconnect_count = 0
            logger.info("WebSocket connected successfully")
            
        except Exception as e:
            logger.error(f"WebSocket connection error: {e}")
            self._attempt_reconnect()
    
    def _get_token(self):
        """Get WebSocket token from KuCoin API."""
        import requests
        
        # Use public endpoint for public data
        response = requests.post("https://api-public.sandbox.kucoin.com/api/v1/bullet-public")
        
        if response.status_code == 200:
            data = response.json()
            self._token = data['data']['token']
            instance_servers = data['data']['instanceServers']
            self._server_url = instance_servers[0]['endpoint']
            logger.info(f"Got WebSocket token from {instance_servers[0]['endpoint']}")
        else:
            raise Exception(f"Failed to get WebSocket token: {response.text}")
    
    def _subscribe(self):
        """Subscribe to configured channels."""
        if not self.ws:
            return
        
        # Subscribe to ticker
        ticker_msg = {
            "id": str(int(time.time() * 1000)),
            "type": "subscribe",
            "topic": f"/market/ticker:{self.symbol}",
            "privateChannel": False,
            "response": True
        }
        self.ws.send(json.dumps(ticker_msg))
        logger.info(f"Subscribed to ticker: {self.symbol}")
        
        # Subscribe to candles (5-minute)
        candle_msg = {
            "id": str(int(time.time() * 1000) + 1),
            "type": "subscribe",
            "topic": f"/market/candles:{self.symbol}_5min",
            "privateChannel": False,
            "response": True
        }
        self.ws.send(json.dumps(candle_msg))
        logger.info(f"Subscribed to candles: {self.symbol}_5min")
        
        # Subscribe to orderbook (optional, level2)
        orderbook_msg = {
            "id": str(int(time.time() * 1000) + 2),
            "type": "subscribe",
            "topic": f"/market/level2:{self.symbol}",
            "privateChannel": False,
            "response": True
        }
        self.ws.send(json.dumps(orderbook_msg))
        logger.info(f"Subscribed to orderbook: {self.symbol}")
    
    def _on_open(self, ws):
        """Handle WebSocket open event."""
        logger.info("WebSocket connection opened")
        self.connected = True
        
    def _on_message(self, ws, message):
        """Handle incoming WebSocket message."""
        try:
            data = json.loads(message)
            
            # Handle ping
            if data.get('type') == 'ping':
                pong_msg = {
                    "id": data.get('id'),
                    "type": "pong"
                }
                ws.send(json.dumps(pong_msg))
                return
            
            # Handle subscription confirmation
            if data.get('type') == 'ack':
                logger.debug(f"Subscription acknowledged: {data.get('id')}")
                return
            
            # Process market data
            topic = data.get('topic', '')
            
            if 'ticker' in topic:
                self._handle_ticker(data)
            elif 'candles' in topic:
                self._handle_candle(data)
            elif 'level2' in topic:
                self._handle_orderbook(data)
            
            # Call user callback if registered
            channel = topic.split(':')[0].split('/')[-1]
            if channel in self.callbacks:
                self.callbacks[channel](data)
                
        except Exception as e:
            logger.error(f"Error processing WebSocket message: {e}")
    
    def _handle_ticker(self, data):
        """Handle ticker data."""
        if 'data' in data:
            ticker_data = data['data']
            self.latest_data['ticker'] = {
                'price': float(ticker_data.get('price', 0)),
                'bestBid': float(ticker_data.get('bestBid', 0)),
                'bestAsk': float(ticker_data.get('bestAsk', 0)),
                'volume': float(ticker_data.get('vol', 0)),
                'change': float(ticker_data.get('changeRate', 0)) * 100,
                'timestamp': ticker_data.get('time', 0)
            }
    
    def _handle_candle(self, data):
        """Handle candle data."""
        if 'data' in data:
            candle_data = data['data']
            # Candle format: [time, open, close, high, low, volume, turnover]
            if len(candle_data) >= 7:
                candle = {
                    'time': int(candle_data[0]),
                    'open': float(candle_data[1]),
                    'close': float(candle_data[2]),
                    'high': float(candle_data[3]),
                    'low': float(candle_data[4]),
                    'volume': float(candle_data[5]),
                    'turnover': float(candle_data[6])
                }
                
                # Add to candles list (keep last 100)
                self.latest_data['candles'].append(candle)
                if len(self.latest_data['candles']) > 100:
                    self.latest_data['candles'] = self.latest_data['candles'][-100:]
    
    def _handle_orderbook(self, data):
        """Handle orderbook data."""
        if 'data' in data:
            orderbook_data = data['data']
            self.latest_data['orderbook'] = {
                'asks': orderbook_data.get('asks', []),
                'bids': orderbook_data.get('bids', []),
                'timestamp': orderbook_data.get('timestamp', 0)
            }
    
    def _on_error(self, ws, error):
        """Handle WebSocket error."""
        logger.error(f"WebSocket error: {error}")
        self.connected = False
    
    def _on_close(self, ws, close_status_code, close_msg):
        """Handle WebSocket close."""
        logger.info(f"WebSocket closed: {close_status_code} - {close_msg}")
        self.connected = False
        self._attempt_reconnect()
    
    def _attempt_reconnect(self):
        """Attempt to reconnect to WebSocket."""
        if self.reconnect_count < self.max_reconnects:
            self.reconnect_count += 1
            logger.info(f"Attempting reconnect {self.reconnect_count}/{self.max_reconnects} in {self.reconnect_delay}s...")
            time.sleep(self.reconnect_delay)
            self.connect()
        else:
            logger.error("Max reconnection attempts reached. Giving up.")
    
    def get_latest_ticker(self) -> Dict:
        """Get latest ticker data."""
        return self.latest_data.get('ticker', {})
    
    def get_latest_candles(self, count: int = 50) -> List[Dict]:
        """Get latest candles."""
        candles = self.latest_data.get('candles', [])
        return candles[-count:] if len(candles) > count else candles
    
    def get_orderbook_snapshot(self) -> Dict:
        """Get latest orderbook snapshot."""
        return self.latest_data.get('orderbook', {})
    
    def disconnect(self):
        """Disconnect from WebSocket."""
        if self.ws:
            self.ws.close()
            self.connected = False
            logger.info("WebSocket disconnected")
    
    def is_connected(self) -> bool:
        """Check if WebSocket is connected."""
        return self.connected and self.ws is not None

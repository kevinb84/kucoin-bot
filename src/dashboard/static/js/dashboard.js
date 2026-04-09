/**
 * Trading Bot Dashboard - Real-time Updates
 * Handles WebSocket connections and UI updates
 */

// Global state
let socket = null;
let chart = null;
let updateInterval = null;

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    console.log('Dashboard initializing...');
    initializeSocket();
    startClock();
    loadInitialData();
});

/**
 * Initialize WebSocket connection
 */
function initializeSocket() {
    socket = io();
    
    socket.on('connect', function() {
        console.log('Connected to server');
        updateConnectionStatus(true);
    });
    
    socket.on('disconnect', function() {
        console.log('Disconnected from server');
        updateConnectionStatus(false);
    });
    
    socket.on('update', function(data) {
        console.log('Received update:', data);
        updateDashboard(data);
    });
    
    socket.on('status', function(data) {
        updateBotStatus(data.is_running);
    });
}

/**
 * Update connection status indicator
 */
function updateConnectionStatus(connected) {
    const statusEl = document.getElementById('connectionStatus');
    if (connected) {
        statusEl.innerHTML = '<span class="conn-dot connected"></span><span>Connected</span>';
    } else {
        statusEl.innerHTML = '<span class="conn-dot disconnected"></span><span>Disconnected</span>';
    }
}

/**
 * Update bot status indicator
 */
function updateBotStatus(isRunning) {
    const statusEl = document.getElementById('botStatus');
    const startBtn = document.getElementById('startBtn');
    const stopBtn = document.getElementById('stopBtn');
    
    if (isRunning) {
        statusEl.innerHTML = '<span class="status-dot running"></span><span class="status-text">Running</span>';
        startBtn.disabled = true;
        stopBtn.disabled = false;
    } else {
        statusEl.innerHTML = '<span class="status-dot stopped"></span><span class="status-text">Stopped</span>';
        startBtn.disabled = false;
        stopBtn.disabled = true;
    }
}

/**
 * Update all dashboard data
 */
function updateDashboard(data) {
    updateMarketData(data.market_data || {});
    updatePosition(data.current_position);
    updatePerformance(data.performance || {});
    updateRecentTrades(data.recent_trades || []);
    updateMLPrediction(data.ml_prediction || {});
    updateChart(data.market_data?.candles || []);
}

/**
 * Update market data display
 */
function updateMarketData(marketData) {
    const ticker = marketData.ticker || {};
    
    // Update price
    if (ticker.price) {
        document.getElementById('currentPrice').textContent = formatCurrency(ticker.price);
    }
    
    // Update price change
    if (ticker.change !== undefined) {
        const changeEl = document.getElementById('priceChange');
        changeEl.textContent = formatPercent(ticker.change);
        changeEl.className = 'price-change ' + (ticker.change >= 0 ? 'positive' : 'negative');
    }
    
    // Update high/low/volume
    if (ticker.high) {
        document.getElementById('high24h').textContent = formatCurrency(ticker.high);
    }
    if (ticker.low) {
        document.getElementById('low24h').textContent = formatCurrency(ticker.low);
    }
    if (ticker.volume) {
        document.getElementById('volume24h').textContent = formatNumber(ticker.volume);
    }
}

/**
 * Update position panel
 */
function updatePosition(position) {
    const panel = document.getElementById('positionPanel');
    
    if (!position || position.size === 0) {
        panel.innerHTML = '<div class="no-position">No open position</div>';
        return;
    }
    
    const pnlClass = position.unrealized_pnl >= 0 ? 'pnl-positive' : 'pnl-negative';
    const sideIcon = position.side === 'long' ? '📈' : '📉';
    
    panel.innerHTML = `
        <div class="position-details">
            <div class="position-header">
                <span class="position-side">${sideIcon} ${position.side.toUpperCase()}</span>
                <span class="position-symbol">${position.symbol}</span>
            </div>
            <div class="position-metrics">
                <div class="metric-row">
                    <span class="metric-label">Size:</span>
                    <span class="metric-value">${position.size.toFixed(4)}</span>
                </div>
                <div class="metric-row">
                    <span class="metric-label">Entry:</span>
                    <span class="metric-value">${formatCurrency(position.entry_price)}</span>
                </div>
                <div class="metric-row">
                    <span class="metric-label">Current:</span>
                    <span class="metric-value">${formatCurrency(position.current_price)}</span>
                </div>
                <div class="metric-row">
                    <span class="metric-label">PnL:</span>
                    <span class="metric-value ${pnlClass}">${formatCurrency(position.unrealized_pnl)}</span>
                </div>
                <div class="metric-row">
                    <span class="metric-label">Leverage:</span>
                    <span class="metric-value">${position.leverage}x</span>
                </div>
            </div>
        </div>
    `;
}

/**
 * Update performance metrics
 */
function updatePerformance(performance) {
    document.getElementById('totalTrades').textContent = performance.total_trades || 0;
    
    const winRate = performance.win_rate || 0;
    document.getElementById('winRate').textContent = winRate.toFixed(1) + '%';
    document.getElementById('winRateBar').style.width = winRate + '%';
    
    document.getElementById('profitFactor').textContent = (performance.profit_factor || 0).toFixed(2);
    
    const totalPnl = performance.total_pnl || 0;
    const pnlEl = document.getElementById('totalPnl');
    pnlEl.textContent = formatCurrency(totalPnl);
    pnlEl.className = 'metric-value ' + (totalPnl >= 0 ? 'pnl-positive' : 'pnl-negative');
    
    document.getElementById('avgWin').textContent = formatCurrency(performance.avg_win || 0);
    document.getElementById('avgLoss').textContent = formatCurrency(performance.avg_loss || 0);
    document.getElementById('sharpeRatio').textContent = (performance.sharpe_ratio || 0).toFixed(2);
    document.getElementById('maxDrawdown').textContent = (performance.max_drawdown || 0).toFixed(2) + '%';
}

/**
 * Update recent trades table
 */
function updateRecentTrades(trades) {
    const tbody = document.getElementById('tradesTableBody');
    
    if (!trades || trades.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="no-data">No trades yet</td></tr>';
        return;
    }
    
    tbody.innerHTML = trades.map(trade => {
        const pnlClass = trade.pnl >= 0 ? 'pnl-positive' : 'pnl-negative';
        const sideIcon = trade.side === 'buy' ? '🟢' : '🔴';
        
        return `
            <tr>
                <td>${formatTime(trade.timestamp)}</td>
                <td>${trade.symbol}</td>
                <td>${sideIcon} ${trade.side.toUpperCase()}</td>
                <td>${formatCurrency(trade.entry_price)}</td>
                <td>${formatCurrency(trade.exit_price || 0)}</td>
                <td class="${pnlClass}">${formatCurrency(trade.pnl)}</td>
                <td>${trade.duration_minutes ? trade.duration_minutes.toFixed(1) + 'm' : '--'}</td>
            </tr>
        `;
    }).join('');
}

/**
 * Update ML prediction display
 */
function updateMLPrediction(prediction) {
    const predEl = document.getElementById('mlPrediction');
    const confidence = prediction.confidence || 0;
    
    if (prediction.prediction === 'up') {
        predEl.textContent = '📈 BULLISH';
        predEl.className = 'prediction-direction bullish';
    } else if (prediction.prediction === 'down') {
        predEl.textContent = '📉 BEARISH';
        predEl.className = 'prediction-direction bearish';
    } else {
        predEl.textContent = '➡️ NEUTRAL';
        predEl.className = 'prediction-direction neutral';
    }
    
    const confidencePercent = confidence * 100;
    document.getElementById('confidence').textContent = confidencePercent.toFixed(1) + '%';
    document.getElementById('confidenceBar').style.width = confidencePercent + '%';
}

/**
 * Update candlestick chart
 */
function updateChart(candles) {
    if (!candles || candles.length === 0) return;
    
    // Prepare data
    const times = candles.map(c => new Date(c.time));
    const open = candles.map(c => c.open);
    const high = candles.map(c => c.high);
    const low = candles.map(c => c.low);
    const close = candles.map(c => c.close);
    const volume = candles.map(c => c.volume);
    
    // Calculate EMAs
    const ema9 = calculateEMA(close, 9);
    const ema21 = calculateEMA(close, 21);
    
    // Create candlestick trace
    const candleTrace = {
        x: times,
        close: close,
        decreasing: {line: {color: '#ef5350'}},
        high: high,
        increasing: {line: {color: '#26a69a'}},
        line: {color: 'rgba(31,119,180,1)'},
        low: low,
        open: open,
        type: 'candlestick',
        xaxis: 'x',
        yaxis: 'y',
        name: 'Price'
    };
    
    // EMA 9 trace
    const ema9Trace = {
        x: times,
        y: ema9,
        type: 'scatter',
        mode: 'lines',
        line: {color: '#ffeb3b', width: 1.5},
        name: 'EMA 9',
        xaxis: 'x',
        yaxis: 'y'
    };
    
    // EMA 21 trace
    const ema21Trace = {
        x: times,
        y: ema21,
        type: 'scatter',
        mode: 'lines',
        line: {color: '#ff9800', width: 1.5},
        name: 'EMA 21',
        xaxis: 'x',
        yaxis: 'y'
    };
    
    // Volume bars
    const volumeTrace = {
        x: times,
        y: volume,
        type: 'bar',
        marker: {
            color: close.map((c, i) => c >= open[i] ? 'rgba(38, 166, 154, 0.5)' : 'rgba(239, 83, 80, 0.5)')
        },
        name: 'Volume',
        xaxis: 'x2',
        yaxis: 'y2'
    };
    
    const layout = {
        dragmode: 'pan',
        showlegend: true,
        xaxis: {
            autorange: true,
            rangeslider: {visible: false}
        },
        yaxis: {
            domain: [0.3, 1],
            title: 'Price (USDT)'
        },
        xaxis2: {
            domain: [0, 1],
            anchor: 'x'
        },
        yaxis2: {
            domain: [0, 0.25],
            title: 'Volume'
        },
        paper_bgcolor: 'rgba(0,0,0,0)',
        plot_bgcolor: 'rgba(0,0,0,0)',
        font: {color: '#c9d1d9'},
        margin: {l: 60, r: 30, t: 30, b: 30},
        legend: {
            x: 0,
            y: 1,
            bgcolor: 'rgba(0,0,0,0.5)'
        }
    };
    
    const config = {
        responsive: true,
        displayModeBar: false
    };
    
    Plotly.react('candlestickChart', [candleTrace, ema9Trace, ema21Trace, volumeTrace], layout, config);
    
    // Update last update time
    document.getElementById('chartUpdate').textContent = 'Last update: ' + formatTime(new Date());
}

/**
 * Calculate EMA
 */
function calculateEMA(data, period) {
    const k = 2 / (period + 1);
    const ema = [data[0]];
    
    for (let i = 1; i < data.length; i++) {
        ema.push(data[i] * k + ema[i - 1] * (1 - k));
    }
    
    return ema;
}

/**
 * Start the trading bot
 */
function startBot() {
    if (socket) {
        socket.emit('start_bot');
    }
}

/**
 * Stop the trading bot
 */
function stopBot() {
    if (socket) {
        socket.emit('stop_bot');
    }
}

/**
 * Refresh trades manually
 */
function refreshTrades() {
    fetch('/api/trades')
        .then(response => response.json())
        .then(data => {
            updateRecentTrades(data);
        })
        .catch(error => {
            console.error('Error fetching trades:', error);
        });
}

/**
 * Load initial data
 */
function loadInitialData() {
    // Fetch initial status
    fetch('/api/status')
        .then(response => response.json())
        .then(data => {
            updateDashboard(data);
            updateBotStatus(data.is_running);
        })
        .catch(error => {
            console.error('Error loading initial data:', error);
        });
}

/**
 * Start clock
 */
function startClock() {
    updateClock();
    setInterval(updateClock, 1000);
}

function updateClock() {
    const now = new Date();
    document.getElementById('currentTime').textContent = now.toLocaleTimeString();
}

/**
 * Utility: Format currency
 */
function formatCurrency(value) {
    return '$' + parseFloat(value).toLocaleString('en-US', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    });
}

/**
 * Utility: Format percentage
 */
function formatPercent(value) {
    const sign = value >= 0 ? '+' : '';
    return sign + parseFloat(value).toFixed(2) + '%';
}

/**
 * Utility: Format number
 */
function formatNumber(value) {
    return parseFloat(value).toLocaleString('en-US');
}

/**
 * Utility: Format time
 */
function formatTime(timestamp) {
    if (!timestamp) return '--';
    const date = new Date(timestamp);
    return date.toLocaleString();
}

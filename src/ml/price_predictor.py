import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, classification_report
import joblib
from typing import List, Dict, Tuple, Optional
from datetime import datetime
from src.utils.logger import get_logger

logger = get_logger(__name__)

class PricePredictor:
    """Machine Learning model for predicting short-term price direction."""
    
    def __init__(self, model_type: str = "random_forest", n_features: int = 10):
        """
        Initialize ML predictor.
        
        Args:
            model_type: Type of ML model to use
            n_features: Number of features to use
        """
        self.model_type = model_type
        self.n_features = n_features
        self.model = None
        self.scaler = StandardScaler()
        self.is_trained = False
        self.feature_names = []
        self.model_path = "ml_model.pkl"
        self.scaler_path = "ml_scaler.pkl"
        
        # Initialize model
        self._create_model()
    
    def _create_model(self):
        """Create ML model based on type."""
        if self.model_type == "random_forest":
            self.model = RandomForestClassifier(
                n_estimators=100,
                max_depth=10,
                min_samples_split=5,
                random_state=42,
                class_weight='balanced'
            )
        elif self.model_type == "gradient_boosting":
            self.model = GradientBoostingClassifier(
                n_estimators=100,
                max_depth=5,
                learning_rate=0.1,
                random_state=42
            )
        elif self.model_type == "logistic_regression":
            self.model = LogisticRegression(
                max_iter=1000,
                class_weight='balanced',
                random_state=42
            )
        else:
            raise ValueError(f"Unknown model type: {self.model_type}")
        
        logger.info(f"Created {self.model_type} model")
    
    def create_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Create technical features from OHLCV data.
        
        Args:
            df: DataFrame with columns: open, high, low, close, volume
        
        Returns:
            DataFrame with additional feature columns
        """
        df = df.copy()
        
        # Price-based features
        df['returns'] = df['close'].pct_change()
        df['log_returns'] = np.log(df['close'] / df['close'].shift(1))
        
        # Moving averages
        for period in [5, 9, 13, 21]:
            df[f'ema_{period}'] = df['close'].ewm(span=period, adjust=False).mean()
            df[f'price_vs_ema_{period}'] = df['close'] / df[f'ema_{period}'] - 1
        
        # RSI
        df['rsi'] = self._calculate_rsi(df['close'], period=14)
        
        # MACD
        ema_fast = df['close'].ewm(span=12, adjust=False).mean()
        ema_slow = df['close'].ewm(span=26, adjust=False).mean()
        df['macd'] = ema_fast - ema_slow
        df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
        df['macd_hist'] = df['macd'] - df['macd_signal']
        
        # Bollinger Bands
        sma = df['close'].rolling(window=20).mean()
        std = df['close'].rolling(window=20).std()
        df['bb_upper'] = sma + (std * 2)
        df['bb_lower'] = sma - (std * 2)
        df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / sma
        df['bb_position'] = (df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'])
        
        # Volume features
        df['volume_sma'] = df['volume'].rolling(window=20).mean()
        df['volume_ratio'] = df['volume'] / df['volume_sma']
        
        # Volatility
        df['volatility'] = df['returns'].rolling(window=10).std()
        
        # High-Low range
        df['hl_range'] = (df['high'] - df['low']) / df['close']
        
        # Price momentum
        for period in [3, 5, 10]:
            df[f'momentum_{period}'] = df['close'].pct_change(periods=period)
        
        # Target variable: price goes up in next period (1) or not (0)
        df['target'] = (df['close'].shift(-1) > df['close']).astype(int)
        
        return df
    
    def _calculate_rsi(self, prices: pd.Series, period: int = 14) -> pd.Series:
        """Calculate RSI indicator."""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    def prepare_data(self, df: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray]:
        """
        Prepare features and target for training.
        
        Args:
            df: DataFrame with OHLCV and features
        
        Returns:
            X (features), y (target)
        """
        # Create features if not already present
        if 'target' not in df.columns:
            df = self.create_features(df)
        
        # Drop rows with NaN
        df_clean = df.dropna()
        
        # Feature columns (exclude OHLCV and target)
        feature_cols = [col for col in df_clean.columns 
                       if col not in ['open', 'high', 'low', 'close', 'volume', 'target',
                                     'time', 'timestamp', 'turnover']]
        
        # Limit to n_features
        self.feature_names = feature_cols[:self.n_features]
        
        X = df_clean[self.feature_names].values
        y = df_clean['target'].values
        
        return X, y
    
    def train(self, df: pd.DataFrame, test_size: float = 0.2) -> Dict:
        """
        Train the ML model.
        
        Args:
            df: Historical OHLCV data
            test_size: Fraction of data for testing
        
        Returns:
            Dictionary with training metrics
        """
        logger.info(f"Training {self.model_type} model on {len(df)} samples...")
        
        # Prepare data
        X, y = self.prepare_data(df)
        
        if len(X) < 50:
            logger.warning("Not enough data for training (need at least 50 samples)")
            return {'error': 'Insufficient data'}
        
        # Split data
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, shuffle=False
        )
        
        # Scale features
        X_train_scaled = self.scaler.fit_transform(X_train)
        X_test_scaled = self.scaler.transform(X_test)
        
        # Train model
        self.model.fit(X_train_scaled, y_train)
        
        # Evaluate
        y_pred = self.model.predict(X_test_scaled)
        accuracy = accuracy_score(y_test, y_pred)
        
        self.is_trained = True
        
        metrics = {
            'accuracy': accuracy,
            'n_samples': len(X),
            'n_train': len(X_train),
            'n_test': len(X_test),
            'n_features': len(self.feature_names),
            'features': self.feature_names,
            'classification_report': classification_report(
                y_test, y_pred, 
                target_names=['Down', 'Up'],
                output_dict=True
            )
        }
        
        logger.info(f"Model trained! Accuracy: {accuracy:.2%}")
        logger.info(f"Features used: {self.feature_names}")
        
        return metrics
    
    def predict(self, df: pd.DataFrame) -> Dict:
        """
        Predict price direction for latest data.
        
        Args:
            df: DataFrame with recent OHLCV data
        
        Returns:
            Dictionary with prediction and confidence
        """
        if not self.is_trained:
            logger.warning("Model not trained yet!")
            return {'prediction': 'hold', 'confidence': 0.0}
        
        # Create features
        df_features = self.create_features(df)
        
        # Get latest row
        latest = df_features.iloc[[-1]]
        
        # Check for NaN
        if latest[self.feature_names].isna().any().any():
            logger.warning("NaN values in features")
            return {'prediction': 'hold', 'confidence': 0.0}
        
        # Scale
        X_scaled = self.scaler.transform(latest[self.feature_names].values)
        
        # Predict
        prediction = self.model.predict(X_scaled)[0]
        probabilities = self.model.predict_proba(X_scaled)[0]
        confidence = max(probabilities)
        
        # Interpret prediction
        direction = "up" if prediction == 1 else "down"
        
        return {
            'prediction': direction,
            'confidence': float(confidence),
            'prob_up': float(probabilities[1]),
            'prob_down': float(probabilities[0]),
            'features_used': self.feature_names
        }
    
    def save_model(self, path: str = None):
        """Save trained model to disk."""
        if not self.is_trained:
            logger.warning("Cannot save untrained model")
            return
        
        save_path = path or self.model_path
        joblib.dump(self.model, save_path)
        joblib.dump(self.scaler, self.scaler_path)
        logger.info(f"Model saved to {save_path}")
    
    def load_model(self, path: str = None):
        """Load trained model from disk."""
        load_path = path or self.model_path
        try:
            self.model = joblib.load(load_path)
            self.scaler = joblib.load(self.scaler_path)
            self.is_trained = True
            logger.info(f"Model loaded from {load_path}")
        except FileNotFoundError:
            logger.error(f"Model file not found: {load_path}")
    
    def get_feature_importance(self) -> Dict:
        """Get feature importance scores."""
        if not self.is_trained:
            return {}
        
        if hasattr(self.model, 'feature_importances_'):
            importance = dict(zip(self.feature_names, self.model.feature_importances_))
            # Sort by importance
            importance = dict(sorted(importance.items(), key=lambda x: x[1], reverse=True))
            return importance
        else:
            return {}

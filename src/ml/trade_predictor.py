"""
ML Trade Success Predictor
Uses Logistic Regression to predict win probability.
Features: trend_strength, volume_ratio, volatility, rsi, btc_direction
"""
import os
import pickle
import numpy as np
from typing import Dict, Optional

class TradePredictor:
    def __init__(self):
        self.model = None
        self.model_file = 'ml_trade_model.pkl'
        self._load_model()
    
    def _load_model(self):
        if os.path.exists(self.model_file):
            try:
                with open(self.model_file, 'rb') as f:
                    self.model = pickle.load(f)
            except:
                self.model = None
    
    def predict_win_probability(self, features: Dict) -> float:
        """
        Predict probability of trade success.
        Features: trend_strength (0-1), volume_ratio, volatility, rsi (0-100), btc_direction (-1 to 1)
        Returns: 0.0 to 1.0
        """
        if self.model is None:
            return 0.5  # Default if no model trained yet
        
        try:
            feature_array = np.array([[
                features.get('trend_strength', 0.5),
                features.get('volume_ratio', 1.0),
                features.get('volatility', 1.0),
                features.get('rsi', 50) / 100.0,
                features.get('btc_direction', 0)
            ]])
            
            probability = self.model.predict_proba(feature_array)[0][1]
            return float(probability)
        except:
            return 0.5
    
    def record_outcome(self, features: Dict, won: bool):
        """Record trade outcome for future retraining."""
        pass  # Simplified for now
    
    def retrain_model(self, trade_history):
        """Retrain model on recent trade history."""
        from sklearn.linear_model import LogisticRegression
        
        if len(trade_history) < 20:
            return  # Need minimum data
        
        # Extract features and labels
        X = []
        y = []
        
        for trade in trade_history:
            features = trade.get('features', {})
            X.append([
                features.get('trend_strength', 0.5),
                features.get('volume_ratio', 1.0),
                features.get('volatility', 1.0),
                features.get('rsi', 50) / 100.0,
                features.get('btc_direction', 0)
            ])
            y.append(1 if trade.get('won', False) else 0)
        
        # Train model
        self.model = LogisticRegression()
        self.model.fit(X, y)
        
        # Save model
        with open(self.model_file, 'wb') as f:
            pickle.dump(self.model, f)

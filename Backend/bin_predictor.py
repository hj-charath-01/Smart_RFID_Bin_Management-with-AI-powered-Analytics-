import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.preprocessing import StandardScaler
from scipy.spatial import distance_matrix
from scipy.optimize import differential_evolution
import json

class BinPredictor:
    """Predicts bin fill times based on historical data and features."""
    
    def __init__(self):
        self.model = GradientBoostingRegressor(
            n_estimators=100,
            learning_rate=0.1,
            max_depth=5,
            random_state=42
        )
        self.scaler = StandardScaler()
        self.is_trained = False
        self.feature_names = [
            'population_score', 'hour_of_day', 'day_of_week',
            'is_weekend', 'collections_count', 'days_since_collection',
            'avg_fill_rate_7d', 'nearby_bins_count', 'distance_to_center'
        ]
    
    def extract_features(self, bin_data: dict, historical_data: List[dict],
                        campus_center: Tuple[float, float] = (12.9716, 79.1577)) -> np.ndarray:
        """Extract features for prediction from bin data."""
        
        # Basic features
        pop_score = bin_data.get('population_score', 5)
        lat = bin_data.get('lat', campus_center[0])
        lng = bin_data.get('lng', campus_center[1])
        collections = bin_data.get('collections', 0)
        
        # Time-based features
        current_time = datetime.utcnow()
        hour = current_time.hour
        day_of_week = current_time.weekday()
        is_weekend = 1 if day_of_week >= 5 else 0
        
        # Historical features
        days_since_collection = self._calculate_days_since_collection(
            bin_data.get('id'), historical_data
        )
        avg_fill_rate = self._calculate_avg_fill_rate(
            bin_data.get('id'), historical_data, days=7
        )
        
        # Spatial features
        nearby_bins = self._count_nearby_bins(lat, lng, historical_data, radius=0.5)
        dist_to_center = self._haversine_distance(lat, lng, *campus_center)
        
        features = [
            pop_score, hour, day_of_week, is_weekend, collections,
            days_since_collection, avg_fill_rate, nearby_bins, dist_to_center
        ]
        
        return np.array(features).reshape(1, -1)
    
    def _haversine_distance(self, lat1: float, lon1: float, 
                           lat2: float, lon2: float) -> float:
        """Calculate distance between two points in kilometers."""
        R = 6371  # Earth radius in km
        
        lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        
        a = np.sin(dlat/2)**2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon/2)**2
        c = 2 * np.arcsin(np.sqrt(a))
        
        return R * c
    
    def _calculate_days_since_collection(self, bin_id: str, 
                                        historical_data: List[dict]) -> float:
        """Calculate days since last collection."""
        collections = [h for h in historical_data 
                      if h.get('bin_id') == bin_id and h.get('event') == 'collected']
        if not collections:
            return 0.0
        
        last_collection = max(collections, key=lambda x: x.get('timestamp', ''))
        try:
            last_time = datetime.fromisoformat(last_collection['timestamp'].replace('Z', ''))
            return (datetime.utcnow() - last_time).total_seconds() / 86400
        except:
            return 0.0
    
    def _calculate_avg_fill_rate(self, bin_id: str, historical_data: List[dict],
                                 days: int = 7) -> float:
        """Calculate average fill rate over last N days."""
        bin_history = [h for h in historical_data if h.get('bin_id') == bin_id]
        if len(bin_history) < 2:
            return 0.0
        
        cutoff = datetime.utcnow() - timedelta(days=days)
        recent = [h for h in bin_history 
                 if datetime.fromisoformat(h.get('timestamp', '').replace('Z', '')) > cutoff]
        
        if len(recent) < 2:
            return 0.0
        
        fill_changes = []
        for i in range(1, len(recent)):
            try:
                t1 = datetime.fromisoformat(recent[i-1]['timestamp'].replace('Z', ''))
                t2 = datetime.fromisoformat(recent[i]['timestamp'].replace('Z', ''))
                f1 = recent[i-1].get('fill_pct', 0)
                f2 = recent[i].get('fill_pct', 0)
                
                time_diff = (t2 - t1).total_seconds() / 3600  # hours
                if time_diff > 0 and f2 > f1:
                    fill_changes.append((f2 - f1) / time_diff)
            except:
                continue
        
        return np.mean(fill_changes) if fill_changes else 0.0
    
    def _count_nearby_bins(self, lat: float, lng: float, 
                          historical_data: List[dict], radius: float = 0.5) -> int:
        """Count bins within radius (km)."""
        unique_bins = {}
        for h in historical_data:
            bid = h.get('bin_id')
            if bid and bid not in unique_bins:
                unique_bins[bid] = (h.get('lat'), h.get('lng'))
        
        count = 0
        for other_lat, other_lng in unique_bins.values():
            if other_lat and other_lng:
                dist = self._haversine_distance(lat, lng, other_lat, other_lng)
                if 0 < dist < radius:
                    count += 1
        
        return count
    
    def train(self, historical_data: List[dict]):
        """Train the prediction model on historical data."""
        if len(historical_data) < 50:
            print("⚠️ Insufficient data for training (need at least 50 records)")
            return False
        
        # Group by bin and calculate time to fill
        df = pd.DataFrame(historical_data)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.sort_values(['bin_id', 'timestamp'])
        
        X_list, y_list = [], []
        
        for bin_id in df['bin_id'].unique():
            bin_df = df[df['bin_id'] == bin_id].copy()
            
            # Find collection events
            collections = bin_df[bin_df['event'] == 'collected'].index
            
            for i, coll_idx in enumerate(collections):
                # Get data after collection
                after_coll = bin_df[bin_df.index > coll_idx]
                
                # Find when it reached 100% or next collection
                full_events = after_coll[
                    (after_coll['fill_pct'] >= 100) | 
                    (after_coll['event'] == 'collected')
                ]
                
                if len(full_events) > 0:
                    start_time = bin_df.loc[coll_idx, 'timestamp']
                    end_time = full_events.iloc[0]['timestamp']
                    hours_to_fill = (end_time - start_time).total_seconds() / 3600
                    
                    # Extract features at collection time
                    bin_data = bin_df.loc[coll_idx].to_dict()
                    features = self.extract_features(bin_data, historical_data)
                    
                    X_list.append(features.flatten())
                    y_list.append(hours_to_fill)
        
        if len(X_list) < 10:
            print("⚠️ Insufficient training samples")
            return False
        
        X = np.array(X_list)
        y = np.array(y_list)
        
        # Scale features
        X_scaled = self.scaler.fit_transform(X)
        
        # Train model
        self.model.fit(X_scaled, y)
        self.is_trained = True
        
        print(f"✅ Model trained on {len(X)} samples")
        print(f"📊 Feature importances: {dict(zip(self.feature_names, self.model.feature_importances_))}")
        
        return True
    
    def predict_fill_time(self, bin_data: dict, 
                         historical_data: List[dict]) -> Dict[str, float]:
        """Predict time to fill for a bin (in hours)."""
        if not self.is_trained:
            # Fallback to simple calculation
            score = bin_data.get('population_score', 5)
            hours = self._simple_fill_time(score)
            return {
                'hours_to_fill': hours,
                'confidence': 0.5,
                'method': 'simple'
            }
        
        features = self.extract_features(bin_data, historical_data)
        features_scaled = self.scaler.transform(features)
        
        prediction = self.model.predict(features_scaled)[0]
        
        # Estimate confidence based on training data variance
        confidence = 0.8  # Simplified confidence score
        
        return {
            'hours_to_fill': max(0.1, prediction),
            'confidence': confidence,
            'method': 'ml_model'
        }
    
    def _simple_fill_time(self, population_score: int) -> float:
        """Simple fallback calculation."""
        FASTEST = 6
        SLOWEST = 48
        
        if population_score <= 0:
            return SLOWEST
        
        score = max(1, min(10, population_score))
        span = SLOWEST - FASTEST
        frac = (10 - score) / 9.0
        
        return FASTEST + frac * span


class BinPositionOptimizer:
    """Optimizes bin positions based on coverage and demand."""
    
    def __init__(self, campus_bounds: Dict[str, float] = None):
        """
        Initialize optimizer with campus boundaries.
        
        Args:
            campus_bounds: dict with 'min_lat', 'max_lat', 'min_lng', 'max_lng'
        """
        # VIT Vellore Campus Coordinates
        self.bounds = campus_bounds or {
            'min_lat': 12.9650,
            'max_lat': 12.9780,
            'min_lng': 79.1520,
            'max_lng': 79.1640
        }
        # VIT Vellore campus center
        self.campus_center = (12.9716, 79.1577)
    
    def calculate_bin_fill_rates(self, existing_bins: List[dict]) -> Dict[str, float]:
        """
        Calculate actual fill rates for existing bins based on their population score and current fill.
        Returns a dict mapping bin_id to fill_rate (percent per hour).
        """
        fill_rates = {}
        for bin_data in existing_bins:
            pop_score = bin_data.get('population_score', 0)
            if pop_score > 0:
                # Calculate fill rate based on population score
                # Higher score = faster fill rate
                FASTEST_HOURS = 6
                SLOWEST_HOURS = 48
                
                score = max(1, min(10, pop_score))
                hours_to_fill = FASTEST_HOURS + ((10 - score) / 9.0) * (SLOWEST_HOURS - FASTEST_HOURS)
                fill_rate = 100.0 / hours_to_fill  # percent per hour
                
                fill_rates[bin_data['id']] = fill_rate
            else:
                fill_rates[bin_data['id']] = 0.0
        
        return fill_rates
    
    def create_demand_heatmap(self, existing_bins: List[dict], 
                             grid_size: int = 50) -> np.ndarray:
        """
        Create a demand heatmap based on existing bin fill rates.
        High-traffic areas (fast-filling bins) get higher values.
        """
        heatmap = np.zeros((grid_size, grid_size))
        
        if not existing_bins:
            return heatmap
        
        # Calculate fill rates for all bins
        fill_rates = self.calculate_bin_fill_rates(existing_bins)
        
        # Create grid
        lat_range = np.linspace(self.bounds['min_lat'], self.bounds['max_lat'], grid_size)
        lng_range = np.linspace(self.bounds['min_lng'], self.bounds['max_lng'], grid_size)
        
        # For each grid cell, calculate demand based on nearby bins
        for i, lat in enumerate(lat_range):
            for j, lng in enumerate(lng_range):
                demand = 0.0
                
                for bin_data in existing_bins:
                    bin_lat = bin_data.get('lat')
                    bin_lng = bin_data.get('lng')
                    bin_id = bin_data.get('id')
                    
                    if bin_lat and bin_lng and bin_id in fill_rates:
                        # Distance from this grid cell to the bin
                        dist = self._haversine_distance(lat, lng, bin_lat, bin_lng)
                        
                        # Bins with higher fill rates contribute more to demand
                        # Use gaussian-like falloff with distance
                        fill_rate = fill_rates[bin_id]
                        if dist < 0.3:  # Within 300m
                            # Normalize fill rate (0-10 scale, higher = more demand)
                            normalized_rate = fill_rate / 10.0  # Rough normalization
                            influence = normalized_rate * np.exp(-(dist ** 2) / 0.05)
                            demand += influence
                
                heatmap[i, j] = demand
        
        # Normalize heatmap to 0-1 range
        if heatmap.max() > 0:
            heatmap = heatmap / heatmap.max()
        
        return heatmap
    
    def suggest_new_position(self, existing_bins: List[dict],
                            population_heatmap: Optional[np.ndarray] = None,
                            grid_size: int = 50) -> Dict[str, float]:
        """
        Suggest optimal position for a new bin based on existing bin fill rates.
        
        Args:
            existing_bins: List of current bin dictionaries
            population_heatmap: 2D array of population density (optional, overridden by actual data)
            grid_size: Resolution of search grid
        """
        if not existing_bins:
            # First bin - place at campus center
            return {
                'lat': self.campus_center[0],
                'lng': self.campus_center[1],
                'reason': 'first_bin_center',
                'expected_score': 7
            }
        
        # Create demand heatmap based on actual bin performance
        demand_heatmap = self.create_demand_heatmap(existing_bins, grid_size)
        
        # Extract existing positions
        existing_pos = np.array([
            [b['lat'], b['lng']] for b in existing_bins
        ])
        
        # Create evaluation grid WITHIN campus bounds
        lats = np.linspace(self.bounds['min_lat'], self.bounds['max_lat'], grid_size)
        lngs = np.linspace(self.bounds['min_lng'], self.bounds['max_lng'], grid_size)
        
        best_score = -np.inf
        best_position = None
        
        for i, lat in enumerate(lats):
            for j, lng in enumerate(lngs):
                # Ensure position is within bounds
                if not self._is_within_bounds(lat, lng):
                    continue
                    
                score = self._evaluate_position(
                    lat, lng, existing_pos, demand_heatmap, i, j
                )
                if score > best_score:
                    best_score = score
                    best_position = (lat, lng, i, j)
        
        # Fallback to campus center if no valid position found
        if best_position is None:
            best_position = (*self.campus_center, grid_size//2, grid_size//2)
        
        # Estimate population score based on demand at this location
        demand_value = demand_heatmap[best_position[2], best_position[3]]
        expected_score = self._estimate_score_from_demand(demand_value)
        
        return {
            'lat': best_position[0],
            'lng': best_position[1],
            'reason': 'optimized_based_on_fill_rates',
            'optimization_score': best_score,
            'expected_score': expected_score,
            'demand_level': float(demand_value)
        }
    
    def _is_within_bounds(self, lat: float, lng: float) -> bool:
        """Check if coordinates are within campus bounds."""
        return (self.bounds['min_lat'] <= lat <= self.bounds['max_lat'] and
                self.bounds['min_lng'] <= lng <= self.bounds['max_lng'])
    
    def _evaluate_position(self, lat: float, lng: float,
                          existing_pos: np.ndarray,
                          demand_heatmap: np.ndarray,
                          grid_i: int, grid_j: int) -> float:
        """Evaluate quality of a position based on demand and coverage."""
        score = 0.0
        
        # 1. Coverage score (distance to nearest existing bin)
        if len(existing_pos) > 0:
            distances = [
                self._haversine_distance(lat, lng, ex_lat, ex_lng)
                for ex_lat, ex_lng in existing_pos
            ]
            min_dist = min(distances)
            
            # Ideal distance: 0.15-0.4 km
            if min_dist < 0.08:
                score -= 100  # Too close
            elif 0.15 <= min_dist <= 0.4:
                score += 40  # Good spacing
            else:
                score += min(25, min_dist * 20)  # Prefer coverage gaps
        
        # 2. DEMAND SCORE - Most important factor (based on actual bin fill rates)
        if 0 <= grid_i < demand_heatmap.shape[0] and 0 <= grid_j < demand_heatmap.shape[1]:
            demand = demand_heatmap[grid_i, grid_j]
            # High demand areas should get significantly higher scores
            score += demand * 100  # Weight demand heavily
        
        # 3. Distance from campus center (prefer somewhat central locations)
        dist_from_center = self._haversine_distance(
            lat, lng, self.campus_center[0], self.campus_center[1]
        )
        # Slight penalty for being too far from center
        if dist_from_center > 0.6:
            score -= dist_from_center * 15
        
        return score
    
    def _estimate_score_from_demand(self, demand_value: float) -> int:
        """Estimate population score (1-10) from demand value (0-1)."""
        # Map demand to population score
        # Higher demand = higher population score
        if demand_value >= 0.8:
            return 9
        elif demand_value >= 0.6:
            return 8
        elif demand_value >= 0.4:
            return 7
        elif demand_value >= 0.25:
            return 6
        elif demand_value >= 0.15:
            return 5
        elif demand_value >= 0.08:
            return 4
        else:
            return 3
    
    def _haversine_distance(self, lat1: float, lon1: float,
                           lat2: float, lon2: float) -> float:
        """Calculate distance in kilometers."""
        R = 6371
        lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = np.sin(dlat/2)**2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon/2)**2
        c = 2 * np.arcsin(np.sqrt(a))
        return R * c
    
    def optimize_collection_route(self, bins_to_collect: List[dict],
                                  depot_location: Tuple[float, float]) -> List[str]:
        """
        Optimize collection route using nearest neighbor heuristic.
        
        Args:
            bins_to_collect: List of bins needing collection
            depot_location: Starting point (lat, lng)
        
        Returns:
            Ordered list of bin IDs
        """
        if not bins_to_collect:
            return []
        
        unvisited = bins_to_collect.copy()
        route = []
        current_pos = depot_location
        
        while unvisited:
            # Find nearest unvisited bin
            nearest = min(unvisited, key=lambda b: self._haversine_distance(
                current_pos[0], current_pos[1], b['lat'], b['lng']
            ))
            
            route.append(nearest['id'])
            current_pos = (nearest['lat'], nearest['lng'])
            unvisited.remove(nearest)
        
        return route


# Example usage and API integration
def create_prediction_api_endpoints(app, predictor: BinPredictor, 
                                   optimizer: BinPositionOptimizer,
                                   bins_data: Dict, history_data: List):
    """
    Add prediction and optimization endpoints to FastAPI app.
    """
    
    @app.get("/api/predict_fill_time/{bin_id}")
    async def predict_fill_time(bin_id: str):
        """Predict time until bin is full."""
        if bin_id not in bins_data:
            return {"error": "Bin not found"}
        
        bin_data = bins_data[bin_id]
        prediction = predictor.predict_fill_time(bin_data, history_data)
        
        current_fill = bin_data.get('fill_pct', 0)
        remaining_pct = 100 - current_fill
        time_to_full = prediction['hours_to_fill'] * (remaining_pct / 100)
        
        return {
            "bin_id": bin_id,
            "current_fill_pct": current_fill,
            "hours_to_full": round(time_to_full, 2),
            "estimated_full_time": (datetime.utcnow() + 
                                   timedelta(hours=time_to_full)).isoformat(),
            "confidence": prediction['confidence'],
            "method": prediction['method']
        }
    
    @app.get("/api/suggest_new_bin")
    async def suggest_new_bin():
        """Suggest optimal position for new bin."""
        existing = list(bins_data.values())
        suggestion = optimizer.suggest_new_position(existing)
        
        return {
            "suggested_position": {
                "lat": suggestion['lat'],
                "lng": suggestion['lng']
            },
            "expected_population_score": suggestion['expected_score'],
            "reason": suggestion['reason'],
            "optimization_score": suggestion.get('optimization_score')
        }
    
    @app.get("/api/train_model")
    async def train_model():
        """Train prediction model on current historical data."""
        success = predictor.train(history_data)
        return {
            "success": success,
            "training_samples": len(history_data),
            "model_status": "trained" if success else "insufficient_data"
        }
    
    @app.get("/api/optimize_route")
    async def optimize_route(threshold: float = 80.0):
        """Get optimized collection route for bins above threshold."""
        bins_to_collect = [
            b for b in bins_data.values() 
            if b.get('fill_pct', 0) >= threshold
        ]
        
        # Use VIT Vellore campus center as depot
        depot = (12.9716, 79.1577)
        route = optimizer.optimize_collection_route(bins_to_collect, depot)
        
        return {
            "route": route,
            "bin_count": len(route),
            "threshold": threshold
        }


if __name__ == "__main__":
    print("🧠 Smart Bin Prediction & Optimization System")
    print("🏫 Configured for VIT Vellore Campus")
    print("📊 Optimized placement based on actual bin fill rates")
    print("=" * 50)
    
    # Initialize
    predictor = BinPredictor()
    optimizer = BinPositionOptimizer()
    
    # Example bin data
    example_bins = [
        {"id": "BIN-001", "lat": 12.9700, "lng": 79.1560, 
         "population_score": 8, "fill_pct": 45, "collections": 5},
        {"id": "BIN-002", "lat": 12.9730, "lng": 79.1590, 
         "population_score": 6, "fill_pct": 70, "collections": 3}
    ]
    
    # Suggest new position
    print("\n📍 Suggesting optimal position for new bin...")
    suggestion = optimizer.suggest_new_position(example_bins)
    print(f"   Latitude: {suggestion['lat']:.6f}")
    print(f"   Longitude: {suggestion['lng']:.6f}")
    print(f"   Expected Score: {suggestion['expected_score']}")
    print(f"   Demand Level: {suggestion.get('demand_level', 0):.3f}")
    print(f"   Reason: {suggestion['reason']}")
    
    print("\n✅ System ready for integration!")
import asyncio
import json
import math
import uuid
from datetime import datetime, timedelta
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from typing import List, Dict
from pathlib import Path
from io import StringIO
import csv
from bin_predictor import BinPredictor, BinPositionOptimizer

app = FastAPI()

# ------------------------------
# CORS + Static setup
# ------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize ML components
predictor = BinPredictor()
optimizer = BinPositionOptimizer()

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
STATIC_DIR = FRONTEND_DIR / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# ------------------------------
# In-memory storage
# ------------------------------
BINS: Dict[str, dict] = {}
BIN_HISTORY: List[dict] = []

# ------------------------------
# Logging helper
# ------------------------------
def log_bin_state(bin_obj: dict, event: str = "update"):
    """Record the current state of a bin with timestamp."""
    BIN_HISTORY.append({
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "event": event,
        "bin_id": bin_obj["id"],
        "rfid": bin_obj["rfid"],
        "lat": bin_obj["lat"],
        "lng": bin_obj["lng"],
        "fill_pct": bin_obj["fill_pct"],
        "collections": bin_obj["collections"],
        "population_score": bin_obj["population_score"],
        "paused": bin_obj.get("paused", False),
    })

# ------------------------------
# WebSocket manager
# ------------------------------
class ConnectionManager:
    def __init__(self):
        self.active: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active.append(websocket)
        print(f"🔌 Client connected ({len(self.active)} total)")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active:
            self.active.remove(websocket)
            print(f"❌ Client disconnected ({len(self.active)} left)")

    async def broadcast(self, message: dict):
        data = json.dumps(message)
        dead = []
        for ws in list(self.active):
            try:
                await ws.send_text(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

manager = ConnectionManager()

# ------------------------------
# Simulation parameters
# ------------------------------
TICK_SECONDS = 1.0
SIM_SPEED = 1.0
FASTEST_FILL_SECONDS = 6 * 3600
SLOWEST_FILL_SECONDS = 48 * 3600
SIMULATED_TIME = datetime.utcnow()

# ------------------------------
# Helpers
# ------------------------------
def seconds_to_fill_for_score(score: int) -> float:
    if score <= 0:
        return float("inf")
    score = max(1, min(10, score))
    span = SLOWEST_FILL_SECONDS - FASTEST_FILL_SECONDS
    frac = (10 - score) / 9.0
    return FASTEST_FILL_SECONDS + frac * span

# ------------------------------
# Simulation loop
# ------------------------------
async def simulation_loop():
    global SIMULATED_TIME, SIM_SPEED
    while True:
        effective_seconds = TICK_SECONDS * SIM_SPEED
        updates = []

        for b in list(BINS.values()):
            score = int(b.get("population_score", 0) or 0)
            if score > 0 and not b.get("paused", False):
                secs_to_fill = seconds_to_fill_for_score(score)
                if math.isfinite(secs_to_fill) and secs_to_fill > 0:
                    pct_per_second = 100.0 / secs_to_fill
                    delta = pct_per_second * effective_seconds
                    new_fill = min(100.0, round(b.get("fill_pct", 0.0) + delta, 4))
                    if new_fill != b.get("fill_pct", 0.0):
                        b["fill_pct"] = new_fill
                        updates.append({
                            "type": "fill_update",
                            "bin_id": b["id"],
                            "fill_pct": b["fill_pct"],
                            "rfid": b["rfid"],
                            "collections": b["collections"]
                        })
                        if b["fill_pct"] >= 100.0:
                            b["fill_pct"] = 100.0
                            b["paused"] = True
                            updates.append({"type": "bin_full", "bin_id": b["id"]})
                            log_bin_state(b, event="full")
                        else:
                            log_bin_state(b, event="auto_update")

        SIMULATED_TIME += timedelta(seconds=effective_seconds)

        for u in updates:
            await manager.broadcast(u)

        await manager.broadcast({
            "type": "time_update",
            "sim_time_iso": SIMULATED_TIME.isoformat() + "Z",
            "sim_speed": SIM_SPEED
        })

        await asyncio.sleep(TICK_SECONDS)

# ------------------------------
# Periodic logger
# ------------------------------
async def periodic_logger():
    global SIMULATED_TIME
    last_snapshot_time = SIMULATED_TIME
    while True:
        await asyncio.sleep(TICK_SECONDS)
        if (SIMULATED_TIME - last_snapshot_time) >= timedelta(minutes=15):
            now = SIMULATED_TIME.isoformat() + "Z"
            for b in list(BINS.values()):
                BIN_HISTORY.append({
                    "timestamp": now,
                    "event": "interval_snapshot",
                    "bin_id": b["id"],
                    "rfid": b["rfid"],
                    "lat": b["lat"],
                    "lng": b["lng"],
                    "fill_pct": b["fill_pct"],
                    "collections": b["collections"],
                    "population_score": b["population_score"],
                    "paused": b.get("paused", False),
                })
            print(f"🕒 Recorded simulated 15-min snapshot ({len(BIN_HISTORY)} total rows)")
            last_snapshot_time = SIMULATED_TIME

# ------------------------------
# Startup tasks
# ------------------------------
@app.on_event("startup")
async def startup_event():
    asyncio.create_task(simulation_loop())
    asyncio.create_task(periodic_logger())
    print("🚀 Simulation + Simulated 15-minute logger started")

# ------------------------------
# REST API - Original endpoints
# ------------------------------
@app.get("/")
async def root():
    """Serve the main HTML page."""
    return FileResponse(FRONTEND_DIR / "index.html")

@app.get("/api/download_csv")
async def download_csv():
    """Export complete bin history as a time-series CSV."""
    if not BIN_HISTORY:
        return JSONResponse({"error": "No data yet"}, status_code=400)

    output = StringIO()
    fieldnames = list(BIN_HISTORY[0].keys())
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(BIN_HISTORY)
    output.seek(0)
    filename = f"bin_history_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(output, media_type="text/csv",
                             headers={"Content-Disposition": f"attachment; filename={filename}"})

# ------------------------------
# ML Prediction Endpoints
# ------------------------------
@app.get("/api/predict_fill_time/{bin_id}")
async def predict_fill_time(bin_id: str):
    """Predict time until bin is full."""
    if bin_id not in BINS:
        return JSONResponse({"error": "Bin not found"}, status_code=404)
    
    bin_data = BINS[bin_id]
    prediction = predictor.predict_fill_time(bin_data, BIN_HISTORY)
    
    current_fill = bin_data.get('fill_pct', 0)
    remaining_pct = max(0, 100 - current_fill)
    time_to_full = prediction['hours_to_fill'] * (remaining_pct / 100) if remaining_pct > 0 else 0
    
    return {
        "success": True,
        "bin_id": bin_id,
        "current_fill_pct": round(current_fill, 2),
        "hours_to_full": round(time_to_full, 2),
        "estimated_full_time": (SIMULATED_TIME + timedelta(hours=time_to_full)).isoformat() + "Z",
        "confidence": prediction['confidence'],
        "method": prediction['method']
    }

@app.get("/api/predict_all_bins")
async def predict_all_bins():
    """Get predictions for all bins."""
    predictions = []
    
    for bin_id, bin_data in BINS.items():
        current_fill = bin_data.get('fill_pct', 0)
        
        if current_fill >= 100:
            predictions.append({
                "bin_id": bin_id,
                "status": "full",
                "current_fill_pct": 100.0
            })
        elif current_fill == 0:
            predictions.append({
                "bin_id": bin_id,
                "status": "empty",
                "current_fill_pct": 0.0
            })
        else:
            try:
                prediction = predictor.predict_fill_time(bin_data, BIN_HISTORY)
                remaining_pct = 100 - current_fill
                time_to_full = prediction['hours_to_fill'] * (remaining_pct / 100)
                
                predictions.append({
                    "bin_id": bin_id,
                    "rfid": bin_data.get('rfid'),
                    "current_fill_pct": round(current_fill, 2),
                    "hours_to_full": round(time_to_full, 2),
                    "estimated_full_time": (SIMULATED_TIME + timedelta(hours=time_to_full)).isoformat() + "Z",
                    "confidence": prediction['confidence'],
                    "method": prediction['method'],
                    "status": "filling"
                })
            except Exception as e:
                predictions.append({
                    "bin_id": bin_id,
                    "status": "error",
                    "error": str(e),
                    "current_fill_pct": round(current_fill, 2)
                })
    
    return {
        "success": True,
        "predictions": predictions,
        "timestamp": SIMULATED_TIME.isoformat() + "Z"
    }

@app.get("/api/suggest_new_bin")
async def suggest_new_bin():
    """Suggest optimal position for new bin."""
    existing = list(BINS.values())
    
    if not existing:
        return {
            "success": True,
            "suggestion": {
                "lat": 12.9716,
                "lng": 79.1588,
                "expected_population_score": 5,
                "reason": "first_bin_center"
            }
        }
    
    suggestion = optimizer.suggest_new_position(existing)
    
    return {
        "success": True,
        "suggestion": {
            "lat": round(suggestion['lat'], 6),
            "lng": round(suggestion['lng'], 6),
            "expected_population_score": suggestion['expected_score'],
            "reason": suggestion['reason'],
            "optimization_score": suggestion.get('optimization_score', 0)
        }
    }

@app.post("/api/suggest_multiple_bins")
async def suggest_multiple_bins(num_bins: int = 3):
    """Suggest multiple optimal bin positions."""
    existing = list(BINS.values())
    suggestions = []
    
    temp_bins = existing.copy()
    
    for i in range(num_bins):
        suggestion = optimizer.suggest_new_position(temp_bins)
        suggestions.append({
            "location_id": f"SUGGESTED-{i+1}",
            "lat": round(suggestion['lat'], 6),
            "lng": round(suggestion['lng'], 6),
            "expected_population_score": suggestion['expected_score'],
            "reason": suggestion['reason'],
            "optimization_score": suggestion.get('optimization_score', 0)
        })
        
        # Add suggested bin to temp list for next iteration
        temp_bins.append({
            'id': f'TEMP-{i}',
            'lat': suggestion['lat'],
            'lng': suggestion['lng'],
            'population_score': suggestion['expected_score']
        })
    
    return {
        "success": True,
        "suggestions": suggestions,
        "count": len(suggestions)
    }

@app.get("/api/train_model")
async def train_model():
    """Train prediction model on current historical data."""
    try:
        success = predictor.train(BIN_HISTORY)
        return {
            "success": success,
            "training_samples": len(BIN_HISTORY),
            "model_status": "trained" if success else "insufficient_data",
            "message": "Model trained successfully" if success else "Need more data (minimum 50 records)"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "training_samples": len(BIN_HISTORY)
        }

@app.get("/api/optimize_route")
async def optimize_route(threshold: float = 80.0):
    """Get optimized collection route for bins above threshold."""
    bins_to_collect = [
        b for b in BINS.values() 
        if b.get('fill_pct', 0) >= threshold
    ]
    
    if not bins_to_collect:
        return {
            "success": True,
            "route": [],
            "bin_count": 0,
            "threshold": threshold,
            "message": "No bins above threshold"
        }
    
    depot = (12.9716, 79.1588)
    route = optimizer.optimize_collection_route(bins_to_collect, depot)
    
    # Calculate total distance
    total_distance = 0
    current_pos = depot
    route_details = []
    
    for bin_id in route:
        bin_data = BINS[bin_id]
        dist = optimizer._haversine_distance(
            current_pos[0], current_pos[1],
            bin_data['lat'], bin_data['lng']
        )
        total_distance += dist
        route_details.append({
            "bin_id": bin_id,
            "lat": bin_data['lat'],
            "lng": bin_data['lng'],
            "fill_pct": bin_data['fill_pct'],
            "distance_from_previous": round(dist, 2)
        })
        current_pos = (bin_data['lat'], bin_data['lng'])
    
    return {
        "success": True,
        "route": route,
        "route_details": route_details,
        "bin_count": len(route),
        "total_distance_km": round(total_distance, 2),
        "threshold": threshold
    }

@app.get("/api/analytics/summary")
async def analytics_summary():
    """Get comprehensive analytics summary."""
    bins_list = list(BINS.values())
    
    if not bins_list:
        return {
            "success": False,
            "error": "No bins available"
        }
    
    total_bins = len(bins_list)
    active_bins = len([b for b in bins_list if 0 < b.get('fill_pct', 0) < 100])
    full_bins = len([b for b in bins_list if b.get('fill_pct', 0) >= 100])
    empty_bins = len([b for b in bins_list if b.get('fill_pct', 0) == 0])
    
    avg_fill = sum(b.get('fill_pct', 0) for b in bins_list) / total_bins if total_bins > 0 else 0
    total_collections = sum(b.get('collections', 0) for b in bins_list)
    
    return {
        "success": True,
        "summary": {
            "total_bins": total_bins,
            "active_bins": active_bins,
            "full_bins": full_bins,
            "empty_bins": empty_bins,
            "average_fill_percentage": round(avg_fill, 2),
            "total_collections": total_collections,
            "model_trained": predictor.is_trained,
            "historical_records": len(BIN_HISTORY)
        },
        "timestamp": SIMULATED_TIME.isoformat() + "Z"
    }

# ------------------------------
# WebSocket handler
# ------------------------------
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    global SIM_SPEED
    await manager.connect(websocket)
    try:
        await websocket.send_text(json.dumps({
            "type": "initial_state",
            "bins": list(BINS.values()),
            "sim_time_iso": SIMULATED_TIME.isoformat() + "Z",
            "sim_speed": SIM_SPEED
        }))

        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                continue

            mtype = msg.get("type")

            if mtype == "add_bin":
                b = msg.get("bin", {})
                try:
                    lat = float(b.get("lat"))
                    lng = float(b.get("lng"))
                except Exception:
                    await websocket.send_text(json.dumps({"type": "error", "message": "invalid_coords"}))
                    continue
                score = max(0, min(10, int(b.get("population_score", 0) or 0)))
                bin_id = b.get("id") or f"BIN-{str(uuid.uuid4())[:8].upper()}"
                bin_obj = {
                    "id": bin_id,
                    "rfid": b.get("rfid") or f"RFID-{str(uuid.uuid4())[:8].upper()}",
                    "lat": lat,
                    "lng": lng,
                    "population_score": score,
                    "fill_pct": float(b.get("fill_pct", 0.0) or 0.0),
                    "collections": int(b.get("collections", 0) or 0),
                    "paused": False
                }
                BINS[bin_id] = bin_obj
                log_bin_state(bin_obj, event="add")
                await manager.broadcast({"type": "bin_added", "bin": bin_obj})

            elif mtype == "collect":
                bin_id = msg.get("bin_id")
                b = BINS.get(bin_id)
                if not b:
                    await websocket.send_text(json.dumps({"type": "error", "message": "bin_not_found"}))
                    continue
                b["fill_pct"] = 0.0
                b["collections"] += 1
                b["paused"] = False
                log_bin_state(b, event="collected")
                await manager.broadcast({
                    "type": "collected",
                    "bin_id": bin_id,
                    "collections": b["collections"]
                })
                await manager.broadcast({
                    "type": "fill_update",
                    "bin_id": bin_id,
                    "fill_pct": b["fill_pct"],
                    "rfid": b["rfid"]
                })

            elif mtype == "remove_bin":
                bin_id = msg.get("bin_id")
                if bin_id in BINS:
                    log_bin_state(BINS[bin_id], event="removed")
                    del BINS[bin_id]
                    await manager.broadcast({"type": "bin_removed", "bin_id": bin_id})

            elif mtype == "set_speed":
                try:
                    new_speed = float(msg.get("mult", 1.0))
                    if new_speed <= 0:
                        new_speed = 1.0
                except Exception:
                    new_speed = 1.0
                SIM_SPEED = new_speed
                await manager.broadcast({"type": "speed_changed", "sim_speed": SIM_SPEED})
                print(f"⚡ Simulation speed updated: {SIM_SPEED}x")

            elif mtype == "reset_simulation":
                for b in BINS.values():
                    b["fill_pct"] = 0.0
                    b["collections"] = 0
                    b["paused"] = False
                    log_bin_state(b, event="reset")
                await manager.broadcast({"type": "reset_done"})
                print("♻️ Simulation reset complete")

    except WebSocketDisconnect:
        manager.disconnect(websocket)
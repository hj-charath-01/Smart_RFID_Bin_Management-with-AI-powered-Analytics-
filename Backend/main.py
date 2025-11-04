import asyncio
import json
import math
import uuid
from datetime import datetime, timedelta
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from typing import List, Dict
from pathlib import Path
from io import StringIO
import csv
from bin_predictor import BinPredictor, BinPositionOptimizer, create_prediction_api_endpoints

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
TICK_SECONDS = 1.0          # real seconds between updates
SIM_SPEED = 1.0             # simulation speed multiplier
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

        # Broadcast simulation time + bin updates
        for u in updates:
            await manager.broadcast(u)

        await manager.broadcast({
            "type": "time_update",
            "sim_time_iso": SIMULATED_TIME.isoformat() + "Z",
            "sim_speed": SIM_SPEED
        })

        await asyncio.sleep(TICK_SECONDS)

# ------------------------------
# ⏱️ Periodic logger (every 15 simulated minutes)
# ------------------------------
async def periodic_logger():
    """Every 15 simulated minutes, snapshot all bins into BIN_HISTORY."""
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
# REST API
# ------------------------------
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

create_prediction_api_endpoints(app, predictor, optimizer, BINS, BIN_HISTORY)
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
                print("♻️ Simulation reset complete")

    except WebSocketDisconnect:
        manager.disconnect(websocket)

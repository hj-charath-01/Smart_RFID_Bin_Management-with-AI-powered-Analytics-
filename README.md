# VIT Vellore Smart Bin Simulator

A real-time waste bin monitoring and route optimization simulator built for the VIT Vellore campus. Bins fill up over time based on their population score, a WebSocket connection pushes updates live to the browser, and a machine learning backend predicts when each bin will be full and suggests where to place new ones.

---

## What it does

Each bin has a population score from 1 to 10 that controls how fast it fills. A score of 10 means the bin fills in about 6 hours; a score of 1 takes around 48 hours. The simulation runs server-side and ticks every second, with a configurable speed multiplier so you can fast-forward to see what happens over days.

When a bin hits 100% it pauses and waits to be collected. Collecting it resets the fill to zero and increments its collection count. All of this is broadcast over a WebSocket so every connected browser stays in sync.

On top of the simulation, there is an analytics layer that predicts time to fill for each active bin, scores bin efficiency, suggests optimal locations for new bins, and builds a collection route ordered by nearest-neighbor.

---

## Project layout

```
.
├── Backend/
│   ├── main.py                  # FastAPI server: WebSocket, REST endpoints, simulation loop
│   ├── bin_predictor.py         # ML prediction (GradientBoosting) and position optimizer
│   └── requirements.txt
└── frontend/
    ├── index.html               # main page
    ├── css/
    │   ├── style.css            # map and base layout
    │   └── analytics.css        # analytics panel components
    └── js/
        ├── ui.js                # top-level wiring: WebSocket events, charts, button handlers
        ├── map.js               # Leaflet map, marker creation and updates
        ├── analytics.js         # AnalyticsDashboard class, fetch and render analytics
        └── websocket.js         # WebSocket connect, send, message dispatch
```

---

## Setup and running

```bash
cd Backend
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

Then open http://localhost:8000 in a browser.

The frontend is served as static files from the FastAPI process, so there is no separate frontend build step.

---

## Using the simulator

**Adding bins** works by clicking anywhere on the map. A prompt asks for a population score. Bins with score 0 are treated as manual (they never fill on their own).

**Collecting a bin** opens the marker popup and clicking "Collect" sends a WebSocket message to the server, which resets fill to 0 and unpauses the bin.

**Speed control** buttons at the top right let you run the simulation at 1x, 10x, 60x, or 3600x real time. At 3600x, one real second equals one simulated hour.

**CSV export** downloads the full bin history as a time-series file. The server records a snapshot every 15 simulated minutes, plus events like adds, collections, and resets.

---

## Analytics panel

The analytics section sits below the map and has three parts.

**Fill time predictions** show how long each bin has until it is full, based on its fill rate and current level. Confidence is rated low/medium/high depending on how much history has accumulated. Once you have at least 50 records you can click "Train Model" to switch from the rule-based fallback to a GradientBoostingRegressor that uses spatial and temporal features.

**Suggested bin locations** run an optimization over a 50x50 grid of the campus bounds. Each candidate position is scored based on demand (inferred from nearby bin fill rates), distance to existing bins, and distance from the campus center. Clicking "Find Optimal Locations" generates three suggestions and pins them on the map. Clicking "Add Bin Here" from a suggestion card or map popup sends an add request directly.

**Efficiency analysis** scores each bin out of 100 based on its collection count and fill rate, and flags bins as optimal, normal, or underutilized.

The panel auto-refreshes predictions every 15 seconds while connected, and does a full refresh whenever a bin is added, collected, or removed.

---

## REST API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/predict_fill_time/{bin_id}` | Hours until a specific bin is full |
| GET | `/api/predict_all_bins` | Predictions for every bin |
| GET | `/api/suggest_new_bin` | Single optimal position for a new bin |
| POST | `/api/suggest_multiple_bins?num_bins=3` | Multiple suggested positions |
| GET | `/api/train_model` | Train the ML model on current history |
| GET | `/api/optimize_route?threshold=80` | Ordered collection route for bins above threshold |
| GET | `/api/analytics/predictions` | Detailed predictions for the analytics panel |
| POST | `/api/analytics/optimize?num_new_bins=3` | Optimal locations with coverage scores |
| GET | `/api/analytics/efficiency` | Per-bin efficiency scores |
| GET | `/api/analytics/summary` | Network-wide stats (total, full, empty, avg fill) |
| GET | `/api/download_csv` | Full bin history as a CSV download |

WebSocket connects at `ws://localhost:8000/ws`. Messages use a `type` field. Inbound types are `add_bin`, `collect`, `remove_bin`, `set_speed`, and `reset_simulation`. Outbound types are `initial_state`, `fill_update`, `bin_added`, `bin_removed`, `collected`, `bin_full`, `time_update`, `speed_changed`, and `reset_done`.

---

## ML model details

`BinPredictor` uses a `GradientBoostingRegressor` with 100 estimators. Features include population score, hour of day, day of week, weekend flag, collection count, days since last collection, 7-day average fill rate, nearby bin count, and distance to the campus center. The target variable is hours from collection to the bin reaching 100%.

Before the model is trained, predictions fall back to a simple linear formula: a score of 10 gives 6 hours to fill, a score of 1 gives 48 hours, with linear interpolation in between.

`BinPositionOptimizer` builds a demand heatmap from existing bin fill rates using a Gaussian falloff within 300m. Each grid position is scored by demand, spacing from existing bins (ideal is 150m to 400m), and distance from the campus center. Collection routes use a nearest-neighbor greedy traversal starting from the campus center as the depot.

---

## Notes

The simulation and all bin state are in-memory. Restarting the server clears everything. The 15-minute interval logger and the heartbeat that detects dead WebSocket connections both run as background asyncio tasks started at server startup.

Campus coordinates are hardcoded to VIT Vellore (centered at 12.9716, 79.1577) with bounds covering roughly the main campus area.

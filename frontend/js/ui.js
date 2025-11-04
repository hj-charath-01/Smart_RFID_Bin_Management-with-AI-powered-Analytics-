import { connectWS, onMessage, send } from './websocket.js';
import { map, createMarker, updateMarker, removeMarker, bins } from './map.js';

window.wsConnected = false;

document.getElementById('startBtn').onclick = () => {
  if (!window.wsConnected) {
    connectWS();
    window.wsConnected = true;
  } else {
    location.reload();
  }
};

// ============= MAP EVENTS =============
map.on('click', (e) => {
  if (e.originalEvent.target.closest('.leaflet-marker-icon')) return;
  let score = parseInt(prompt('Population score (0=manual, 1–10):', '0')) || 0;
  score = Math.min(Math.max(score, 0), 10);

  const bin = {
    id: 'BIN-' + Math.random().toString(36).slice(2, 8).toUpperCase(),
    rfid: 'RFID-' + Math.random().toString(16).slice(2,10).toUpperCase(),
    lat: e.latlng.lat,
    lng: e.latlng.lng,
    population_score: score,
    fill_pct: 0,
    collections: 0,
    paused: false
  };

  createMarker(bin);
  send({ type: 'add_bin', bin });
});

// ============= WS HANDLERS =============
onMessage('initial_state', (msg) => {
  (msg.bins || []).forEach(createMarker);
  if (msg.sim_time_iso) document.getElementById('simTime').innerText = new Date(msg.sim_time_iso).toLocaleString();
  if (msg.sim_speed) document.getElementById('simSpeed').innerText = msg.sim_speed + '×';
  updateCharts();
});

onMessage('bin_added', (msg) => { createMarker(msg.bin); updateCharts(); });

onMessage('fill_update', (msg) => {
  const b = bins[msg.bin_id];
  if (b) { 
    b.fill_pct = msg.fill_pct; 
    updateMarker(b); 
    updateCharts();
  }
});

onMessage('collected', (msg) => {
  const b = bins[msg.bin_id];
  if (b) {
    b.collections = msg.collections;
    b.fill_pct = 0;
    b.paused = false;
    updateMarker(b);
    updateCharts();
  }
});

onMessage('bin_removed', (msg) => { 
  removeMarker(msg.bin_id); 
  updateCharts();
});

onMessage('time_update', (msg) => {
  if (msg.sim_time_iso) document.getElementById('simTime').innerText = new Date(msg.sim_time_iso).toLocaleString();
});

onMessage('speed_changed', (msg) => {
  if (msg.sim_speed !== undefined) document.getElementById('simSpeed').innerText = msg.sim_speed + '×';
});

onMessage('reset_done', () => {
  // backend confirms full reset
  Object.values(bins).forEach(b => {
    b.fill_pct = 0;
    b.collections = 0;
    b.paused = false;
    updateMarker(b);
  });
  updateCharts();
});

// ============= SPEED CONTROL =============
document.querySelectorAll('.speed-controls .btn').forEach(btn => {
  btn.onclick = () => send({ type: 'set_speed', mult: Number(btn.dataset.speed) || 1 });
});

// ============= CSV DOWNLOAD (Full Time-Series) =============
document.getElementById('downloadCSV').onclick = async () => {
  try {
    const res = await fetch('http://127.0.0.1:8000/api/download_csv');
    if (!res.ok) throw new Error("No data available yet");

    const blob = await res.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `bin_history_${new Date().toISOString().replace(/[:.]/g, '-')}.csv`;
    a.click();
  } catch (err) {
    alert(err.message || "Failed to download dataset");
    console.error(err);
  }
};


// ============= RESET BUTTON =============
document.getElementById('resetSim').onclick = () => {
  if (!confirm('Reset all bins to initial state (fill = 0, collections = 0)?')) return;
  send({ type: 'reset_simulation' });
};

// ============= DASHBOARD CHARTS =============
const fillCtx = document.getElementById('fillChart').getContext('2d');
const collectCtx = document.getElementById('collectChart').getContext('2d');

let fillChart = new Chart(fillCtx, {
  type: 'doughnut',
  data: { 
    labels: ['Low (<25%)', 'Medium (25–75%)', 'High (>75%)'], 
    datasets: [{ 
      data: [0,0,0], 
      backgroundColor: ['#9ccc65','#ffee58','#ef5350'] 
    }] 
  },
  options: { plugins: { legend: { position: 'bottom' } } }
});

let collectChart = new Chart(collectCtx, {
  type: 'bar',
  data: { 
    labels: [], 
    datasets: [{ 
      label: 'Collections per Bin', 
      data: [], 
      backgroundColor: '#42a5f5' 
    }] 
  },
  options: { 
    plugins: { legend: { display: false } }, 
    scales: { y: { beginAtZero: true } } 
  }
});

function updateCharts() {
  const allBins = Object.values(bins);
  const low = allBins.filter(b => b.fill_pct < 25).length;
  const mid = allBins.filter(b => b.fill_pct >= 25 && b.fill_pct <= 75).length;
  const high = allBins.filter(b => b.fill_pct > 75).length;

  fillChart.data.datasets[0].data = [low, mid, high];
  fillChart.update();

  collectChart.data.labels = allBins.map(b => b.id);
  collectChart.data.datasets[0].data = allBins.map(b => b.collections);
  collectChart.update();
}

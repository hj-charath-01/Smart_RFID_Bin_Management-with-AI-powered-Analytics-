import { connectWS, onMessage, send } from './websocket.js';
import { map, createMarker, updateMarker, removeMarker, bins } from './map.js';
import { analyticsInstance } from './analytics.js';

window.wsConnected = false;

// Initialize analytics on page load
analyticsInstance.init();

// Make map globally accessible for analytics
window.mapInstance = map;

// Global function to add bin at location (used by analytics)
window.addBinAtLocation = function(lat, lng, popScore) {
  const bin = {
    id: 'BIN-' + Math.random().toString(36).slice(2, 8).toUpperCase(),
    rfid: 'RFID-' + Math.random().toString(16).slice(2, 10).toUpperCase(),
    lat: lat,
    lng: lng,
    population_score: popScore,
    fill_pct: 0,
    collections: 0,
    paused: false
  };

  createMarker(bin);
  send({ type: 'add_bin', bin });
  alert(`✅ Adding bin at ${lat.toFixed(4)}, ${lng.toFixed(4)}`);
};

document.getElementById('startBtn').onclick = () => {
  if (!window.wsConnected) {
    connectWS();
    window.wsConnected = true;
    analyticsInstance.onConnect();
  } else {
    location.reload();
  }
};

// ============= MAP EVENTS =============
map.on('click', (e) => {
  if (e.originalEvent.target.closest('.leaflet-marker-icon')) return;
  let score = parseInt(prompt('Population score (0=manual, 1–10):', '5')) || 5;
  score = Math.min(Math.max(score, 0), 10);

  const bin = {
    id: 'BIN-' + Math.random().toString(36).slice(2, 8).toUpperCase(),
    rfid: 'RFID-' + Math.random().toString(16).slice(2, 10).toUpperCase(),
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
  if (msg.sim_time_iso) {
    document.getElementById('simTime').innerText = new Date(msg.sim_time_iso).toLocaleString();
  }
  if (msg.sim_speed) {
    document.getElementById('simSpeed').innerText = msg.sim_speed + '×';
  }
  updateCharts();
  analyticsInstance.fetchAllAnalytics();
});

onMessage('bin_added', (msg) => { 
  createMarker(msg.bin); 
  updateCharts();
  // Refresh analytics after adding a bin
  setTimeout(() => analyticsInstance.fetchAllAnalytics(), 500);
});

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
    // Refresh analytics after collection
    setTimeout(() => analyticsInstance.fetchAllAnalytics(), 500);
  }
});

onMessage('bin_removed', (msg) => { 
  removeMarker(msg.bin_id); 
  updateCharts();
  setTimeout(() => analyticsInstance.fetchAllAnalytics(), 500);
});

onMessage('time_update', (msg) => {
  if (msg.sim_time_iso) {
    document.getElementById('simTime').innerText = new Date(msg.sim_time_iso).toLocaleString();
  }
});

onMessage('speed_changed', (msg) => {
  if (msg.sim_speed !== undefined) {
    document.getElementById('simSpeed').innerText = msg.sim_speed + '×';
  }
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
  setTimeout(() => analyticsInstance.fetchAllAnalytics(), 500);
});

// ============= SPEED CONTROL =============
document.querySelectorAll('.speed-controls .btn').forEach(btn => {
  btn.onclick = () => send({ type: 'set_speed', mult: Number(btn.dataset.speed) || 1 });
});

// ============= CSV DOWNLOAD (Full Time-Series) =============
document.getElementById('downloadCSV').onclick = async () => {
  try {
    const res = await fetch('/api/download_csv');
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
      data: [0, 0, 0], 
      backgroundColor: ['#9ccc65', '#ffee58', '#ef5350'] 
    }] 
  },
  options: { 
    plugins: { 
      legend: { position: 'bottom' },
      title: {
        display: true,
        text: 'Bin Fill Distribution'
      }
    } 
  }
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
    plugins: { 
      legend: { display: false },
      title: {
        display: true,
        text: 'Collection Activity'
      }
    }, 
    scales: { 
      y: { 
        beginAtZero: true,
        ticks: {
          stepSize: 1
        }
      } 
    } 
  }
});

function updateCharts() {
  const allBins = Object.values(bins);
  
  if (allBins.length === 0) {
    fillChart.data.datasets[0].data = [0, 0, 0];
    collectChart.data.labels = [];
    collectChart.data.datasets[0].data = [];
  } else {
    const low = allBins.filter(b => b.fill_pct < 25).length;
    const mid = allBins.filter(b => b.fill_pct >= 25 && b.fill_pct <= 75).length;
    const high = allBins.filter(b => b.fill_pct > 75).length;

    fillChart.data.datasets[0].data = [low, mid, high];
    
    collectChart.data.labels = allBins.map(b => b.id);
    collectChart.data.datasets[0].data = allBins.map(b => b.collections);
  }

  fillChart.update();
  collectChart.update();
}

// Auto-refresh analytics periodically when bins are updating
setInterval(() => {
  if (window.wsConnected && Object.keys(bins).length > 0) {
    analyticsInstance.fetchPredictions();
  }
}, 15000); // Every 15 seconds
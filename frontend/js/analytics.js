// analytics.js - Add this to your frontend/static/js folder

class AnalyticsDashboard {
    constructor() {
      this.predictions = [];
      this.optimalLocations = [];
      this.efficiency = [];
      this.updateInterval = null;
    }
  
    init() {
      this.createDashboardUI();
      this.startAutoUpdate();
    }
  
    createDashboardUI() {
      // Check if analytics section already exists
      if (document.getElementById('analytics-section')) return;
  
      const analyticsHTML = `
        <div id="analytics-section" class="analytics-container">
          <div class="analytics-header">
            <h3>🤖 AI-Powered Analytics</h3>
            <div class="analytics-controls">
              <button id="refreshAnalytics" class="btn">🔄 Refresh</button>
              <button id="findOptimalBtn" class="btn primary">📍 Find Optimal Locations</button>
              <button id="toggleAnalytics" class="btn">👁️ Hide</button>
            </div>
          </div>
  
          <div id="analyticsContent">
            <!-- Predictions Panel -->
            <div class="analytics-panel">
              <h4>⏱️ Fill Time Predictions</h4>
              <div id="predictionsContainer" class="predictions-grid">
                <p class="loading">Loading predictions...</p>
              </div>
            </div>
  
            <!-- Optimal Locations Panel -->
            <div class="analytics-panel">
              <h4>📍 Suggested Bin Locations</h4>
              <div id="optimalContainer">
                <p class="info">Click "Find Optimal Locations" to generate suggestions</p>
              </div>
            </div>
  
            <!-- Efficiency Panel -->
            <div class="analytics-panel">
              <h4>📊 Bin Efficiency Analysis</h4>
              <div id="efficiencyContainer">
                <p class="loading">Analyzing...</p>
              </div>
            </div>
          </div>
        </div>
      `;
  
      // Insert before dashboard or after map
      const mapEl = document.getElementById('map');
      if (mapEl) {
        mapEl.insertAdjacentHTML('afterend', analyticsHTML);
      }
  
      this.attachEventListeners();
    }
  
    attachEventListeners() {
      document.getElementById('refreshAnalytics')?.addEventListener('click', () => {
        this.fetchAllAnalytics();
      });
  
      document.getElementById('findOptimalBtn')?.addEventListener('click', () => {
        this.findOptimalLocations();
      });
  
      document.getElementById('toggleAnalytics')?.addEventListener('click', (e) => {
        const content = document.getElementById('analyticsContent');
        const btn = e.target;
        if (content.style.display === 'none') {
          content.style.display = 'block';
          btn.textContent = '👁️ Hide';
        } else {
          content.style.display = 'none';
          btn.textContent = '👁️ Show';
        }
      });
    }
  
    async fetchAllAnalytics() {
      await Promise.all([
        this.fetchPredictions(),
        this.fetchEfficiency()
      ]);
    }
  
    async fetchPredictions() {
      try {
        const response = await fetch('/api/analytics/predictions');
        const data = await response.json();
        
        if (data.success) {
          this.predictions = data.predictions;
          this.renderPredictions();
        }
      } catch (error) {
        console.error('Failed to fetch predictions:', error);
        this.showError('predictionsContainer', 'Failed to load predictions');
      }
    }
  
    async findOptimalLocations(numBins = 3) {
      try {
        const response = await fetch('/api/analytics/optimize', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ num_new_bins: numBins })
        });
        
        const data = await response.json();
        
        if (data.success) {
          this.optimalLocations = data.optimal_locations;
          this.renderOptimalLocations();
          this.displayOptimalOnMap();
        }
      } catch (error) {
        console.error('Failed to find optimal locations:', error);
        this.showError('optimalContainer', 'Failed to find optimal locations');
      }
    }
  
    async fetchEfficiency() {
      try {
        const response = await fetch('/api/analytics/efficiency');
        const data = await response.json();
        
        if (data.success) {
          this.efficiency = data.efficiency_analysis;
          this.renderEfficiency();
        }
      } catch (error) {
        console.error('Failed to fetch efficiency:', error);
        this.showError('efficiencyContainer', 'Failed to load efficiency data');
      }
    }
  
    renderPredictions() {
      const container = document.getElementById('predictionsContainer');
      if (!container) return;
  
      if (this.predictions.length === 0) {
        container.innerHTML = '<p class="info">No predictions available yet. Bins need more data.</p>';
        return;
      }
  
      const html = this.predictions.map(pred => {
        if (pred.status === 'full') {
          return `
            <div class="prediction-card full">
              <div class="pred-header">
                <strong>${pred.bin_id}</strong>
                <span class="status-badge full">FULL</span>
              </div>
              <p>Current: ${pred.current_fill.toFixed(1)}%</p>
            </div>
          `;
        } else if (pred.status === 'insufficient_data') {
          return `
            <div class="prediction-card pending">
              <div class="pred-header">
                <strong>${pred.bin_id}</strong>
                <span class="status-badge pending">PENDING</span>
              </div>
              <p>Collecting data... (${pred.current_fill.toFixed(1)}%)</p>
            </div>
          `;
        } else if (pred.time_to_full_hours !== undefined) {
          const hours = pred.time_to_full_hours;
          const timeStr = hours < 1 
            ? `${Math.round(hours * 60)} min` 
            : hours < 24 
            ? `${hours.toFixed(1)} hrs`
            : `${(hours / 24).toFixed(1)} days`;
          
          const confidenceColor = pred.confidence === 'high' ? 'green' : 
                                  pred.confidence === 'medium' ? 'orange' : 'red';
          
          return `
            <div class="prediction-card active">
              <div class="pred-header">
                <strong>${pred.bin_id}</strong>
                <span class="confidence-badge" style="background: ${confidenceColor}">
                  ${pred.confidence.toUpperCase()}
                </span>
              </div>
              <div class="pred-body">
                <p class="pred-time">⏱️ Time to full: <strong>${timeStr}</strong></p>
                <p class="pred-fill">📊 Fill rate: ${pred.fill_rate_per_hour.toFixed(2)}%/hr</p>
                <p class="pred-current">Current: ${pred.current_fill.toFixed(1)}%</p>
                ${pred.predicted_full_time ? 
                  `<p class="pred-date">📅 ${new Date(pred.predicted_full_time).toLocaleString()}</p>` 
                  : ''}
              </div>
            </div>
          `;
        }
        return '';
      }).join('');
  
      container.innerHTML = html;
    }
  
    renderOptimalLocations() {
      const container = document.getElementById('optimalContainer');
      if (!container) return;
  
      if (this.optimalLocations.length === 0) {
        container.innerHTML = '<p class="info">No optimal locations found.</p>';
        return;
      }
  
      const html = `
        <div class="optimal-locations-list">
          ${this.optimalLocations.map(loc => `
            <div class="optimal-card">
              <div class="optimal-header">
                <strong>${loc.location_id}</strong>
                <span class="score-badge">Score: ${loc.coverage_score}/10</span>
              </div>
              <div class="optimal-body">
                <p>📍 Lat: ${loc.lat}, Lng: ${loc.lng}</p>
                <p>👥 Est. Population: ${loc.estimated_population_score}/10</p>
                <p>📏 Nearest bin: ${loc.distance_to_nearest_bin_km} km</p>
                <p class="reason">${loc.reason}</p>
                <button class="btn btn-sm" onclick="analytics.addBinAtLocation(${loc.lat}, ${loc.lng}, ${loc.estimated_population_score})">
                  ➕ Add Bin Here
                </button>
              </div>
            </div>
          `).join('')}
        </div>
      `;
  
      container.innerHTML = html;
    }
  
    renderEfficiency() {
      const container = document.getElementById('efficiencyContainer');
      if (!container) return;
  
      if (this.efficiency.length === 0) {
        container.innerHTML = '<p class="info">Not enough data for efficiency analysis.</p>';
        return;
      }
  
      const html = `
        <div class="efficiency-list">
          ${this.efficiency.map(eff => `
            <div class="efficiency-card ${eff.status}">
              <div class="eff-header">
                <strong>${eff.bin_id}</strong>
                <span class="status-badge ${eff.status}">${eff.status.toUpperCase()}</span>
              </div>
              <div class="eff-body">
                <div class="eff-score">
                  <span class="score-label">Efficiency Score</span>
                  <span class="score-value">${eff.efficiency_score}/100</span>
                </div>
                <p>🔄 Collections: ${eff.collections}</p>
                <p>📈 Fill rate: ${eff.fill_rate_per_hour.toFixed(2)}%/hr</p>
                <div class="progress-bar">
                  <div class="progress-fill" style="width: ${eff.efficiency_score}%"></div>
                </div>
              </div>
            </div>
          `).join('')}
        </div>
      `;
  
      container.innerHTML = html;
    }
  
    displayOptimalOnMap() {
      // This function should interact with your Leaflet map
      // Assuming you have a global map object
      if (typeof window.map === 'undefined') return;
  
      // Clear previous optimal markers
      if (window.optimalMarkers) {
        window.optimalMarkers.forEach(m => window.map.removeLayer(m));
      }
      window.optimalMarkers = [];
  
      // Add new optimal location markers
      this.optimalLocations.forEach(loc => {
        const marker = L.marker([loc.lat, loc.lng], {
          icon: L.divIcon({
            className: 'optimal-marker',
            html: `<div class="optimal-pin">
              <span>📍</span>
              <div class="optimal-label">${loc.location_id}</div>
            </div>`,
            iconSize: [40, 40]
          })
        }).addTo(window.map);
  
        marker.bindPopup(`
          <strong>${loc.location_id}</strong><br>
          Coverage Score: ${loc.coverage_score}/10<br>
          Est. Population: ${loc.estimated_population_score}/10<br>
          <button onclick="analytics.addBinAtLocation(${loc.lat}, ${loc.lng}, ${loc.estimated_population_score})">
            Add Bin
          </button>
        `);
  
        window.optimalMarkers.push(marker);
      });
    }
  
    addBinAtLocation(lat, lng, popScore) {
      // This should trigger your existing "add bin" functionality
      // Emit via WebSocket or call your existing add bin function
      if (window.ws && window.ws.readyState === WebSocket.OPEN) {
        window.ws.send(JSON.stringify({
          type: 'add_bin',
          bin: {
            lat: lat,
            lng: lng,
            population_score: popScore,
            fill_pct: 0,
            collections: 0
          }
        }));
        alert(`Adding bin at ${lat.toFixed(4)}, ${lng.toFixed(4)}`);
      }
    }
  
    showError(containerId, message) {
      const container = document.getElementById(containerId);
      if (container) {
        container.innerHTML = `<p class="error">${message}</p>`;
      }
    }
  
    startAutoUpdate() {
      // Update predictions every 30 seconds
      this.updateInterval = setInterval(() => {
        this.fetchAllAnalytics();
      }, 30000);
    }
  
    stopAutoUpdate() {
      if (this.updateInterval) {
        clearInterval(this.updateInterval);
      }
    }
  }
  
  // Initialize analytics dashboard
  const analytics = new AnalyticsDashboard();
  
  // Auto-init when page loads
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => analytics.init());
  } else {
    analytics.init();
  }
  
  // Export for use in other modules
  export default analytics;
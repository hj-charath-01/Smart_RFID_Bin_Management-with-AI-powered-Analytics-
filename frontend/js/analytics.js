// analytics.js - AI-Powered Analytics Dashboard

export class AnalyticsDashboard {
    constructor() {
      this.predictions = [];
      this.optimalLocations = [];
      this.efficiency = [];
      this.updateInterval = null;
      this.isConnected = false;
    }
  
    init() {
      this.attachEventListeners();
      console.log('📊 Analytics dashboard initialized');
    }
  
    attachEventListeners() {
      const refreshBtn = document.getElementById('refreshAnalytics');
      const trainBtn = document.getElementById('trainModel');
      const findOptimalBtn = document.getElementById('findOptimalBtn');
      const toggleBtn = document.getElementById('toggleAnalytics');
  
      if (refreshBtn) {
        refreshBtn.addEventListener('click', () => this.fetchAllAnalytics());
      }
  
      if (trainBtn) {
        trainBtn.addEventListener('click', () => this.trainModel());
      }
  
      if (findOptimalBtn) {
        findOptimalBtn.addEventListener('click', () => this.findOptimalLocations());
      }
  
      if (toggleBtn) {
        toggleBtn.addEventListener('click', (e) => {
          const content = document.getElementById('analyticsContent');
          if (content.style.display === 'none') {
            content.style.display = 'block';
            e.target.textContent = '👁️ Hide';
          } else {
            content.style.display = 'none';
            e.target.textContent = '👁️ Show';
          }
        });
      }
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
  
    async trainModel() {
      try {
        const response = await fetch('/api/train_model');
        const data = await response.json();
        
        if (data.success) {
          alert(`✅ Model trained successfully!\n${data.training_samples} samples used.`);
          await this.fetchAllAnalytics();
        } else {
          alert(`⚠️ ${data.message || 'Failed to train model'}`);
        }
      } catch (error) {
        console.error('Failed to train model:', error);
        alert('❌ Failed to train model');
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
        container.innerHTML = '<p class="info">No bins available. Add bins to see predictions.</p>';
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
              <div class="pred-body">
                <p>Current: ${pred.current_fill.toFixed(1)}%</p>
                <p style="color: #f44336;">⚠️ Needs collection</p>
              </div>
            </div>
          `;
        } else if (pred.status === 'manual') {
          return `
            <div class="prediction-card">
              <div class="pred-header">
                <strong>${pred.bin_id}</strong>
                <span class="status-badge" style="background: #9e9e9e;">MANUAL</span>
              </div>
              <div class="pred-body">
                <p>Current: ${pred.current_fill.toFixed(1)}%</p>
                <p style="font-size: 12px; color: #777;">Manual control (score = 0)</p>
              </div>
            </div>
          `;
        } else if (pred.status === 'insufficient_data') {
          return `
            <div class="prediction-card pending">
              <div class="pred-header">
                <strong>${pred.bin_id}</strong>
                <span class="status-badge pending">LEARNING</span>
              </div>
              <div class="pred-body">
                <p>Current: ${pred.current_fill.toFixed(1)}%</p>
                <p style="font-size: 12px; color: #777;">Collecting data for predictions...</p>
              </div>
            </div>
          `;
        } else if (pred.status === 'active' && pred.time_to_full_hours !== undefined) {
          const hours = pred.time_to_full_hours;
          const timeStr = hours < 1 
            ? `${Math.round(hours * 60)} min` 
            : hours < 24 
            ? `${hours.toFixed(1)} hrs`
            : `${(hours / 24).toFixed(1)} days`;
          
          const confidenceColors = {
            'high': '#4CAF50',
            'medium': '#ff9800',
            'low': '#f44336'
          };
          const confidenceColor = confidenceColors[pred.confidence] || '#9e9e9e';
          
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
                <p>📈 Fill rate: ${pred.fill_rate_per_hour.toFixed(2)}%/hr</p>
                <p>📊 Current: ${pred.current_fill.toFixed(1)}%</p>
                ${pred.predicted_full_time ? 
                  `<p class="pred-date">📅 ${new Date(pred.predicted_full_time).toLocaleString()}</p>` 
                  : ''}
              </div>
            </div>
          `;
        }
        return '';
      }).join('');
  
      container.innerHTML = html || '<p class="info">No predictions available</p>';
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
                <p>📍 Lat: ${loc.lat.toFixed(6)}, Lng: ${loc.lng.toFixed(6)}</p>
                <p>👥 Est. Population: ${loc.estimated_population_score}/10</p>
                <p>📏 Nearest bin: ${loc.distance_to_nearest_bin_km.toFixed(2)} km</p>
                <p class="reason">${loc.reason}</p>
                <button class="btn btn-sm" onclick="window.addBinAtLocation(${loc.lat}, ${loc.lng}, ${loc.estimated_population_score})">
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
                <p>📊 Current: ${eff.current_fill.toFixed(1)}%</p>
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
      // Access global map object
      if (typeof window.mapInstance === 'undefined') {
        console.warn('Map not available');
        return;
      }
  
      const map = window.mapInstance;
  
      // Clear previous optimal markers
      if (window.optimalMarkers) {
        window.optimalMarkers.forEach(m => map.removeLayer(m));
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
        }).addTo(map);
  
        marker.bindPopup(`
          <div style="font-size: 14px; min-width: 200px;">
            <strong>${loc.location_id}</strong><br>
            Coverage Score: ${loc.coverage_score}/10<br>
            Est. Population: ${loc.estimated_population_score}/10<br>
            <button class="btn" style="margin-top: 8px;" onclick="window.addBinAtLocation(${loc.lat}, ${loc.lng}, ${loc.estimated_population_score})">
              ➕ Add Bin
            </button>
          </div>
        `);
  
        window.optimalMarkers.push(marker);
      });
  
      console.log(`📍 Added ${this.optimalLocations.length} optimal location markers`);
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
        if (this.isConnected) {
          this.fetchAllAnalytics();
        }
      }, 30000);
      console.log('🔄 Auto-update started (30s interval)');
    }
  
    stopAutoUpdate() {
      if (this.updateInterval) {
        clearInterval(this.updateInterval);
        this.updateInterval = null;
        console.log('⏸️ Auto-update stopped');
      }
    }
  
    onConnect() {
      this.isConnected = true;
      this.fetchAllAnalytics();
      this.startAutoUpdate();
    }
  
    onDisconnect() {
      this.isConnected = false;
      this.stopAutoUpdate();
    }
  }
  
  // Create global instance
  export const analyticsInstance = new AnalyticsDashboard();
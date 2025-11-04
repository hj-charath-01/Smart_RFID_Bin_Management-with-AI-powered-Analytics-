import { send } from './websocket.js';

export const bins = {};
export const markers = {};

export const map = L.map('map').setView([12.9716, 79.1636], 16);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19 }).addTo(map);

const greenIcon = L.divIcon({ className: 'marker-green' });
const redIcon   = L.divIcon({ className: 'marker-red' });

function getIcon(fillPct) { 
  return fillPct >= 75 ? redIcon : greenIcon; 
}

export function createMarker(bin) {
  bins[bin.id] = { ...bin };

  const marker = L.marker([bin.lat, bin.lng], { icon: getIcon(bin.fill_pct), draggable: true }).addTo(map);
  markers[bin.id] = marker;
  bins[bin.id].marker = marker;

  marker.on('dragend', (e) => {
    const pos = e.target.getLatLng();
    bins[bin.id].lat = pos.lat;
    bins[bin.id].lng = pos.lng;
  });

  bindPopup(bin, marker);
}

export function updateMarker(bin) {
  bins[bin.id] = { ...bins[bin.id], ...bin };
  const marker = markers[bin.id];
  if (!marker) return;

  marker.setIcon(getIcon(bin.fill_pct));

  const popupNode = marker.getPopup()?._contentNode;
  if (popupNode) {
    popupNode.querySelector('.fill').innerText = Math.round(bin.fill_pct) + '%';
    popupNode.querySelector('.collections').innerText = bin.collections;
    popupNode.querySelector('.bar').style.width = Math.round(bin.fill_pct) + '%';
  }
}

function bindPopup(bin, marker) {
  const popup = `
    <div style="font-size:14px">
      <b>${bin.id}</b><br>
      RFID: <code>${bin.rfid}</code><br>
      Score: ${bin.population_score}<br>
      Collections: <span class="collections">${bin.collections}</span><br>
      <div style="margin-top:6px">
        <div class="progress"><div class="bar" style="width:${Math.round(bin.fill_pct)}%"></div></div>
        <div style="font-size:12px;margin-top:4px" class="fill">${Math.round(bin.fill_pct)}%</div>
      </div>
      <div style="margin-top:6px; display:flex; flex-wrap:wrap; gap:6px;">
        <button class="btn collect">Collect</button>
        <button class="btn remove" style="background:#fceaea">Remove</button>
        <button class="btn model" style="background:#d6ecff">3D Model</button>
      </div>
    </div>
  `;

  marker.bindPopup(popup);

  marker.on('popupopen', (e) => {
    const el = e.popup._contentNode;

    el.querySelector('.collect').onclick = () => send({ type: 'collect', bin_id: bin.id });

    el.querySelector('.remove').onclick = () => {
      removeMarker(bin.id);
      send({ type: 'remove_bin', bin_id: bin.id });
    };

    // new: open 3D model prototype
    el.querySelector('.model').onclick = () => {
      window.open(`model.html?bin=${bin.id}`, "_blank", "width=800,height=600");
    };
  });
}

export function removeMarker(bin_id) {
  const marker = markers[bin_id];
  if (marker) {
    map.closePopup();
    map.removeLayer(marker);
    delete markers[bin_id];
  }
  if (bins[bin_id]) delete bins[bin_id];
}

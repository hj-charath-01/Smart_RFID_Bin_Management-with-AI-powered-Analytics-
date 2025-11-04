// websocket.js
export let ws = null;
let handlers = {};

export function onMessage(type, fn) { handlers[type] = fn; }

export function send(msg) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
}

export function connectWS() {
  const WS_URL = `ws://${location.hostname}:8000/ws`;
  ws = new WebSocket(WS_URL);

  ws.addEventListener('open', () => {
    document.getElementById('status').innerText = 'Connected';
    document.getElementById('startBtn').innerText = 'Disconnect';
  });

  ws.addEventListener('message', (ev) => {
    const msg = JSON.parse(ev.data);
    const fn = handlers[msg.type];
    if (fn) fn(msg);
  });

  ws.addEventListener('close', () => {
    document.getElementById('status').innerText = 'Disconnected';
    document.getElementById('startBtn').innerText = 'Connect';
    ws = null;
  });

  ws.addEventListener('error', (e) => console.error('WS error:', e));

  setInterval(() => { if (ws && ws.readyState === WebSocket.OPEN) send({ type: 'ping' }); }, 30000);
}

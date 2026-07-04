/**
 * API Client - communicates with the FastAPI backend
 */

const API = {
    baseUrl: '',

    async get(endpoint) {
        const res = await fetch(this.baseUrl + endpoint);
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(err.detail || `HTTP ${res.status}`);
        }
        return res.json();
    },

    async post(endpoint, body = null) {
        const opts = { method: 'POST', headers: {} };
        if (body) {
            opts.headers['Content-Type'] = 'application/json';
            opts.body = JSON.stringify(body);
        }
        const res = await fetch(this.baseUrl + endpoint, opts);
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(err.detail || `HTTP ${res.status}`);
        }
        return res.json();
    },

    async put(endpoint, body) {
        const res = await fetch(this.baseUrl + endpoint, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(err.detail || `HTTP ${res.status}`);
        }
        return res.json();
    },

    // Status
    getStatus() { return this.get('/api/status'); },

    // Sensors
    getSensors() { return this.get('/api/sensors'); },
    rescanSensors(rescanDisks = false) {
        return this.post('/api/sensors/rescan', { rescan_disks: rescanDisks });
    },

    // Fans
    getFans() { return this.get('/api/fans'); },
    setFanMode(fanName, mode) {
        return this.put(`/api/fans/${encodeURIComponent(fanName)}/mode`, { mode });
    },
    setFanPwm(fanName, pwm) {
        return this.put(`/api/fans/${encodeURIComponent(fanName)}/pwm`, { pwm });
    },
    updateFanCurve(fanName, curve) {
        return this.put(`/api/fans/${encodeURIComponent(fanName)}/curve`, { curve });
    },

    // History
    getHistory(fanName, limit = 100) {
        let url = `/api/history?limit=${limit}`;
        if (fanName) url += `&fan_name=${encodeURIComponent(fanName)}`;
        return this.get(url);
    },

    // Config
    getConfig() { return this.get('/api/config'); },
    updateConfig(config) { return this.put('/api/config', config); },
    saveConfig() { return this.post('/api/config/save'); },
};

/**
 * WebSocket connection manager
 */
class WSManager {
    constructor() {
        this.ws = null;
        this.connected = false;
        this.listeners = [];
        this.reconnectTimer = null;
        this.pingTimer = null;
    }

    connect() {
        const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${location.host}/ws`;

        try {
            this.ws = new WebSocket(wsUrl);
        } catch (e) {
            console.error('WebSocket creation failed:', e);
            this.scheduleReconnect();
            return;
        }

        this.ws.onopen = () => {
            this.connected = true;
            this.updateStatus(true);
            this.startPing();
            console.log('WebSocket connected');
        };

        this.ws.onmessage = (event) => {
            try {
                const msg = JSON.parse(event.data);
                this.listeners.forEach(fn => fn(msg));
            } catch (e) {
                console.error('WebSocket message parse error:', e);
            }
        };

        this.ws.onclose = () => {
            this.connected = false;
            this.updateStatus(false);
            this.stopPing();
            this.scheduleReconnect();
        };

        this.ws.onerror = (err) => {
            console.error('WebSocket error:', err);
        };
    }

    scheduleReconnect() {
        if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
        this.reconnectTimer = setTimeout(() => {
            console.log('Attempting WebSocket reconnect...');
            this.connect();
        }, 3000);
    }

    startPing() {
        this.pingTimer = setInterval(() => {
            if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                this.ws.send(JSON.stringify({ type: 'ping' }));
            }
        }, 30000);
    }

    stopPing() {
        if (this.pingTimer) {
            clearInterval(this.pingTimer);
            this.pingTimer = null;
        }
    }

    updateStatus(connected) {
        const dot = document.querySelector('.status-dot');
        const text = document.querySelector('.status-text');
        if (dot && text) {
            dot.className = `status-dot ${connected ? 'connected' : 'disconnected'}`;
            text.textContent = connected ? '已连接' : '未连接';
        }
    }

    onMessage(fn) {
        this.listeners.push(fn);
    }

    send(data) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(data));
        }
    }
}

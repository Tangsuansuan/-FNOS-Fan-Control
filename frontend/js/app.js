/**
 * FNOS Fan Controller - Main Application Logic
 */

const ws = new WSManager();
let currentStatus = null;
let updateTimer = null;

// ===== Initialization =====
document.addEventListener('DOMContentLoaded', () => {
    initNavigation();
    Charts.initCharts();
    CurveEditor.init();
    ws.connect();
    ws.onMessage(handleWsMessage);
    fetchInitialData();

    // Poll for status updates as backup to WebSocket
    updateTimer = setInterval(fetchStatus, 5000);
});

// ===== Navigation =====
function initNavigation() {
    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', () => {
            document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
            document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
            item.classList.add('active');
            const pageId = `page-${item.dataset.page}`;
            const page = document.getElementById(pageId);
            if (page) page.classList.add('active');

            // Lazy load page data
            const pageName = item.dataset.page;
            if (pageName === 'sensors') fetchSensors();
            if (pageName === 'fans') fetchFans();
            if (pageName === 'curve') initCurveEditor();
            if (pageName === 'settings') fetchConfig();
            if (pageName === 'history') loadHistory();
        });
    });
}

// ===== WebSocket Handler =====
function handleWsMessage(msg) {
    if (msg.type === 'status' && msg.data) {
        currentStatus = msg.data;
        renderDashboard(msg.data);
    } else if (msg.type === 'pong') {
        // Keepalive response
    }
}

// ===== Data Fetching =====
async function fetchInitialData() {
    try {
        const status = await API.getStatus();
        currentStatus = status;
        renderDashboard(status);

        const history = await API.getHistory(null, 60);
        Charts.updateTempChart(history);
        Charts.updateRpmChart(history);
    } catch (e) {
        showToast(`初始化失败: ${e.message}`, 'error');
        console.error(e);
    }
}

async function fetchStatus() {
    try {
        const status = await API.getStatus();
        currentStatus = status;
        renderDashboard(status);
    } catch (e) {
        // Silent fail for polling
        console.debug('Status fetch error:', e.message);
    }
}

async function fetchSensors() {
    try {
        const data = await API.getSensors();
        renderSensors(data);
    } catch (e) {
        showToast(`获取传感器失败: ${e.message}`, 'error');
    }
}

async function fetchFans() {
    try {
        const data = await API.getFans();
        renderFanControls(data.fans);
    } catch (e) {
        showToast(`获取风扇信息失败: ${e.message}`, 'error');
    }
}

async function fetchConfig() {
    try {
        const cfg = await API.getConfig();
        document.getElementById('setting-update-interval').value = cfg.update_interval || 2;
        document.getElementById('setting-history-length').value = cfg.data_history_length || 300;
        document.getElementById('setting-enable-alerts').checked = cfg.enable_alerts || false;
        document.getElementById('setting-alert-cpu').value = cfg.alert_temp_cpu || 85;
        document.getElementById('setting-alert-disk').value = cfg.alert_temp_disk || 60;
        document.getElementById('setting-enable-smartctl').checked = cfg.enable_smartctl !== false;
        document.getElementById('setting-smartctl-path').value = cfg.smartctl_path || '/usr/sbin/smartctl';
        // History retention
        document.getElementById('setting-history-retention').value = cfg.history_retention_days || 30;
        // SMTP
        document.getElementById('setting-alert-enabled').checked = cfg.alert_enabled || false;
        document.getElementById('setting-smtp-host').value = cfg.smtp_host || '';
        document.getElementById('setting-smtp-port').value = cfg.smtp_port || 465;
        document.getElementById('setting-smtp-tls').checked = cfg.smtp_use_tls !== false;
        document.getElementById('setting-smtp-user').value = cfg.smtp_user || '';
        document.getElementById('setting-smtp-password').value = cfg.smtp_password || '';
        document.getElementById('setting-smtp-from').value = cfg.smtp_from || '';
        document.getElementById('setting-smtp-to').value = cfg.smtp_to || '';
        document.getElementById('setting-alert-cooldown').value = cfg.alert_cooldown_minutes || 30;
    } catch (e) {
        showToast(`获取配置失败: ${e.message}`, 'error');
    }
}

// ===== Dashboard Rendering =====
function renderDashboard(status) {
    renderTempCards(status.temperatures || {});
    renderFanCards(status.fans || []);
    renderAlerts(status.alerts || []);

    // Update charts with latest history periodically
    if (Math.random() < 0.3) { // ~30% chance each update to refresh charts
        refreshCharts();
    }
}

function renderTempCards(temps) {
    const container = document.getElementById('temp-cards');
    if (!container) return;

    const entries = Object.entries(temps);
    container.innerHTML = entries.map(([name, temp]) => {
        const tempClass = Charts.getTempClass(temp);
        const color = Charts.getTempColor(temp);
        const displayName = name.startsWith('disk:') ?
            `💾 ${name.replace('disk:', '').replace('/dev/', '')}` :
            `🌡️ ${name}`;
        const source = name.startsWith('disk:') ? 'SMART' : 'hwmon';

        return `
            <div class="temp-card ${tempClass}">
                <div class="temp-card-label">${displayName}</div>
                <div class="temp-card-value" style="color: ${color}">
                    ${temp.toFixed(1)}<span class="temp-card-unit">°C</span>
                </div>
                <div class="temp-card-source">${source}</div>
            </div>
        `;
    }).join('');

    if (entries.length === 0) {
        container.innerHTML = '<div style="color: var(--text-muted); padding: 20px;">未检测到温度传感器</div>';
    }
}

function renderFanCards(fans) {
    const container = document.getElementById('fan-cards');
    if (!container) return;

    if (!fans || fans.length === 0) {
        container.innerHTML = '<div style="color: var(--text-muted); padding: 20px;">未检测到可控风扇</div>';
        return;
    }

    container.innerHTML = fans.map(fan => {
        const pwmPercent = fan.pwm_percent || 0;
        return `
            <div class="fan-card">
                <div class="fan-card-header">
                    <span class="fan-card-name">🌀 ${fan.name}</span>
                    <span class="fan-mode-badge ${fan.mode}">${fan.mode}</span>
                </div>
                <div class="fan-card-stats">
                    <div class="fan-stat">
                        <span class="fan-stat-label">转速</span>
                        <span class="fan-stat-value">${fan.current_rpm}<span class="fan-stat-unit"> RPM</span></span>
                    </div>
                    <div class="fan-stat">
                        <span class="fan-stat-label">PWM</span>
                        <span class="fan-stat-value">${fan.current_pwm}<span class="fan-stat-unit"> / 255</span></span>
                    </div>
                    <div class="fan-stat">
                        <span class="fan-stat-label">参考温度</span>
                        <span class="fan-stat-value" style="color:${Charts.getTempColor(fan.reference_temp)}">${fan.reference_temp.toFixed(1)}<span class="fan-stat-unit">°C</span></span>
                    </div>
                </div>
                <div class="fan-pwm-bar">
                    <div class="fan-pwm-bar-fill" style="width: ${pwmPercent}%"></div>
                </div>
                <div class="fan-controls">
                    <button class="btn btn-sm ${fan.mode === 'curve' ? 'active' : ''}" onclick="setFanMode('${fan.name}', 'curve')">曲线</button>
                    <button class="btn btn-sm ${fan.mode === 'manual' ? 'active' : ''}" onclick="setFanMode('${fan.name}', 'manual')">手动</button>
                    <button class="btn btn-sm ${fan.mode === 'auto' ? 'active' : ''}" onclick="setFanMode('${fan.name}', 'auto')">自动</button>
                </div>
            </div>
        `;
    }).join('');
}

function renderAlerts(alerts) {
    const container = document.getElementById('alerts-container');
    if (!container) return;

    if (!alerts || alerts.length === 0) {
        container.innerHTML = '';
        return;
    }

    container.innerHTML = alerts.map(a => `
        <div class="alert-banner">
            <span class="alert-icon">⚠️</span>
            <div class="alert-text">
                <span class="alert-sensor">${a.sensor}</span>:
                ${a.message}
            </div>
        </div>
    `).join('');
}

// ===== Fan Control Page =====
function renderFanControls(fans) {
    const container = document.getElementById('fan-control-list');
    if (!container) return;

    if (!fans || fans.length === 0) {
        container.innerHTML = '<div style="color: var(--text-muted); padding: 40px; text-align: center;">未检测到可控风扇。请确认硬件支持PWM控制，并检查系统权限。</div>';
        return;
    }

    container.innerHTML = fans.map(fan => `
        <div class="fan-control-card">
            <div class="fan-control-header">
                <div>
                    <h3 style="margin-bottom: 4px;">🌀 ${fan.name}</h3>
                    <div style="font-size: 12px; color: var(--text-muted);">
                        路径: ${fan.hwmon_path} | PWM通道: ${fan.pwm_channel}
                    </div>
                </div>
                <div style="display: flex; gap: 24px; align-items: center;">
                    <div style="text-align: center;">
                        <div style="font-size: 12px; color: var(--text-secondary);">转速</div>
                        <div style="font-size: 24px; font-weight: 700;">${fan.current_rpm}</div>
                        <div style="font-size: 11px; color: var(--text-muted);">RPM</div>
                    </div>
                    <div style="text-align: center;">
                        <div style="font-size: 12px; color: var(--text-secondary);">PWM</div>
                        <div style="font-size: 24px; font-weight: 700;">${fan.current_pwm}</div>
                        <div style="font-size: 11px; color: var(--text-muted);">/ 255</div>
                    </div>
                </div>
            </div>
            <div class="fan-mode-selector">
                <button class="btn ${fan.mode === 'curve' ? 'btn-primary active' : ''}" onclick="setFanMode('${fan.name}', 'curve')">📈 曲线控制</button>
                <button class="btn ${fan.mode === 'manual' ? 'btn-primary active' : ''}" onclick="setFanMode('${fan.name}', 'manual')">🎮 手动控制</button>
                <button class="btn ${fan.mode === 'auto' ? 'btn-primary active' : ''}" onclick="setFanMode('${fan.name}', 'auto')">⚙️ 自动 (BIOS)</button>
            </div>
            <div class="fan-manual-control" id="manual-control-${fan.name}" style="${fan.mode === 'manual' ? '' : 'display: none;'}">
                <label style="white-space: nowrap;">手动PWM:</label>
                <input type="range" min="0" max="255" value="${fan.current_pwm}"
                    oninput="document.getElementById('pwm-value-${fan.name}').textContent = this.value"
                    onchange="setFanPwm('${fan.name}', this.value)" class="fan-manual-slider">
                <span id="pwm-value-${fan.name}" style="font-size: 18px; font-weight: 700; min-width: 40px;">${fan.current_pwm}</span>
            </div>
            <div style="margin-top: 16px;">
                <h4 style="font-size: 13px; color: var(--text-secondary); margin-bottom: 8px;">当前曲线</h4>
                <div style="display: flex; gap: 8px; flex-wrap: wrap;">
                    ${fan.curve.map(p => `
                        <div style="background: var(--bg-input); padding: 4px 12px; border-radius: 6px; font-size: 12px;">
                            ${p.temp}°C → ${p.pwm}
                        </div>
                    `).join('')}
                </div>
            </div>
        </div>
    `).join('');
}

// ===== Actions =====
async function setFanMode(fanName, mode) {
    try {
        await API.setFanMode(fanName, mode);
        showToast(`风扇 ${fanName} 已切换至 ${mode} 模式`, 'success');
        fetchFans();
        fetchStatus();
    } catch (e) {
        showToast(`设置失败: ${e.message}`, 'error');
    }
}

async function setFanPwm(fanName, pwm) {
    try {
        await API.setFanPwm(fanName, parseInt(pwm));
        // No toast for rapid slider changes
    } catch (e) {
        showToast(`设置PWM失败: ${e.message}`, 'error');
    }
}

async function rescanSensors(rescanDisks = false) {
    try {
        showToast('正在重新扫描传感器...', 'info');
        const result = await API.rescanSensors(rescanDisks);
        showToast(`扫描完成: ${result.sensors.hwmon_devices.length} 个hwmon设备, ${result.sensors.disks.length} 个硬盘`, 'success');
        fetchStatus();
        fetchSensors();
    } catch (e) {
        showToast(`重新扫描失败: ${e.message}`, 'error');
    }
}

// ===== Sensors Page =====
function renderSensors(data) {
    const container = document.getElementById('sensors-list');
    if (!container) return;

    let html = '';

    // Hwmon devices
    data.hwmon_devices.forEach(dev => {
        let rows = '';

        // Temperatures
        if (dev.temperatures.length > 0) {
            rows += `<div class="sensor-row header">
                <div>传感器</div><div>类型</div><div>当前值</div><div>来源</div>
            </div>`;
            dev.temperatures.forEach(s => {
                rows += `
                    <div class="sensor-row">
                        <div>${s.label || s.name} ${s.label ? `<span style="color:var(--text-muted);font-size:11px">(${s.name})</span>` : ''}</div>
                        <div>🌡️ 温度</div>
                        <div style="color:${Charts.getTempColor(s.current_value)};font-weight:600">${s.current_value.toFixed(1)}°C</div>
                        <div>hwmon</div>
                    </div>`;
            });
        }

        // Fan RPMs
        if (dev.fan_rpms.length > 0) {
            dev.fan_rpms.forEach(s => {
                rows += `
                    <div class="sensor-row">
                        <div>${s.label || s.name}</div>
                        <div>🌀 转速</div>
                        <div style="font-weight:600">${s.current_value} RPM</div>
                        <div>hwmon</div>
                    </div>`;
            });
        }

        // Fan PWMs
        if (dev.fan_pwms.length > 0) {
            dev.fan_pwms.forEach(s => {
                const pct = Math.round(s.current_value / 255 * 100);
                rows += `
                    <div class="sensor-row">
                        <div>${s.name}</div>
                        <div>⚡ PWM控制</div>
                        <div style="font-weight:600">${s.current_value} (${pct}%)</div>
                        <div>hwmon</div>
                    </div>`;
            });
        }

        if (rows) {
            html += `
                <div class="sensor-group">
                    <div class="sensor-group-header">
                        <h3>📦 ${dev.name}</h3>
                        <span class="badge">${dev.hwmon_path}</span>
                    </div>
                    <div class="sensor-table">${rows}</div>
                </div>`;
        }
    });

    // Disks
    if (data.disks.length > 0) {
        let diskRows = `<div class="sensor-row header">
            <div>设备</div><div>型号</div><div>温度</div><div>类型</div>
        </div>`;
        data.disks.forEach(d => {
            diskRows += `
                <div class="sensor-row">
                    <div>${d.device}</div>
                    <div>${d.model || '-'}</div>
                    <div style="color:${Charts.getTempColor(d.temperature)};font-weight:600">${d.temperature.toFixed(1)}°C</div>
                    <div>${d.is_nvme ? 'NVMe' : 'SATA'}</div>
                </div>`;
        });
        html += `
            <div class="sensor-group">
                <div class="sensor-group-header">
                    <h3>💾 硬盘</h3>
                    <span class="badge">${data.disks.length} 个设备</span>
                </div>
                <div class="sensor-table">${diskRows}</div>
            </div>`;
    }

    container.innerHTML = html || '<div style="color: var(--text-muted); padding: 40px; text-align: center;">未检测到传感器</div>';
}

// ===== Curve Editor =====
async function initCurveEditor() {
    if (!currentStatus || !currentStatus.fans) {
        const status = await API.getStatus();
        currentStatus = status;
    }

    const selector = document.getElementById('curve-fan-selector');
    selector.innerHTML = currentStatus.fans.map(f =>
        `<option value="${f.name}">${f.name}</option>`
    ).join('');

    if (currentStatus.fans.length > 0) {
        selectFanForCurve();
    }
}

function selectFanForCurve() {
    const selector = document.getElementById('curve-fan-selector');
    const fanName = selector.value;
    const fan = currentStatus.fans.find(f => f.name === fanName);

    if (fan && fan.curve) {
        CurveEditor.setPoints(fan.curve);
    }
}

async function saveCurve() {
    const selector = document.getElementById('curve-fan-selector');
    const fanName = selector.value;
    const points = CurveEditor.getPoints();

    if (points.length < 2) {
        showToast('至少需要两个曲线节点', 'error');
        return;
    }

    // Validate points are sorted and valid
    for (let i = 0; i < points.length - 1; i++) {
        if (points[i].temp >= points[i + 1].temp) {
            showToast('温度节点必须按升序排列', 'error');
            return;
        }
    }

    try {
        await API.updateFanCurve(fanName, points);
        showToast(`风扇 ${fanName} 的温度曲线已保存`, 'success');
    } catch (e) {
        showToast(`保存失败: ${e.message}`, 'error');
    }
}

function resetCurve() {
    CurveEditor.setPoints([
        { temp: 30, pwm: 0 },
        { temp: 40, pwm: 60 },
        { temp: 50, pwm: 120 },
        { temp: 60, pwm: 180 },
        { temp: 70, pwm: 255 },
    ]);
}

// ===== Settings =====
async function saveSettings() {
    const config = {
        update_interval: parseInt(document.getElementById('setting-update-interval').value),
        enable_alerts: document.getElementById('setting-enable-alerts').checked,
        alert_temp_cpu: parseFloat(document.getElementById('setting-alert-cpu').value),
        alert_temp_disk: parseFloat(document.getElementById('setting-alert-disk').value),
        enable_smartctl: document.getElementById('setting-enable-smartctl').checked,
        history_retention_days: parseInt(document.getElementById('setting-history-retention').value),
        alert_enabled: document.getElementById('setting-alert-enabled').checked,
        alert_cooldown_minutes: parseInt(document.getElementById('setting-alert-cooldown').value),
        smtp_host: document.getElementById('setting-smtp-host').value,
        smtp_port: parseInt(document.getElementById('setting-smtp-port').value),
        smtp_user: document.getElementById('setting-smtp-user').value,
        smtp_password: document.getElementById('setting-smtp-password').value,
        smtp_from: document.getElementById('setting-smtp-from').value,
        smtp_to: document.getElementById('setting-smtp-to').value,
        smtp_use_tls: document.getElementById('setting-smtp-tls').checked,
    };

    try {
        await API.updateConfig(config);
        showToast('设置已保存', 'success');
    } catch (e) {
        showToast(`保存失败: ${e.message}`, 'error');
    }
}

async function exportConfig() {
    try {
        const cfg = await API.getConfig();
        const blob = new Blob([JSON.stringify(cfg, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'fnos-fan-config.json';
        a.click();
        URL.revokeObjectURL(url);
        showToast('配置已导出', 'success');
    } catch (e) {
        showToast(`导出失败: ${e.message}`, 'error');
    }
}

// ===== Charts Refresh =====
async function refreshCharts() {
    try {
        const history = await API.getHistory(null, 60);
        Charts.updateTempChart(history);
        Charts.updateRpmChart(history);
    } catch (e) {
        // Silent
    }
}

// ===== History Page =====
let historyTempChart = null;
let historyFanChart = null;

async function loadHistory() {
    const days = document.getElementById('history-days')?.value || '30';
    const sensor = document.getElementById('history-sensor')?.value || '';

    try {
        // Load temperature history
        const tempRes = await fetch(`/api/history/temperatures?days=${days}&sensor_name=${encodeURIComponent(sensor)}&limit=2000`);
        const tempData = await tempRes.json();

        // Load fan history
        const fanRes = await fetch(`/api/history/fans?days=${days}&limit=2000`);
        const fanData = await fanRes.json();

        // Load summary
        const summaryRes = await fetch('/api/history/summary?days=1');
        const summaryData = await summaryRes.json();

        renderHistoryCharts(tempData.data, fanData.data);
        renderSummary(summaryData.summary);

        // Populate sensor dropdown for history page
        populateHistorySensors(tempData.data);
    } catch (e) {
        console.error('Failed to load history:', e);
    }
}

function populateHistorySensors(data) {
    const selector = document.getElementById('history-sensor');
    if (!selector || selector.options.length > 2) return;
    const sensors = new Set();
    data.forEach(d => sensors.add(d.sensor));
    sensors.forEach(s => {
        const opt = document.createElement('option');
        opt.value = s;
        opt.textContent = s;
        selector.appendChild(opt);
    });
}

function renderHistoryCharts(tempData, fanData) {
    // Temperature history chart
    const tempCtx = document.getElementById('history-temp-chart')?.getContext('2d');
    if (tempCtx) {
        if (historyTempChart) historyTempChart.destroy();

        // Group by sensor
        const series = {};
        tempData.forEach(d => {
            if (!series[d.sensor]) series[d.sensor] = [];
            series[d.sensor].push({ x: d.timestamp * 1000, y: d.value });
        });

        const datasets = [];
        const colors = ['#ff6b6b', '#51cf66', '#339af0', '#fcc419', '#cc5de8', '#20c997', '#ff922b', '#748ffc'];
        let ci = 0;
        for (const [name, points] of Object.entries(series)) {
            points.sort((a, b) => a.x - b.x);
            datasets.push({
                label: name, data: points,
                borderColor: colors[ci % colors.length],
                backgroundColor: 'transparent',
                borderWidth: 1.5, pointRadius: 0, tension: 0.3,
            });
            ci++;
        }

        historyTempChart = new Chart(tempCtx, {
            type: 'line',
            data: { datasets },
            options: {
                responsive: true, maintainAspectRatio: false,
                scales: {
                    x: { type: 'time', time: { tooltipFormat: 'MM-dd HH:mm' }, grid: { color: '#333' } },
                    y: { title: { text: '°C', display: true }, grid: { color: '#333' } },
                },
                plugins: { legend: { labels: { color: '#aaa', usePointStyle: true } } },
            },
        });
    }

    // Fan history chart
    const fanCtx = document.getElementById('history-fan-chart')?.getContext('2d');
    if (fanCtx) {
        if (historyFanChart) historyFanChart.destroy();

        const series = {};
        fanData.forEach(d => {
            const key = d.fan + '_pwm';
            if (!series[key]) series[key] = [];
            series[key].push({ x: d.timestamp * 1000, y: d.pwm });
        });

        const datasets = [];
        const colors = ['#339af0', '#51cf66', '#fcc419', '#ff6b6b'];
        let ci = 0;
        for (const [name, points] of Object.entries(series)) {
            points.sort((a, b) => a.x - b.x);
            datasets.push({
                label: name, data: points,
                borderColor: colors[ci % colors.length],
                backgroundColor: 'transparent',
                borderWidth: 1.5, pointRadius: 0, tension: 0.3,
            });
            ci++;
        }

        historyFanChart = new Chart(fanCtx, {
            type: 'line',
            data: { datasets },
            options: {
                responsive: true, maintainAspectRatio: false,
                scales: {
                    x: { type: 'time', time: { tooltipFormat: 'MM-dd HH:mm' }, grid: { color: '#333' } },
                    y: { title: { text: 'PWM (0-255)', display: true }, grid: { color: '#333' } },
                },
                plugins: { legend: { labels: { color: '#aaa', usePointStyle: true } } },
            },
        });
    }
}

function renderSummary(summary) {
    const container = document.getElementById('history-summary');
    if (!container) return;
    if (!summary || Object.keys(summary).length === 0) {
        container.innerHTML = '<span class="text-muted">暂无历史数据</span>';
        return;
    }
    let html = '<div style="display:flex;flex-wrap:wrap;gap:16px">';
    for (const [name, stats] of Object.entries(summary)) {
        html += `
            <div style="background:var(--bg-input);padding:12px 16px;border-radius:8px;min-width:180px">
                <div style="font-size:11px;color:var(--text-muted);margin-bottom:4px">${name}</div>
                <div style="display:flex;gap:12px;font-size:13px">
                    <span>低 ${stats.min}°C</span>
                    <span>均 ${stats.avg}°C</span>
                    <span>高 ${stats.max}°C</span>
                </div>
            </div>`;
    }
    html += '</div>';
    container.innerHTML = html;
}

// ===== Alert Test =====
async function testAlertEmail() {
    try {
        const res = await fetch('/api/alert/test', { method: 'POST' });
        const data = await res.json();
        showToast(data.message, data.success ? 'success' : 'error');
    } catch (e) {
        showToast(`测试失败: ${e.message}`, 'error');
    }
}

// ===== Toast =====
function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.animation = 'slideIn 0.3s ease reverse';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

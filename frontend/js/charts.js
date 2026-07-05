/**
 * Chart rendering module using Chart.js
 */

const Charts = {
    tempChart: null,
    rpmChart: null,
    curveChart: null,
    maxDataPoints: 60,

    // Color palette for sensors
    colors: [
        '#4f8cf7', '#22d3ee', '#4ade80', '#facc15',
        '#fb923c', '#f87171', '#a78bfa', '#ec4899',
        '#14b8a6', '#e879f9',
    ],

    initCharts() {
        const commonOpts = {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            animation: { duration: 0 },
            scales: {
                x: {
                    type: 'linear',
                    ticks: {
                        callback: (val) => {
                            const d = new Date(val * 1000);
                            return d.toLocaleTimeString('zh-CN', { hour12: false });
                        },
                        color: '#8b8fa3',
                        maxTicksLimit: 6,
                    },
                    grid: { color: 'rgba(46, 51, 68, 0.5)' },
                },
                y: {
                    ticks: { color: '#8b8fa3' },
                    grid: { color: 'rgba(46, 51, 68, 0.5)' },
                },
            },
            plugins: {
                legend: {
                    display: true,
                    position: 'top',
                    labels: { color: '#8b8fa3', font: { size: 11 }, boxWidth: 12 },
                },
                tooltip: {
                    backgroundColor: 'rgba(30, 34, 48, 0.95)',
                    titleColor: '#e4e6ed',
                    bodyColor: '#e4e6ed',
                    borderColor: '#2e3344',
                    borderWidth: 1,
                },
                zoom: {
                    pan: { enabled: true, mode: 'x' },
                    zoom: {
                        wheel: { enabled: true },
                        pinch: { enabled: true },
                        drag: { enabled: true, backgroundColor: 'rgba(79,140,247,0.15)', borderColor: '#4f8cf7' },
                        mode: 'x',
                    },
                    limits: { x: { minRange: 60000 } },
                },
            },
        };

        // Temperature chart
        const tempCtx = document.getElementById('temp-chart');
        if (tempCtx) {
            this.tempChart = new Chart(tempCtx, {
                type: 'line',
                data: { datasets: [] },
                options: {
                    ...commonOpts,
                    scales: {
                        ...commonOpts.scales,
                        y: {
                            ...commonOpts.scales.y,
                            title: { display: true, text: '°C', color: '#8b8fa3' },
                            suggestedMin: 20,
                            suggestedMax: 80,
                        },
                    },
                },
            });
        }

        // RPM chart
        const rpmCtx = document.getElementById('rpm-chart');
        if (rpmCtx) {
            this.rpmChart = new Chart(rpmCtx, {
                type: 'line',
                data: { datasets: [] },
                options: {
                    ...commonOpts,
                    scales: {
                        ...commonOpts.scales,
                        y: {
                            ...commonOpts.scales.y,
                            title: { display: true, text: 'RPM', color: '#8b8fa3' },
                            suggestedMin: 0,
                            suggestedMax: 2000,
                        },
                    },
                },
            });
        }
    },

    updateTempChart(history) {
        if (!this.tempChart || !history || !history.system) return;

        const sysData = history.system;
        if (sysData.length === 0) return;

        // Collect all sensor names
        const sensorNames = new Set();
        sysData.forEach(entry => {
            if (entry.temps) {
                Object.keys(entry.temps).forEach(k => sensorNames.add(k));
            }
        });

        const sensors = Array.from(sensorNames).slice(0, 8); // Max 8 lines
        const colors = this.colors;

        // Update legend
        const legendEl = document.getElementById('temp-legend');
        if (legendEl) {
            legendEl.innerHTML = sensors.map((s, i) =>
                `<span style="color:${colors[i % colors.length]}">●</span> ${this.shortName(s)}`
            ).join('&nbsp;&nbsp;');
        }

        this.tempChart.data.datasets = sensors.map((name, i) => ({
            label: this.shortName(name),
            data: sysData
                .filter(e => e.temps && e.temps[name] !== undefined)
                .map(e => ({ x: e.timestamp, y: e.temps[name] })),
            borderColor: colors[i % colors.length],
            backgroundColor: colors[i % colors.length] + '20',
            borderWidth: 2,
            pointRadius: 0,
            tension: 0.3,
            fill: i === 0,
        }));

        this.tempChart.update('none');
    },

    updateRpmChart(history) {
        if (!this.rpmChart || !history || !history.system) return;

        const sysData = history.system;
        if (sysData.length === 0) return;

        // Collect all RPM sensor names
        const rpmNames = new Set();
        sysData.forEach(entry => {
            if (entry.rpms) {
                Object.keys(entry.rpms).forEach(k => rpmNames.add(k));
            }
        });

        const sensors = Array.from(rpmNames).slice(0, 6);
        const colors = this.colors;

        // Update legend
        const legendEl = document.getElementById('rpm-legend');
        if (legendEl) {
            legendEl.innerHTML = sensors.map((s, i) =>
                `<span style="color:${colors[i % colors.length]}">●</span> ${this.shortName(s)}`
            ).join('&nbsp;&nbsp;');
        }

        this.rpmChart.data.datasets = sensors.map((name, i) => ({
            label: this.shortName(name),
            data: sysData
                .filter(e => e.rpms && e.rpms[name] !== undefined)
                .map(e => ({ x: e.timestamp, y: e.rpms[name] })),
            borderColor: colors[i % colors.length],
            backgroundColor: colors[i % colors.length] + '20',
            borderWidth: 2,
            pointRadius: 0,
            tension: 0.3,
            fill: false,
        }));

        this.rpmChart.update('none');
    },

    shortName(name) {
        // Shorten sensor names for display
        if (name.startsWith('disk:')) {
            return name.replace('disk:', '').replace('/dev/', '');
        }
        // Remove common prefixes
        return name.replace('temp', 'T').replace('input', '');
    },

    getTempClass(temp) {
        if (temp >= 80) return 'temp-critical';
        if (temp >= 65) return 'temp-hot';
        if (temp >= 50) return 'temp-warm';
        return 'temp-cool';
    },

    getTempColor(temp) {
        if (temp >= 80) return '#f87171';
        if (temp >= 65) return '#fb923c';
        if (temp >= 50) return '#facc15';
        return '#4ade80';
    },
};

/**
 * Fan Curve Editor - interactive canvas-based curve editor
 */
const CurveEditor = {
    canvas: null,
    ctx: null,
    points: [],
    draggingIndex: -1,
    hoverIndex: -1,
    selectedFan: null,
    maxTemp: 100,
    maxPwm: 255,

    init() {
        this.canvas = document.getElementById('curve-editor');
        if (!this.canvas) return;

        this.ctx = this.canvas.getContext('2d');
        this.setupEvents();
        this.draw();
    },

    setPoints(points) {
        this.points = points.map(p => ({ temp: p.temp, pwm: p.pwm }));
        this.draw();
        this.updateTable();
    },

    getPoints() {
        return this.points.map(p => ({ temp: Math.round(p.temp), pwm: Math.round(p.pwm) }));
    },

    setupEvents() {
        const canvas = this.canvas;

        canvas.addEventListener('mousedown', (e) => {
            const { x, y } = this.getMousePos(e);
            const idx = this.findNearbyPoint(x, y);
            if (idx !== -1) {
                this.draggingIndex = idx;
            }
        });

        canvas.addEventListener('mousemove', (e) => {
            const { x, y } = this.getMousePos(e);
            if (this.draggingIndex !== -1) {
                const temp = this.xToTemp(x);
                const pwm = this.yToPwm(y);
                this.points[this.draggingIndex].temp = Math.max(0, Math.min(this.maxTemp, temp));
                this.points[this.draggingIndex].pwm = Math.max(0, Math.min(this.maxPwm, pwm));
                this.draw();
                this.updateTable();
            } else {
                const idx = this.findNearbyPoint(x, y);
                this.hoverIndex = idx;
                canvas.style.cursor = idx !== -1 ? 'grab' : 'crosshair';
                this.draw();
            }
        });

        canvas.addEventListener('mouseup', () => {
            this.draggingIndex = -1;
        });

        canvas.addEventListener('mouseleave', () => {
            this.draggingIndex = -1;
            this.hoverIndex = -1;
            this.draw();
        });

        canvas.addEventListener('dblclick', (e) => {
            const { x, y } = this.getMousePos(e);
            const idx = this.findNearbyPoint(x, y);
            if (idx !== -1 && this.points.length > 2) {
                this.points.splice(idx, 1);
                this.points.sort((a, b) => a.temp - b.temp);
                this.draw();
                this.updateTable();
            }
        });

        canvas.addEventListener('contextmenu', (e) => {
            e.preventDefault();
            const { x, y } = this.getMousePos(e);
            const temp = Math.round(this.xToTemp(x));
            const pwm = Math.round(this.yToPwm(y));
            if (temp > 0 && temp < this.maxTemp) {
                this.points.push({ temp, pwm });
                this.points.sort((a, b) => a.temp - b.temp);
                this.draw();
                this.updateTable();
            }
        });
    },

    getMousePos(e) {
        const rect = this.canvas.getBoundingClientRect();
        const scaleX = this.canvas.width / rect.width;
        const scaleY = this.canvas.height / rect.height;
        return {
            x: (e.clientX - rect.left) * scaleX,
            y: (e.clientY - rect.top) * scaleY,
        };
    },

    // Canvas coordinate transformations
    // Drawing area: x from 60 to 580, y from 20 to 360
    tempToX(temp) { return 60 + (temp / this.maxTemp) * 520; },
    xToTemp(x) { return ((x - 60) / 520) * this.maxTemp; },
    pwmToY(pwm) { return 360 - (pwm / this.maxPwm) * 340; },
    yToPwm(y) { return ((360 - y) / 340) * this.maxPwm; },

    findNearbyPoint(x, y) {
        for (let i = 0; i < this.points.length; i++) {
            const px = this.tempToX(this.points[i].temp);
            const py = this.pwmToY(this.points[i].pwm);
            const dist = Math.sqrt((x - px) ** 2 + (y - py) ** 2);
            if (dist < 15) return i;
        }
        return -1;
    },

    draw() {
        const ctx = this.ctx;
        const w = this.canvas.width;
        const h = this.canvas.height;

        // Background
        ctx.fillStyle = '#0f1117';
        ctx.fillRect(0, 0, w, h);

        // Grid
        ctx.strokeStyle = 'rgba(46, 51, 68, 0.5)';
        ctx.lineWidth = 1;
        ctx.font = '11px sans-serif';
        ctx.fillStyle = '#5a5e70';

        // Vertical grid (temperature)
        for (let t = 0; t <= this.maxTemp; t += 10) {
            const x = this.tempToX(t);
            ctx.beginPath();
            ctx.moveTo(x, 20);
            ctx.lineTo(x, 360);
            ctx.stroke();
            ctx.fillText(t + '°C', x - 12, 380);
        }

        // Horizontal grid (PWM)
        for (let p = 0; p <= this.maxPwm; p += 51) {
            const y = this.pwmToY(p);
            ctx.beginPath();
            ctx.moveTo(60, y);
            ctx.lineTo(580, y);
            ctx.stroke();
            ctx.fillText(Math.round(p / 255 * 100) + '%', 10, y + 4);
        }

        // Axis labels
        ctx.fillStyle = '#8b8fa3';
        ctx.font = '12px sans-serif';
        ctx.fillText('温度 (°C)', w / 2 - 30, 398);
        ctx.save();
        ctx.translate(15, h / 2);
        ctx.rotate(-Math.PI / 2);
        ctx.fillText('PWM (%)', -20, 0);
        ctx.restore();

        // Draw curve
        if (this.points.length < 1) return;

        const sorted = [...this.points].sort((a, b) => a.temp - b.temp);

        // Fill area under curve
        ctx.beginPath();
        ctx.moveTo(this.tempToX(sorted[0].temp), 360);
        sorted.forEach(p => {
            ctx.lineTo(this.tempToX(p.temp), this.pwmToY(p.pwm));
        });
        ctx.lineTo(this.tempToX(sorted[sorted.length - 1].temp), 360);
        ctx.closePath();
        ctx.fillStyle = 'rgba(79, 140, 247, 0.1)';
        ctx.fill();

        // Draw curve line
        ctx.strokeStyle = '#4f8cf7';
        ctx.lineWidth = 2;
        ctx.beginPath();
        sorted.forEach((p, i) => {
            const x = this.tempToX(p.temp);
            const y = this.pwmToY(p.pwm);
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        });
        ctx.stroke();

        // Draw points
        sorted.forEach((p, i) => {
            const x = this.tempToX(p.temp);
            const y = this.pwmToY(p.pwm);
            const origIdx = this.points.indexOf(p);
            const isHover = origIdx === this.hoverIndex;
            const isDrag = origIdx === this.draggingIndex;

            ctx.beginPath();
            ctx.arc(x, y, isHover || isDrag ? 7 : 5, 0, Math.PI * 2);
            ctx.fillStyle = isHover || isDrag ? '#22d3ee' : '#4f8cf7';
            ctx.fill();
            ctx.strokeStyle = '#fff';
            ctx.lineWidth = 2;
            ctx.stroke();

            // Label
            ctx.fillStyle = '#e4e6ed';
            ctx.font = '10px sans-serif';
            ctx.fillText(`${Math.round(p.temp)}°/${Math.round(p.pwm / 255 * 100)}%`, x + 8, y - 8);
        });
    },

    updateTable() {
        const tbody = document.getElementById('curve-points-body');
        if (!tbody) return;

        const sorted = [...this.points].sort((a, b) => a.temp - b.temp);
        tbody.innerHTML = sorted.map((p, i) => `
            <tr>
                <td><input type="number" value="${Math.round(p.temp)}" min="0" max="100"
                    onchange="CurveEditor.updatePoint(${i}, 'temp', this.value)"></td>
                <td><input type="number" value="${Math.round(p.pwm)}" min="0" max="255"
                    onchange="CurveEditor.updatePoint(${i}, 'pwm', this.value)"></td>
                <td><button class="btn btn-sm btn-danger"
                    onclick="CurveEditor.removePoint(${i})">删除</button></td>
            </tr>
        `).join('');
    },

    updatePoint(index, field, value) {
        const sorted = [...this.points].sort((a, b) => a.temp - b.temp);
        if (sorted[index]) {
            sorted[index][field] = Math.max(0, parseFloat(value));
            this.points = sorted;
            this.draw();
            this.updateTable();
        }
    },

    removePoint(index) {
        const sorted = [...this.points].sort((a, b) => a.temp - b.temp);
        if (sorted.length > 2) {
            sorted.splice(index, 1);
            this.points = sorted;
            this.draw();
            this.updateTable();
        } else {
            showToast('至少保留两个节点', 'error');
        }
    },
};

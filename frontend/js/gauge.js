/**
 * Car-style dashboard gauge — Canvas-based semicircular gauge.
 * Usage: new Gauge(canvasId, options)
 */

class Gauge {
    constructor(canvasId, options = {}) {
        this.canvas = document.getElementById(canvasId);
        if (!this.canvas) return;
        this.ctx = this.canvas.getContext('2d');
        this.value = options.value || 0;
        this.min = options.min || 0;
        this.max = options.max || 100;
        this.unit = options.unit || '°C';
        this.title = options.title || '';
        this.warn = options.warn || 60;   // yellow starts
        this.crit = options.crit || 80;    // red starts
        this.resolution = window.devicePixelRatio || 1;
    }

    setValue(val) {
        const prev = this.value;
        this.value = Math.max(this.min, Math.min(this.max, val));
        // Smooth animate
        if (Math.abs(this.value - prev) > 1) {
            this._target = this.value;
            this.value = prev;
            this._animating = true;
        }
    }

    draw() {
        if (!this.canvas) return;

        // Handle animation
        if (this._animating && Math.abs(this.value - this._target) > 0.3) {
            this.value += (this._target - this.value) * 0.3;
            if (Math.abs(this._target - this.value) < 0.5) {
                this.value = this._target;
                this._animating = false;
            }
        }

        const w = this.canvas.offsetWidth * this.resolution;
        const h = this.canvas.offsetHeight * this.resolution;
        this.canvas.width = w;
        this.canvas.height = h;

        const ctx = this.ctx;
        const cx = w / 2;
        const cy = h * 0.78;
        const radius = Math.min(w, h * 1.3) * 0.52;

        ctx.clearRect(0, 0, w, h);

        // Angle range: 225° to 315° (bottom-left to bottom-right, 270° span)
        const startAngle = -225 * Math.PI / 180;
        const endAngle = 45 * Math.PI / 180;
        const range = endAngle - startAngle;

        // Background arc
        ctx.beginPath();
        ctx.arc(cx, cy, radius, startAngle, endAngle);
        ctx.strokeStyle = '#2a2a3a';
        ctx.lineWidth = radius * 0.18;
        ctx.stroke();

        // Color zones
        const colorZones = [
            { from: this.min, to: this.warn, color: '#22c55e' },
            { from: this.warn, to: this.crit, color: '#eab308' },
            { from: this.crit, to: this.max, color: '#ef4444' },
        ];

        const zoneWidth = radius * 0.18;
        colorZones.forEach(zone => {
            const zStart = startAngle + (zone.from - this.min) / (this.max - this.min) * range;
            const zEnd = startAngle + (zone.to - this.min) / (this.max - this.min) * range;
            ctx.beginPath();
            ctx.arc(cx, cy, radius, zStart, zEnd);
            ctx.strokeStyle = zone.color;
            ctx.lineWidth = zoneWidth;
            ctx.stroke();
        });

        // Tick marks
        const tickCount = 8;
        for (let i = 0; i <= tickCount; i++) {
            const val = this.min + i * (this.max - this.min) / tickCount;
            const angle = startAngle + i * range / tickCount;
            const innerR = radius * 0.82;
            const outerR = radius * 0.92;
            ctx.beginPath();
            ctx.moveTo(cx + innerR * Math.cos(angle), cy + innerR * Math.sin(angle));
            ctx.lineTo(cx + outerR * Math.cos(angle), cy + outerR * Math.sin(angle));
            ctx.strokeStyle = i === 0 || i === tickCount ? '#888' : '#555';
            ctx.lineWidth = 1.5;
            ctx.stroke();

            // Tick label
            const labelR = radius * 0.65;
            ctx.fillStyle = '#888';
            ctx.font = `${Math.round(radius * 0.12)}px monospace`;
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText(Math.round(val), cx + labelR * Math.cos(angle), cy + labelR * Math.sin(angle));
        }

        // Needle
        const valueRatio = (this.value - this.min) / (this.max - this.min);
        const needleAngle = startAngle + valueRatio * range;

        const needleLen = radius * 0.78;
        const needleTip = {
            x: cx + needleLen * Math.cos(needleAngle),
            y: cy + needleLen * Math.sin(needleAngle),
        };

        // Needle shadow
        ctx.beginPath();
        ctx.moveTo(cx, cy);
        ctx.lineTo(needleTip.x + 2, needleTip.y + 2);
        ctx.lineWidth = 4;
        ctx.strokeStyle = 'rgba(0,0,0,0.3)';
        ctx.stroke();

        // Needle body
        const needleColor = this.value >= this.crit ? '#ef4444' :
                           this.value >= this.warn ? '#eab308' : '#ef4444';
        ctx.beginPath();
        ctx.moveTo(cx, cy);
        ctx.lineTo(needleTip.x, needleTip.y);
        ctx.strokeStyle = needleColor;
        ctx.lineWidth = 3;
        ctx.stroke();

        // Needle base circle
        ctx.beginPath();
        ctx.arc(cx, cy, radius * 0.1, 0, Math.PI * 2);
        ctx.fillStyle = '#333';
        ctx.fill();
        ctx.strokeStyle = '#555';
        ctx.lineWidth = 2;
        ctx.stroke();

        // Digital value in center
        ctx.fillStyle = '#fff';
        ctx.font = `bold ${Math.round(radius * 0.22)}px monospace`;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'bottom';
        const valueY = cy - radius * 0.1;
        ctx.fillText(this.value.toFixed(1), cx, valueY);

        // Unit
        ctx.fillStyle = '#aaa';
        ctx.font = `${Math.round(radius * 0.1)}px sans-serif`;
        ctx.textBaseline = 'top';
        ctx.fillText(this.unit, cx, valueY + 4);

        // Title
        ctx.fillStyle = '#999';
        ctx.font = `${Math.round(radius * 0.09)}px sans-serif`;
        ctx.fillText(this.title, cx, cy + radius * 0.28);
    }
}

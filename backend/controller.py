"""
Temperature curve controller and fan control manager.
Implements the PWM mapping curve engine with hysteresis,
weighted sensor aggregation, and the main control loop.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional
from collections import deque

from config import AppConfig, FanConfig, FanCurvePoint
from sensors import SensorScanner
from history import init_db, write_temperature, write_fan_state, cleanup_old_records
from notifier import AlertNotifier

logger = logging.getLogger("fnos-fan.controller")


class CurveInterpolator:
    """
    Interpolates PWM values from a temperature curve.
    Uses linear interpolation between curve points with clamping.
    """

    def __init__(self, curve: list[FanCurvePoint]):
        self.points = sorted(curve, key=lambda p: p.temp)

    def interpolate(self, temperature: float) -> int:
        """Get PWM value for a given temperature."""
        if not self.points:
            return 128  # Safe default: 50% speed

        # Below the first point
        if temperature <= self.points[0].temp:
            return self.points[0].pwm

        # Above the last point
        if temperature >= self.points[-1].temp:
            return self.points[-1].pwm

        # Find the two surrounding points
        for i in range(len(self.points) - 1):
            p1 = self.points[i]
            p2 = self.points[i + 1]
            if p1.temp <= temperature <= p2.temp:
                # Linear interpolation
                if p2.temp == p1.temp:
                    return p1.pwm
                ratio = (temperature - p1.temp) / (p2.temp - p1.temp)
                return int(p1.pwm + ratio * (p2.pwm - p1.pwm))

        return self.points[-1].pwm


@dataclass
class FanRuntimeState:
    """Runtime state for a single fan."""
    config: FanConfig
    interpolator: Optional[CurveInterpolator] = None
    last_temp: float = 0.0
    last_pwm: int = 0
    target_pwm: int = 0
    control_enabled: bool = True
    manual_mode_set: bool = False
    pwm_history: deque = field(default_factory=lambda: deque(maxlen=300))
    rpm_history: deque = field(default_factory=lambda: deque(maxlen=300))
    temp_history: deque = field(default_factory=lambda: deque(maxlen=300))

    def update_interpolator(self):
        """Rebuild the curve interpolator from config."""
        self.interpolator = CurveInterpolator(self.config.curve)


class FanController:
    """
    Main fan controller. Manages the control loop, sensor reading,
    curve interpolation, and PWM output.
    """

    def __init__(self, config: AppConfig, scanner: SensorScanner):
        self.config = config
        self.scanner = scanner
        self.fan_states: list[FanRuntimeState] = []
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._update_callback = None

        # System-wide temperature history
        self.sys_temp_history: deque = deque(maxlen=config.data_history_length)
        self.last_update_time: float = 0.0

        # Persistent history
        init_db()
        self._cleanup_task: Optional[asyncio.Task] = None

        # Alert notifier
        self._notifier = AlertNotifier(config.model_dump())

        self._init_fan_states()

    def _init_fan_states(self):
        """Initialize runtime state for all configured fans."""
        self.fan_states.clear()
        for fan_cfg in self.config.fans:
            if not fan_cfg.enabled:
                continue
            state = FanRuntimeState(config=fan_cfg)
            state.update_interpolator()
            state.control_enabled = fan_cfg.mode != "auto"
            self.fan_states.append(state)
            logger.info(
                f"Initialized fan '{fan_cfg.name}' "
                f"(mode={fan_cfg.mode}, source={fan_cfg.sensor_source})"
            )

    def set_update_callback(self, callback):
        """Set a callback called after each control loop iteration."""
        self._update_callback = callback

    def reload_config(self, config: AppConfig):
        """Reload configuration and reinitialize fan states."""
        self.config = config
        self.sys_temp_history = deque(maxlen=config.data_history_length)
        self._init_fan_states()
        self._notifier.reload_config(config.model_dump())

    async def start(self):
        """Start the control loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._control_loop())
        # Run initial cleanup and schedule periodic cleanup
        self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
        logger.info("Fan control loop started")

    async def stop(self):
        """Stop the control loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
        # Restore fans to automatic mode
        for state in self.fan_states:
            self.scanner.set_fan_mode(
                state.config.hwmon_path,
                state.config.pwm_channel,
                2,  # 2 = automatic
            )
        logger.info("Fan control loop stopped, fans restored to auto mode")

    async def _periodic_cleanup(self):
        """Periodically clean up old history records."""
        await asyncio.sleep(10)  # Wait for system to settle
        while self._running:
            try:
                cleanup_old_records(self.config.history_retention_days)
            except Exception as e:
                logger.error(f"History cleanup error: {e}")
            await asyncio.sleep(3600)  # Run every hour

    def _get_reference_temp(self, state: FanRuntimeState, all_temps: dict[str, float]) -> float:
        """
        Get the reference temperature for a fan based on its sensor_source config.
        Supports: cpu, max, avg, specific:<name>
        """
        source = state.config.sensor_source

        if source.startswith("specific:"):
            name = source.split(":", 1)[1]
            return all_temps.get(name, 0.0)

        if source == "cpu":
            # Find CPU temperature - common hwmon names for CPU
            cpu_names = ["coretemp", "k10temp", "cpu_thermal", "soc_thermal",
                        "zenpower", "amdgpu", "nct"]
            cpu_temps = []
            for dev in self.scanner.hwmon_devices:
                if any(cn in dev.name.lower() for cn in cpu_names):
                    for sensor in dev.temperatures:
                        val = self.scanner.read_temperature(sensor)
                        if val > 0:
                            cpu_temps.append(val)
            if cpu_temps:
                return max(cpu_temps)  # Use hottest CPU core
            # Fallback: use the first available temperature
            if all_temps:
                return list(all_temps.values())[0]
            return 0.0

        if source == "max":
            vals = [v for v in all_temps.values() if v > 0]
            return max(vals) if vals else 0.0

        if source == "avg":
            vals = [v for v in all_temps.values() if v > 0]
            return sum(vals) / len(vals) if vals else 0.0

        # Default: use max
        vals = [v for v in all_temps.values() if v > 0]
        return max(vals) if vals else 0.0

    def _apply_hysteresis(self, state: FanRuntimeState, current_temp: float, target_pwm: int) -> int:
        """
        Apply hysteresis to prevent PWM oscillation.
        Only change PWM if temperature moved more than hysteresis degrees
        or the change is large enough.
        """
        hyst = state.config.hysteresis
        last_pwm = state.last_pwm

        # If temperature barely changed and PWM difference is small, keep current
        if abs(current_temp - state.last_temp) < hyst:
            # Only allow increasing PWM (safer)
            if target_pwm > last_pwm + 5:
                return target_pwm
            return last_pwm

        return target_pwm

    async def _control_loop(self):
        """Main control loop - runs at configured interval."""
        logger.info(f"Control loop running at {self.config.update_interval}s interval")

        while self._running:
            try:
                await self._run_single_iteration()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Control loop error: {e}", exc_info=True)

            await asyncio.sleep(self.config.update_interval)

    async def _run_single_iteration(self):
        """Execute one control loop iteration."""
        # Read all temperatures
        all_temps = self.scanner.get_all_temperatures()
        all_rpms = self.scanner.get_all_fan_rpms()
        all_pwms = self.scanner.get_all_pwms()

        timestamp = time.time()
        self.last_update_time = timestamp

        # Persist temperatures to SQLite
        for name, val in all_temps.items():
            if val > 0:
                try:
                    write_temperature(name, val, timestamp)
                except Exception:
                    pass

        # Process each controlled fan
        for state in self.fan_states:
            if not state.control_enabled:
                continue

            ref_temp = self._get_reference_temp(state, all_temps)
            state.last_temp = ref_temp
            state.temp_history.append((timestamp, ref_temp))

            if state.config.mode == "manual":
                target_pwm = state.config.manual_pwm
            elif state.config.mode == "auto":
                # Skip control, just read current values
                continue
            elif state.config.mode == "curve" and state.interpolator:
                raw_pwm = state.interpolator.interpolate(ref_temp)
                # Apply minimum PWM
                target_pwm = max(raw_pwm, state.config.min_pwm)
                # Apply hysteresis
                target_pwm = self._apply_hysteresis(state, ref_temp, target_pwm)
            else:
                target_pwm = 128  # Safe default

            state.target_pwm = target_pwm

            # Write PWM to hardware
            if state.config.mode == "curve" or state.config.mode == "manual":
                # Ensure manual mode is set
                if not state.manual_mode_set:
                    if self.scanner.set_fan_mode(
                        state.config.hwmon_path,
                        state.config.pwm_channel,
                        1,  # 1 = manual PWM control
                    ):
                        state.manual_mode_set = True

                self.scanner.write_pwm(
                    state.config.hwmon_path,
                    state.config.pwm_channel,
                    target_pwm,
                )

            state.last_pwm = target_pwm
            state.pwm_history.append((timestamp, target_pwm))

            # Read current RPM
            current_rpm = 0
            for dev in self.scanner.hwmon_devices:
                for sensor in dev.fan_rpms:
                    if (sensor.hwmon_path == state.config.hwmon_path and
                        sensor.channel == state.config.rpm_channel):
                        current_rpm = self.scanner.read_fan_rpm(sensor)
                        state.rpm_history.append((timestamp, current_rpm))
                        break

            # Persist fan state to SQLite
            try:
                write_fan_state(state.config.name, target_pwm, current_rpm, timestamp)
            except Exception:
                pass

            logger.debug(
                f"Fan '{state.config.name}': temp={ref_temp:.1f}C, "
                f"pwm={target_pwm}/255 ({target_pwm*100//255}%)"
            )

        # Update system temp history
        sys_temp = max((v for v in all_temps.values() if v > 0), default=0.0)
        self.sys_temp_history.append((timestamp, {
            "timestamp": timestamp,
            "temps": dict(all_temps),
            "rpms": dict(all_rpms),
            "pwms": dict(all_pwms),
        }))

        # Check alerts and send emails
        self._check_and_send_alerts()

        # Call update callback if set
        if self._update_callback:
            try:
                await self._update_callback(self.get_status())
            except Exception as e:
                logger.error(f"Update callback error: {e}")

    def _check_and_send_alerts(self):
        """Check temperature thresholds and send email alerts."""
        if not self.config.enable_alerts:
            return

        all_temps = self.scanner.get_all_temperatures()
        for name, temp in all_temps.items():
            if temp <= 0:
                continue
            threshold = self.config.alert_temp_disk if "硬盘" in name else self.config.alert_temp_cpu
            if temp > threshold:
                self._notifier.send_alert(name, temp, threshold)

    def get_status(self) -> dict:
        """Get current status of all fans and sensors."""
        all_temps = self.scanner.get_all_temperatures()
        all_rpms = self.scanner.get_all_fan_rpms()
        all_pwms = self.scanner.get_all_pwms()

        fan_statuses = []
        for state in self.fan_states:
            fan_statuses.append({
                "name": state.config.name,
                "mode": state.config.mode,
                "enabled": state.control_enabled,
                "hwmon_path": state.config.hwmon_path,
                "pwm_channel": state.config.pwm_channel,
                "current_pwm": state.last_pwm,
                "target_pwm": state.target_pwm,
                "current_rpm": state.rpm_history[-1][1] if state.rpm_history else 0,
                "reference_temp": state.last_temp,
                "sensor_source": state.config.sensor_source,
                "pwm_percent": round(state.last_pwm * 100 / 255, 1),
                "curve": [
                    {"temp": p.temp, "pwm": p.pwm} for p in state.config.curve
                ],
                "history_length": len(state.pwm_history),
            })

        return {
            "timestamp": time.time(),
            "update_interval": self.config.update_interval,
            "temperatures": all_temps,
            "fan_rpms": all_rpms,
            "pwm_values": all_pwms,
            "fans": fan_statuses,
            "sensors": self.scanner.to_dict(),
            "alerts": self._check_alerts(all_temps),
        }

    def _check_alerts(self, temps: dict[str, float]) -> list[dict]:
        """Check for temperature alerts."""
        alerts = []
        if not self.config.enable_alerts:
            return alerts

        for name, temp in temps.items():
            if name.startswith("disk:"):
                if temp > self.config.alert_temp_disk:
                    alerts.append({
                        "level": "warning",
                        "sensor": name,
                        "temperature": temp,
                        "threshold": self.config.alert_temp_disk,
                        "message": f"{name} temperature {temp:.1f}C exceeds threshold {self.config.alert_temp_disk}C",
                    })
            else:
                if temp > self.config.alert_temp_cpu:
                    alerts.append({
                        "level": "warning",
                        "sensor": name,
                        "temperature": temp,
                        "threshold": self.config.alert_temp_cpu,
                        "message": f"{name} temperature {temp:.1f}C exceeds threshold {self.config.alert_temp_cpu}C",
                    })

        return alerts

    def set_fan_mode(self, fan_name: str, mode: str) -> bool:
        """Change a fan's control mode at runtime."""
        for state in self.fan_states:
            if state.config.name == fan_name:
                state.config.mode = mode
                state.manual_mode_set = False
                if mode == "auto":
                    self.scanner.set_fan_mode(
                        state.config.hwmon_path,
                        state.config.pwm_channel,
                        2,
                    )
                logger.info(f"Fan '{fan_name}' mode changed to '{mode}'")
                return True
        return False

    def set_fan_manual_pwm(self, fan_name: str, pwm: int) -> bool:
        """Set manual PWM for a fan."""
        for state in self.fan_states:
            if state.config.name == fan_name:
                state.config.manual_pwm = max(0, min(255, pwm))
                if state.config.mode != "manual":
                    state.config.mode = "manual"
                    state.manual_mode_set = False
                logger.info(f"Fan '{fan_name}' manual PWM set to {pwm}")
                return True
        return False

    def update_fan_curve(self, fan_name: str, curve: list[dict]) -> bool:
        """Update a fan's temperature curve at runtime."""
        for state in self.fan_states:
            if state.config.name == fan_name:
                new_curve = [FanCurvePoint(**p) for p in curve]
                state.config.curve = new_curve
                state.update_interpolator()
                logger.info(f"Fan '{fan_name}' curve updated with {len(new_curve)} points")
                return True
        return False

    def get_history(self, fan_name: Optional[str] = None, limit: int = 100) -> dict:
        """Get historical data for charts."""
        result = {"system": [], "fans": {}}

        # System history
        sys_data = list(self.sys_temp_history)
        if limit and len(sys_data) > limit:
            sys_data = sys_data[-limit:]
        result["system"] = [
            {"timestamp": entry[0], **entry[1]} for entry in sys_data
        ]

        # Per-fan history
        for state in self.fan_states:
            if fan_name and state.config.name != fan_name:
                continue
            result["fans"][state.config.name] = {
                "pwm": [
                    {"t": t, "v": v} for t, v in state.pwm_history
                ],
                "rpm": [
                    {"t": t, "v": v} for t, v in state.rpm_history
                ],
                "temp": [
                    {"t": t, "v": v} for t, v in state.temp_history
                ],
            }

        return result

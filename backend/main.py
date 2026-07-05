"""
FNOS 风扇控制器 - FastAPI 应用。
提供 REST API 和 WebSocket，实现风扇控制和温度监控。
"""

import asyncio
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import AppConfig, FanConfig, FanCurvePoint, load_config, save_config
from sensors import SensorScanner
from controller import FanController
from history import read_temperature_history, read_fan_history, get_temp_summary

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("fnos-fan")

# 全局实例
app_config: AppConfig = None
scanner: SensorScanner = None
controller: FanController = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动和关闭生命周期。"""
    global app_config, scanner, controller

    logger.info("Starting FNOS Fan Controller...")

    # Load configuration
    config_path = os.environ.get("FNOS_FAN_CONFIG", None)
    app_config = load_config(config_path)
    logging.getLogger().setLevel(getattr(logging, app_config.log_level, logging.INFO))

    # Initialize sensor scanner
    scanner = SensorScanner(
        smartctl_path=app_config.smartctl_path,
        enable_smartctl=app_config.enable_smartctl,
    )

    # 扫描硬件
    logger.info("Scanning hardware sensors...")
    scanner.scan_hwmon()
    await scanner.scan_disks()

    # 如果未配置风扇且启用了自动检测，则自动配置
    if app_config.auto_detect and not app_config.fans:
        logger.info("Auto-detecting fans...")
        _auto_configure_fans(app_config, scanner)

    # Initialize controller
    controller = FanController(app_config, scanner)
    await controller.start()

    logger.info("FNOS Fan Controller started successfully")
    yield

    # Shutdown
    logger.info("Shutting down FNOS Fan Controller...")
    if controller:
        await controller.stop()
    logger.info("Goodbye!")


def _auto_configure_fans(config: AppConfig, scn: SensorScanner):
    """Auto-detect and configure fans based on found PWM controls."""
    for dev in scn.hwmon_devices:
        for pwm in dev.fan_pwms:
            # 跳过无对应转速传感器的 PWM（可能不是风扇）
            has_rpm = any(
                rpm.hwmon_path == dev.hwmon_path and rpm.channel == pwm.channel
                for rpm in dev.fan_rpms
            )
            if not has_rpm:
                continue

            fan = FanConfig(
                name=f"{dev.name}_fan{pwm.channel}",
                hwmon_path=dev.hwmon_path,
                pwm_channel=pwm.channel,
                rpm_channel=pwm.channel,
                enabled=True,
                mode="curve",
                sensor_source="cpu",
            )
            config.fans.append(fan)
            logger.info(f"Auto-configured fan: {fan.name}")

    if not config.fans:
        logger.warning("No controllable fans detected!")


# 创建 FastAPI 应用
app = FastAPI(
    title="FNOS Fan Controller",
    description="Fan control and temperature monitoring for FNOS (飞牛OS)",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- WebSocket connection manager ---

class ConnectionManager:
    """管理实时更新的 WebSocket 连接。"""

    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)
        logger.info(f"WebSocket connected, total: {len(self.active)}")

    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)
        logger.info(f"WebSocket disconnected, total: {len(self.active)}")

    async def broadcast(self, message: dict):
        """向所有连接的客户端广播消息。"""
        if not self.active:
            return
        data = json.dumps(message, ensure_ascii=False)
        dead = []
        for ws in self.active:
            try:
                await ws.send_text(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


ws_manager = ConnectionManager()


async def ws_update_callback(status: dict):
    """控制器通过 WebSocket 推送更新的回调。"""
    await ws_manager.broadcast({"type": "status", "data": status})


# 在 lifespan 中初始化控制器后设置回调


# --- API 的 Pydantic 模型 ---

class FanModeRequest(BaseModel):
    mode: str  # "curve" | "manual" | "auto"


class FanPwmRequest(BaseModel):
    pwm: int  # 0-255


class FanCurveUpdate(BaseModel):
    curve: list[dict]  # [{"temp": 30, "pwm": 0}, ...]


class ConfigUpdate(BaseModel):
    update_interval: Optional[int] = None
    enable_alerts: Optional[bool] = None
    alert_temp_cpu: Optional[float] = None
    alert_temp_disk: Optional[float] = None
    enable_smartctl: Optional[bool] = None
    history_retention_days: Optional[int] = None
    alert_enabled: Optional[bool] = None
    alert_cooldown_minutes: Optional[int] = None
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_from: Optional[str] = None
    smtp_to: Optional[str] = None
    smtp_use_tls: Optional[bool] = None


class RescanRequest(BaseModel):
    rescan_disks: bool = True


# --- API 路由 ---

@app.get("/api/status")
async def get_status():
    """获取当前系统状态：所有温度、风扇转速、PWM 值。"""
    if controller is None:
        raise HTTPException(503, "Controller not initialized")
    return controller.get_status()


@app.get("/api/sensors")
async def get_sensors():
    """获取所有检测到的传感器。"""
    if scanner is None:
        raise HTTPException(503, "Scanner not initialized")
    return scanner.to_dict()


@app.post("/api/sensors/rescan")
async def rescan_sensors(req: RescanRequest):
    """重新扫描硬件传感器。"""
    global scanner
    if scanner is None:
        raise HTTPException(503, "Scanner not initialized")

    scanner.scan_hwmon()
    if req.rescan_disks:
        await scanner.scan_disks()

    # 如有需要重新初始化控制器
    if controller:
        controller._init_fan_states()

    return {
        "message": "Rescan complete",
        "sensors": scanner.to_dict(),
    }


@app.get("/api/fans")
async def get_fans():
    """获取所有风扇配置和当前状态。"""
    if controller is None:
        raise HTTPException(503, "Controller not initialized")
    return {"fans": controller.get_status()["fans"]}


@app.put("/api/fans/{fan_name}/mode")
async def set_fan_mode(fan_name: str, req: FanModeRequest):
    """设置风扇控制模式。"""
    if controller is None:
        raise HTTPException(503, "Controller not initialized")
    if not controller.set_fan_mode(fan_name, req.mode):
        raise HTTPException(404, f"Fan '{fan_name}' not found")
    return {"message": f"Fan '{fan_name}' mode set to '{req.mode}'"}


@app.put("/api/fans/{fan_name}/pwm")
async def set_fan_pwm(fan_name: str, req: FanPwmRequest):
    """设置风扇手动 PWM（同时将模式设为手动）。"""
    if controller is None:
        raise HTTPException(503, "Controller not initialized")
    if not controller.set_fan_manual_pwm(fan_name, req.pwm):
        raise HTTPException(404, f"Fan '{fan_name}' not found")
    return {"message": f"Fan '{fan_name}' PWM set to {req.pwm}"}


@app.put("/api/fans/{fan_name}/curve")
async def update_fan_curve(fan_name: str, req: FanCurveUpdate):
    """更新风扇温度曲线。"""
    if controller is None:
        raise HTTPException(503, "Controller not initialized")
    if not controller.update_fan_curve(fan_name, req.curve):
        raise HTTPException(404, f"Fan '{fan_name}' not found")
    return {"message": f"Fan '{fan_name}' curve updated"}


@app.get("/api/history")
async def get_history(fan_name: Optional[str] = None, limit: int = 100):
    """获取图表的历史数据。"""
    if controller is None:
        raise HTTPException(503, "Controller not initialized")
    return controller.get_history(fan_name=fan_name, limit=limit)


@app.get("/api/config")
async def get_config():
    """获取当前配置。"""
    if app_config is None:
        raise HTTPException(503, "Not initialized")
    return app_config.model_dump()


@app.put("/api/config")
async def update_config(req: ConfigUpdate):
    """更新应用配置。"""
    global app_config
    if app_config is None:
        raise HTTPException(503, "Not initialized")

    changed = False
    if req.update_interval is not None:
        app_config.update_interval = req.update_interval
        changed = True
    if req.enable_alerts is not None:
        app_config.enable_alerts = req.enable_alerts
        changed = True
    if req.alert_temp_cpu is not None:
        app_config.alert_temp_cpu = req.alert_temp_cpu
        changed = True
    if req.alert_temp_disk is not None:
        app_config.alert_temp_disk = req.alert_temp_disk
        changed = True
    if req.enable_smartctl is not None:
        app_config.enable_smartctl = req.enable_smartctl
        changed = True
    if req.history_retention_days is not None:
        app_config.history_retention_days = max(3, min(90, req.history_retention_days))
        changed = True
    if req.alert_enabled is not None:
        app_config.alert_enabled = req.alert_enabled
        changed = True
    if req.alert_cooldown_minutes is not None:
        app_config.alert_cooldown_minutes = req.alert_cooldown_minutes
        changed = True
    if req.smtp_host is not None:
        app_config.smtp_host = req.smtp_host
        changed = True
    if req.smtp_port is not None:
        app_config.smtp_port = req.smtp_port
        changed = True
    if req.smtp_user is not None:
        app_config.smtp_user = req.smtp_user
        changed = True
    if req.smtp_password is not None:
        app_config.smtp_password = req.smtp_password
        changed = True
    if req.smtp_from is not None:
        app_config.smtp_from = req.smtp_from
        changed = True
    if req.smtp_to is not None:
        app_config.smtp_to = req.smtp_to
        changed = True
    if req.smtp_use_tls is not None:
        app_config.smtp_use_tls = req.smtp_use_tls
        changed = True

    if changed:
        if controller:
            controller.reload_config(app_config)
        # Save config
        try:
            save_config(app_config)
        except Exception as e:
            logger.warning(f"Failed to save config: {e}")

    return {"message": "Configuration updated", "config": app_config.model_dump()}


@app.post("/api/config/save")
async def save_config_endpoint():
    """将当前配置保存到磁盘。"""
    if app_config is None:
        raise HTTPException(503, "Not initialized")
    path = save_config(app_config)
    return {"message": "Configuration saved", "path": path}


@app.get("/api/history/summary")
async def get_history_summary(days: int = 1):
    """获取最近 N 天的温度 min/max/avg 汇总。"""
    return {"days": days, "summary": get_temp_summary(days)}


@app.get("/api/history/temperatures")
async def get_temp_history(sensor_name: Optional[str] = None, days: int = 7, limit: int = 2000):
    """从 SQLite 获取温度历史记录。"""
    return {
        "days": days,
        "sensor": sensor_name,
        "data": read_temperature_history(sensor_name, days, limit),
    }


@app.get("/api/history/fans")
async def get_fan_history(fan_name: Optional[str] = None, days: int = 7, limit: int = 2000):
    """从 SQLite 获取风扇 PWM/RPM 历史记录。"""
    return {
        "days": days,
        "fan": fan_name,
        "data": read_fan_history(fan_name, days, limit),
    }


@app.post("/api/alert/test")
async def test_alert_email():
    """发送测试邮件以验证 SMTP 配置。"""
    if controller is None:
        raise HTTPException(503, "Controller not initialized")
    ok, msg = controller._notifier.send_test_email()
    return {"success": ok, "message": msg}


# --- WebSocket ---

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """WebSocket 端点，用于实时状态更新。"""
    await ws_manager.connect(ws)
    # Set the update callback
    if controller:
        controller.set_update_callback(ws_update_callback)

    try:
        while True:
            # 保持连接，监听客户端消息
            data = await ws.receive_text()
            msg = json.loads(data) if data else {}
            if msg.get("type") == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        ws_manager.disconnect(ws)
    except Exception as e:
        logger.debug(f"WebSocket error: {e}")
        ws_manager.disconnect(ws)


# --- 静态文件（前端）---
# 使用 resolve() 获取绝对路径，不受脚本调用方式影响
frontend_path = Path(__file__).resolve().parent.parent / "frontend"
if frontend_path.exists():
    app.mount("/", StaticFiles(directory=str(frontend_path), html=True), name="frontend")
else:
    logger.warning(f"Frontend directory not found: {frontend_path}")


if __name__ == "__main__":
    port = 8070
    if app_config:
        port = app_config.web_port
    else:
        env_port = os.environ.get("FNOS_FAN_PORT")
        if env_port:
            port = int(env_port)

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        log_level="info",
    )

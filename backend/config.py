"""
FNOS 风扇控制器配置管理。
处理配置文件的加载、保存和运行时更新。
"""

import json
import os
from pathlib import Path
from typing import Any, Optional
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


class FanCurvePoint(BaseModel):
    """A single point on the temperature-PWM curve."""
    temp: float = Field(description="Temperature in degrees Celsius")
    pwm: int = Field(ge=0, le=255, description="PWM value (0-255)")


class FanConfig(BaseModel):
    """Configuration for a single fan."""
    name: str = Field(description="Human-readable fan name")
    hwmon_path: str = Field(description="Path to the fan's hwmon sysfs directory")
    pwm_channel: int = Field(default=1, description="PWM channel number (pwmN)")
    rpm_channel: int = Field(default=1, description="RPM channel number (fanN_input)")
    enabled: bool = Field(default=True, description="Whether this fan is under control")
    mode: str = Field(default="curve", description="Control mode: curve | manual | auto")
    manual_pwm: int = Field(default=128, ge=0, le=255, description="PWM value when mode=manual")
    curve: list[FanCurvePoint] = Field(
        default_factory=lambda: [
            FanCurvePoint(temp=30, pwm=0),
            FanCurvePoint(temp=40, pwm=60),
            FanCurvePoint(temp=50, pwm=120),
            FanCurvePoint(temp=60, pwm=180),
            FanCurvePoint(temp=70, pwm=255),
        ],
        description="Temperature-PWM curve points",
    )
    sensor_source: str = Field(
        default="cpu",
        description="Which sensor to use for curve control: cpu | max | avg | specific:<name>",
    )
    hysteresis: float = Field(
        default=2.0,
        description="Temperature hysteresis in Celsius to prevent oscillation",
    )
    min_pwm: int = Field(default=30, ge=0, le=255, description="Minimum PWM to prevent stall")


class AppConfig(BaseModel):
    """Application configuration."""
    update_interval: int = Field(default=2, description="Control loop interval in seconds")
    data_history_length: int = Field(default=300, description="Number of historical data points to keep")
    enable_smartctl: bool = Field(default=True, description="Enable smartctl for HDD temperatures")
    smartctl_path: str = Field(default="", description="smartctl 路径（留空=自动检测）")
    web_port: int = Field(default=8070, description="Web server port")
    fans: list[FanConfig] = Field(default_factory=list, description="Fan configurations")
    auto_detect: bool = Field(default=True, description="Auto-detect sensors on startup")
    log_level: str = Field(default="INFO", description="Log level: DEBUG | INFO | WARNING | ERROR")
    enable_alerts: bool = Field(default=False, description="启用温度告警")
    alert_temp_cpu: float = Field(default=85.0, description="CPU 告警温度")
    alert_temp_disk: float = Field(default=60.0, description="硬盘告警温度")

    # 历史记录保留
    history_retention_days: int = Field(default=30, ge=3, le=90, description="温度/风扇历史保留天数（3/7/30/90）")

    # 邮件告警（SMTP）
    alert_enabled: bool = Field(default=False, description="发送邮件告警")
    alert_cooldown_minutes: int = Field(default=30, ge=5, le=1440, description="告警邮件最小间隔")
    smtp_host: str = Field(default="", description="SMTP 服务器地址")
    smtp_port: int = Field(default=465, description="SMTP 端口")
    smtp_user: str = Field(default="", description="SMTP 用户名")
    smtp_password: str = Field(default="", description="SMTP 密码")
    smtp_from: str = Field(default="", description="发件人地址（默认同用户名）")
    smtp_to: str = Field(default="", description="告警收件邮箱")
    smtp_use_tls: bool = Field(default=True, description="使用 SSL/TLS 连接")


DEFAULT_CONFIG_PATH = "/etc/fnos-fan-control/config.json"
LOCAL_CONFIG_PATH = "config/config.json"


def get_default_config() -> AppConfig:
    """Return a default configuration."""
    return AppConfig()


def load_config(config_path: Optional[str] = None) -> AppConfig:
    """
    Load configuration from file.
    Priority: explicit path -> /etc/fnos-fan-control/config.json -> ./config/config.json -> defaults
    """
    paths_to_try = []
    if config_path:
        paths_to_try.append(Path(config_path))
    paths_to_try.append(Path(DEFAULT_CONFIG_PATH))
    paths_to_try.append(Path(LOCAL_CONFIG_PATH))

    for p in paths_to_try:
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                return AppConfig(**data)
            except (json.JSONDecodeError, Exception) as e:
                print(f"Warning: Failed to load config from {p}: {e}")
                continue

    return get_default_config()


def save_config(config: AppConfig, config_path: Optional[str] = None) -> str:
    """Save configuration to file.
    Priority: explicit path -> FNOS_FAN_CONFIG env -> ./config/config.json
    """
    if not config_path:
        config_path = os.environ.get("FNOS_FAN_CONFIG", LOCAL_CONFIG_PATH)
    target = Path(config_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(config.model_dump(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return str(target)

"""
温度告警邮件通知模块。
用户自行配置 SMTP 服务器。
"""

import logging
import smtplib
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logger = logging.getLogger("fnos-fan.notifier")


class AlertNotifier:
    """温度超阈值时发送邮件告警。"""

    def __init__(self, config: dict):
        self.smtp_host = config.get("smtp_host", "")
        self.smtp_port = config.get("smtp_port", 465)
        self.smtp_user = config.get("smtp_user", "")
        self.smtp_password = config.get("smtp_password", "")
        self.smtp_from = config.get("smtp_from", "")
        self.smtp_to = config.get("smtp_to", "")
        self.smtp_use_tls = config.get("smtp_use_tls", True)
        self.cooldown_seconds = config.get("alert_cooldown_minutes", 30) * 60
        self.enabled = config.get("alert_enabled", False)

        # 冷却跟踪：传感器名 → 上次告警时间戳
        self._last_alert: dict[str, float] = {}

    @property
    def configured(self) -> bool:
        return bool(self.smtp_host and self.smtp_user and self.smtp_to)

    def reload_config(self, config: dict):
        self.smtp_host = config.get("smtp_host", "")
        self.smtp_port = config.get("smtp_port", 465)
        self.smtp_user = config.get("smtp_user", "")
        self.smtp_password = config.get("smtp_password", "")
        self.smtp_from = config.get("smtp_from", "")
        self.smtp_to = config.get("smtp_to", "")
        self.smtp_use_tls = config.get("smtp_use_tls", True)
        self.cooldown_seconds = config.get("alert_cooldown_minutes", 30) * 60
        self.enabled = config.get("alert_enabled", False)

    def send_alert(self, sensor_name: str, temperature: float, threshold: float) -> bool:
        """发送温度告警邮件。发送成功返回 True，跳过或失败返回 False。"""
        if not self.enabled:
            return False
        if not self.configured:
            logger.warning("Alert enabled but SMTP not configured")
            return False

        # 冷却检查
        now = time.time()
        last = self._last_alert.get(sensor_name, 0)
        if now - last < self.cooldown_seconds:
            return False

        subject = f"[FNOS风扇控制] 温度告警: {sensor_name} = {temperature:.1f}°C"
        body = f"""FNOS 风扇控制 — 温度告警

传感器: {sensor_name}
当前温度: {temperature:.1f}°C
告警阈值: {threshold:.1f}°C
触发时间: {time.strftime('%Y-%m-%d %H:%M:%S')}

请检查设备散热状况。
"""

        try:
            msg = MIMEMultipart()
            msg["From"] = self.smtp_from or self.smtp_user
            msg["To"] = self.smtp_to
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "plain", "utf-8"))

            if self.smtp_use_tls:
                server = smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=10)
            else:
                server = smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=10)
                server.starttls()

            server.login(self.smtp_user, self.smtp_password)
            server.send_message(msg)
            server.quit()

            self._last_alert[sensor_name] = now
            logger.info(f"Alert email sent: {sensor_name} @ {temperature:.1f}°C")
            return True

        except Exception as e:
            logger.error(f"Failed to send alert email: {e}")
            return False

    def send_test_email(self) -> tuple[bool, str]:
        """发送测试邮件以验证 SMTP 配置。"""
        if not self.configured:
            return False, "SMTP服务器未配置"

        subject = "[FNOS风扇控制] 测试邮件"
        body = f"""FNOS 风扇控制 — SMTP 测试邮件

如果您收到此邮件，说明邮件告警配置正确。

发送时间: {time.strftime('%Y-%m-%d %H:%M:%S')}
"""

        try:
            msg = MIMEMultipart()
            msg["From"] = self.smtp_from or self.smtp_user
            msg["To"] = self.smtp_to
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "plain", "utf-8"))

            if self.smtp_use_tls:
                server = smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=10)
            else:
                server = smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=10)
                server.starttls()

            server.login(self.smtp_user, self.smtp_password)
            server.send_message(msg)
            server.quit()

            return True, "测试邮件发送成功"
        except smtplib.SMTPAuthenticationError:
            return False, "SMTP认证失败，请检查用户名和密码"
        except smtplib.SMTPConnectError:
            return False, f"无法连接到 {self.smtp_host}:{self.smtp_port}"
        except Exception as e:
            return False, f"发送失败: {e}"

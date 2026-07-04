# FNOS 风扇控制 & 温度监控

FNOS（飞牛OS）专用。后端 Python/FastAPI，前端原生 JS，FPK 应用中心安装。

## 能干什么

- 自动扫 sysfs/hwmon 下面所有温度传感器、风扇转速和 PWM 控制器
- 读硬盘温度：优先 sysfs hwmon（不用 smartctl），不行动用 smartctl。HBA/阵列卡后面的盘也支持
- PWM 曲线控制风扇，支持拖拽编辑曲线，滞后保护防止反复跳变
- 三种模式：曲线 / 手动 PWM / BIOS 自动
- 温度历史记录存 SQLite，可选保留 3/7/30/90 天，Web 界面回溯查阅
- 温度超限自动发邮件告警（需自配 SMTP 服务器）
- Web 实时仪表盘，WebSocket 推送

## 怎么装

```bash
cd fnos-fan-control
bash fpk/build-fpk.sh x86   # x86_64 设备
bash fpk/build-fpk.sh arm   # ARM 设备
```

FPK 包在 `dist/` 下。飞牛桌面操作：应用中心 → 手动安装 → 上传 fpk → 确认。

## 怎么用

仪表盘能看到实时温度（颜色标识等级）、走势图和风扇转速曲线、每个风扇的 PWM/转速/参考温度。

曲线模式按温度-PWM 曲线自动调转速，手动模式直接拉 PWM（0-255），自动模式丢给 BIOS。

曲线编辑器：拖拽节点、右键加节点、双击删节点、表格输精确值。

## 历史记录

温度历史曲线保留时长在设置里选（3/7/30/90 天），数据存在 `/var/lib/fnos-fan-control/history.db`。每个传感器单独记录，Web 界面可按传感器和时间范围筛选查看。

## 邮件告警

设置页填 SMTP 信息，点测试验证。温度超阈值自动发邮件，同一传感器两次告警间隔可设（默认 30 分钟防刷屏）。

常用邮箱 SMTP：
- QQ 邮箱：smtp.qq.com:465，用户名为 QQ 邮箱地址，密码用授权码
- 163 邮箱：smtp.163.com:465，密码用授权码
- Gmail：smtp.gmail.com:587，需开启两步验证 + 应用专用密码

## 配置

配置文件在 `/etc/fnos-fan-control/config.json`：

```json
{
    "update_interval": 2,
    "web_port": 8070,
    "enable_smartctl": true,
    "smartctl_path": "",
    "fans": [],
    "auto_detect": true,
    "history_retention_days": 30,
    "enable_alerts": false,
    "alert_temp_cpu": 85.0,
    "alert_temp_disk": 60.0,
    "alert_enabled": false,
    "alert_cooldown_minutes": 30,
    "smtp_host": "",
    "smtp_port": 465,
    "smtp_user": "",
    "smtp_password": "",
    "smtp_from": "",
    "smtp_to": "",
    "smtp_use_tls": true
}
```

`sensor_source` 可选：`cpu`、`max`、`avg`、`specific:传感器名`。

## 注意

PWM 写入要 root 权限。程序直接控风扇，曲线错了可能过热，先观察再长期跑。停掉会恢复 BIOS 自动控制。BMC/IPMI 管的服务器可能没有 sysfs PWM 节点，温度能看风扇控不了。

## 目录

```
fnos-fan-control/
├── backend/         FastAPI 后端
│   ├── main.py      入口 + API
│   ├── config.py    配置
│   ├── sensors.py   传感器扫描
│   ├── controller.py PWM 控制引擎
│   ├── history.py   历史记录
│   ├── notifier.py  邮件告警
│   └── requirements.txt
├── frontend/        Web 前端
├── fpk/             FPK 打包
├── config/          默认配置
└── dist/            构建输出
```

## 出问题了

硬盘温度读不到？先看 sysfs hwmon（快），不行才 smartctl。确认装了：`smartctl --version`。手工试：`smartctl -A /dev/sda`。

风扇控不了？`ls /sys/class/hwmon/*/pwm*` 看看有没有。确认 root。BMC 管的机器没 PWM。

温度不对？跑 `sensors`，查日志。

邮件发不出？用测试按钮看错误信息。

## License

MIT

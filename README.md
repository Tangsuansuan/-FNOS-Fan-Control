# FNOS 风扇控制 & 温度监控

[English](#) | 简体中文

给 FNOS（飞牛OS）做的风扇控制和温度监控工具。后端 Python/FastAPI，前端原生 JS，打包成 FPK 在应用中心装。

## 能干什么

- 自动扫 sysfs/hwmon 下面所有能读的温度传感器、风扇转速和 PWM 控制器
- 读硬盘温度：优先走 sysfs hwmon（不用 smartctl 也能读），读不到才用 smartctl。LSI MegaRAID、SAS HBA、HP SmartArray、3Ware 这些卡后面的盘也支持
- PWM 曲线控制风扇：拖拽编辑曲线，多节点插值，有滞后保护防止反复跳变
- 三种模式：按曲线跑、手动设 PWM、扔回 BIOS 自己管
- Web 界面看实时温度趋势和风扇转速，WebSocket 推送
- 温度超了弹告警
- 打成 .fpk 包，飞牛应用中心直接装

## 什么硬件能用

| | |
|---|---|
| 内核 | 3.x ~ 6.x 都试过 |
| 系统 | fnOS、Debian、Ubuntu、CentOS、RHEL、Fedora、Arch、Alpine |
| CPU | Intel、AMD、ARM（树莓派、RK3588、全志 H6 这些） |
| 硬盘 | SATA、SAS、NVMe、老 IDE 盘 |
| HBA/阵列卡 | LSI MegaRAID、LSI SAS HBA（mpt3sas/mpt2sas）、HP SmartArray、3Ware、Adaptec、Marvell、Intel RST、ASMedia、VirtIO |
| 监控芯片 | ITE IT87 全家、Nuvoton NCT 全家、Winbond W83 全家、Fintek F7 全家 |
| Python | 3.8 以上就行 |

## 怎么装

### FPK 安装（推荐）

```bash
cd fnos-fan-control
bash fpk/build-fpk.sh

# 传到 NAS 上
scp dist/fnos-fan-control_1.1.0_x86.fpk root@<nas-ip>:/tmp/
ssh root@<nas-ip> 'appcenter-cli install-fpk /tmp/fnos-fan-control_1.1.0_x86.fpk'
```

或者在飞牛桌面操作：应用中心 → 左下角「手动安装」→ 上传 fpk → 确认。桌面上会出现「风扇控制」图标。

### 直接跑

```bash
cd backend
pip install -r requirements.txt
python main.py
```

浏览器打开 `http://<NAS_IP>:8070`

## 怎么用

仪表盘上能看到所有传感器的实时温度（颜色标识级别）、温度走势图和风扇转速曲线、每个风扇当前的 PWM 值、转速和参考温度。

控制风扇有三种：曲线模式按你设的温度-PWM 曲线自动调、手动模式直接拉 PWM（0-255）、自动模式丢给 BIOS。

曲线编辑器支持拖拽节点、右键加新节点、双击删节点，也可以在表格里敲精确数值。

## 配置

配置文件在 `/etc/fnos-fan-control/config.json`：

```json
{
    "update_interval": 2,
    "data_history_length": 300,
    "enable_smartctl": true,
    "smartctl_path": "",
    "web_port": 8070,
    "fans": [],
    "auto_detect": true,
    "log_level": "INFO",
    "enable_alerts": false,
    "alert_temp_cpu": 85.0,
    "alert_temp_disk": 60.0
}
```

`smartctl_path` 留空就行，程序会自己找 smartctl 在哪。

如果需要手动配风扇：

```json
{
    "fans": [
        {
            "name": "CPU_Fan",
            "hwmon_path": "/sys/class/hwmon/hwmon2",
            "pwm_channel": 1,
            "rpm_channel": 1,
            "enabled": true,
            "mode": "curve",
            "sensor_source": "cpu",
            "hysteresis": 2.0,
            "min_pwm": 30,
            "curve": [
                {"temp": 30, "pwm": 0},
                {"temp": 40, "pwm": 60},
                {"temp": 50, "pwm": 120},
                {"temp": 60, "pwm": 180},
                {"temp": 70, "pwm": 255}
            ]
        }
    ]
}
```

sensor_source 可以填：
- `cpu` — CPU 温度（自动找 coretemp/k10temp）
- `max` — 所有传感器里最高的那个
- `avg` — 所有传感器的平均值
- `specific:传感器名` — 指定某个传感器

## 注意

PWM 写入要 root 权限。这程序直接控硬件风扇，曲线设错了可能过热，建议先挂着观察一阵再长期跑。停掉服务后风扇会恢复 BIOS 自动控制。

有些 NAS 硬件（比如 BMC/IPMI 管的）没有 sysfs PWM 节点，温度能看但风扇控不了。

## 目录结构

```
fnos-fan-control/
├── backend/              后端
│   ├── main.py           入口 + API 路由 + WebSocket
│   ├── config.py         配置模型和读写
│   ├── sensors.py        hwmon + sysfs + smartctl 传感器扫描
│   ├── controller.py     PWM 曲线控制引擎
│   └── requirements.txt
├── frontend/             Web 前端
│   ├── index.html
│   ├── css/style.css
│   └── js/
│       ├── api.js        REST + WebSocket 客户端
│       ├── charts.js     Chart.js 图表 + 曲线编辑器
│       └── app.js        主逻辑
├── fpk/                  FPK 打包
│   ├── manifest          应用清单
│   ├── cmd/              生命周期脚本
│   ├── config/           权限/资源配置
│   ├── ui/               桌面图标配置
│   ├── health.json       健康检查
│   ├── generate_icons.py 图标生成
│   └── build-fpk.sh      打包脚本
├── docker/               Docker 部署（可选）
├── config/default.json   默认配置
├── scripts/install.sh    systemd 安装脚本
└── dist/                 构建出来的 fpk
```

## 出问题了

硬盘温度读不到？
程序先试 sysfs hwmon（快），不行才用 smartctl。确认 smartctl 装了没：`smartctl --version`。手工试试：`smartctl -A /dev/sda`，HBA 后面的盘可能要加 `-d megaraid,0` 之类的参数。日志在 `/var/log/fnos-fan-control/start.log`。

风扇控不了？
先看看有没有 PWM 接口：`ls /sys/class/hwmon/*/pwm*`。确认是 root 跑的。有些服务器主板风扇是 BMC 管的，系统层面碰不到。

温度不对？
跑 `sensors` 看看系统能不能读到。查应用日志。

## License

MIT

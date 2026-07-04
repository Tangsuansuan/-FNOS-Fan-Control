# 代码审查指南 — FNOS 风扇控制器 v1.1.0

写这个文档是为了让审查代码的人不用从头啃。下面是项目怎么组织的、哪些地方值得多看一眼、已经知道有哪些坑。

---

## 项目概览

给飞牛 fnOS 做的风扇控制 + 温度监控。后端 Python + FastAPI，前端原生 JS，FPK 打包成普通应用（不是 Docker）在应用中心装。

数据怎么走的：

```
sysfs (/sys/class/hwmon, /sys/block/*/device/hwmon)
        ↓
SensorScanner (sensors.py)  ←── smartctl（HBA 后面的盘读不到 sysfs 时回退）
        ↓
FanController (controller.py)  ←── AppConfig (config.py)
        ↓ 写 PWM
sysfs (pwmN)
        ↑
        ↓ WebSocket
FastAPI (main.py)  ←── REST API  ←── 前端 (frontend/)
```

---

## 怎么读这个项目

建议按这个顺序看，从数据模型到硬件交互再到控制逻辑：

1. `config.py`（~150 行）— Pydantic 模型和 JSON 读写，看完就知道所有配置项
2. `sensors.py`（~760 行）— 传感器扫描，这是最复杂的模块，HBA 检测和温度解析都在这里
3. `controller.py`（~440 行）— 控制循环、曲线插值、滞后防抖，安全关键
4. `main.py`（~390 行）— FastAPI 路由、WebSocket、生命周期，串联所有模块
5. 前端 `app.js` — 确认 API 调用和状态管理方式
6. FPK 配置 — `manifest`、`cmd/main`、`cmd/install_init`

---

## 各文件重点

### sensors.py（~760 行）

整个项目最复杂的文件。做三件事：扫 hwmon 传感器、读 sysfs 硬盘温度、smartctl 回退。

**值得看的地方**：

- `_find_smartctl()` — smartctl 路径不硬编码，8 个常见路径挨个试，不行就 `which`，支持各种发行版
- `scan_disks()` — 从 `/sys/block/` 扫真实物理设备（排除 loop/dm/md 这些虚拟的），先试 `_read_disk_temp_from_sysfs()` 从 hwmon 读（毫秒级，大部分盘都能走这条路），读不到才用 smartctl
- `_load_hba_info()` → `_get_smartctl_device_types()` — 读 sysfs 拿到驱动名，在 30+ 种驱动的映射表里找对应的 smartctl -d 参数，不用盲试
- `_parse_sata_temp()` — 4 级回退解析温度：标准化值 → raw.value → raw.string 正则提取 → SCSI current_temperature。不同厂商的 smartctl 输出格式差很多，这里尽量都兼容了
- `_HWMON_NAME_MAP` — 150+ 条传感器驱动名到中文的翻译，涵盖主流 CPU/主板/GPU/网卡/SIO

**潜在坑**：未知 HBA 驱动会用 `_GENERIC_DEVICE_TYPES` 盲试，队列最长可能 10 种参数，单盘最多 10 次 smartctl 调用。

### controller.py（~440 行）

控制循环的核心，120 行以内的代码决定了风扇的生死。

**安全点**：
- `min_pwm` 默认 30，防止风扇停转（PWM=0 不等于风扇停，但 PWM 过低可能停）
- `stop()` 会恢复所有风扇为 auto 模式，不管程序怎么挂的，风扇都能回到 BIOS 控制
- 滞后（hysteresis）默认 2°C，防止温度在阈值附近来回跳导致风扇反复加速减速

**值得看的地方**：
- `_control_loop()` — asyncio 独立 Task，每 `update_interval` 秒跑一轮
- `_compute_pwm()` — 根据曲线插值算 PWM，线性插值，超出曲线范围时 clamp 到边界
- `reload_config()` — 配置热更新，但会清空历史数据

### config.py（~150 行）

Pydantic BaseModel + JSON 持久化。`smartctl_path` 默认空字符串，SensorScanner 会自己找。

**已知小问题**：`except (json.JSONDecodeError, Exception)` 里 JSONDecodeError 实际上被 Exception 覆盖了，虽然不影响功能但代码意图不清晰。

### main.py（~390 行）

FastAPI 应用，用了 lifespan 管理启动/关闭。CORS 全开（NAS 局域网场景，没做鉴权）。

**已知问题**：
- `__main__` 里检查 `app_config`，这个变量只在 lifespan 里赋值，直接 `python main.py` 运行时恒为 None，实际走的是环境变量 `FNOS_FAN_PORT`
- rescan 接口调用 `controller._init_fan_states()`，调了私有方法

### 前端（frontend/）

纯原生 JS，没用框架。Chart.js 画图表，Canvas 做曲线编辑器。

**潜在坑**：曲线编辑器的 Canvas 事件绑定和 resize 处理；WebSocket 断线重连逻辑在 `api.js` 里。

---

## v1.1.0 新增的东西

这一版主要解决通用兼容性，不再针对单一硬件：

- smartctl 路径自适应（不写死 `/usr/sbin/smartctl`）
- 磁盘扫描从 `/dev/` 改成 `/sys/block/`，自动过滤虚拟设备
- sysfs hwmon 优先读温（80%+ 的盘不用 smartctl，毫秒级）
- HBA 驱动自动检测，不再盲试参数
- 并行 smartctl 扫描（Semaphore(8)）
- 传感器翻译表扩大到 150+ 条
- Python 3.8+ 兼容

---

## 已知问题

### 建议修

1. `config.py` — `except (json.JSONDecodeError, Exception)` 冗余，改成 `except Exception`
2. `main.py` — rescan 调了 `controller._init_fan_states()` 私有方法，应该加个公开方法
3. `main.py` 的 `__main__` — `app_config` 判断永远为 None，直接用环境变量
4. `fpk/cmd/` — 6 个回调脚本是空存根（`exit 0`），要么实现要么删了

### 安全

5. 所有 API 没鉴权 — 局域网部署场景可以接受，但谁都能调接口控风扇
6. CORS `*` + `allow_credentials=True` — 同上，局域网场景没问题

### 代码质量

7. 前端没有构建工具、没有 TypeScript — 功能不多的时候还行，扩展的话要上
8. `controller.reload_config()` 清历史数据 — 行为没错但用户可能意外
9. 全局变量 `app_config`/`scanner`/`controller` = None — 在 FastAPI 里常见，但不够优雅

---

## 安全检查点

- PWM 下限：`min_pwm` 默认 30，手动模式 `set_fan_manual_pwm` 也有 `max(0, min(255))` 兜底
- 停机恢复：`controller.stop()` 把所有风扇切回 auto
- 控制循环容错：`_control_loop` 捕获 Exception 继续跑，极端情况下可能静默吞错
- smartctl 调用：`create_subprocess_exec` 不是 shell，参数由 HBA 检测表生成，没有注入风险
- 配置写入：路径来自环境变量或硬编码，没有路径遍历问题

---

## 快速跑起来

```bash
cd backend
pip install -r requirements.txt
python main.py
# http://localhost:8070

# 看 API 正不正常
curl http://localhost:8070/api/status  | python -m json.tool
curl http://localhost:8070/api/sensors | python -m json.tool
curl http://localhost:8070/api/config  | python -m json.tool

# 打 FPK 包
bash fpk/build-fpk.sh
# → dist/fnos-fan-control_1.1.0_x86.fpk
```

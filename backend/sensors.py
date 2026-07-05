"""
硬件传感器扫描模块 — 通用兼容版本。
支持：
  - Linux 内核 3.x ~ 6.x
  - Debian / Ubuntu / CentOS / RHEL / Fedora / Arch / Alpine / fnOS
  - SATA / SAS / NVMe / IDE / USB / eMMC 硬盘
  - AHCI / LSI MegaRAID / LSI SAS HBA (mpt3sas/mpt2sas) / 3Ware /
    HP SmartArray / Adaptec / Marvell / ASMedia / Intel RST / VirtIO
  - smartctl 路径和 HBA 驱动类型自动检测
  - sysfs 温度（hwmon）优先，smartctl 作为补充
"""

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger("fnos-fan.sensors")

# -------- sysfs 根路径（容器可覆盖）--------
SYSFS_BASE = os.environ.get("SYSFS_PATH", "/sys")
HWMON_BASE = os.path.join(SYSFS_BASE, "class/hwmon")
BLOCK_BASE = os.path.join(SYSFS_BASE, "block")
DEV_BASE = os.environ.get("DEV_PATH", "/dev")
THERMAL_BASE = os.path.join(SYSFS_BASE, "class/thermal")
SCSI_HOST_BASE = os.path.join(SYSFS_BASE, "class/scsi_host")

# -------- 已知 smartctl 安装路径（按可能性排序）--------
_SMARTCTL_CANDIDATES = [
    "/usr/sbin/smartctl",
    "/usr/bin/smartctl",
    "/sbin/smartctl",
    "/bin/smartctl",
    "/usr/local/sbin/smartctl",
    "/usr/local/bin/smartctl",
    "/opt/sbin/smartctl",
    "/opt/bin/smartctl",
]

# -------- HBA / RAID 驱动 → 推荐的 smartctl -d 参数回退列表 --------
# 需要指定设备类型的驱动，按顺序尝试直到 smartctl 返回有效数据
# until smartctl returns valid data.
_HBA_DRIVER_DEVICE_TYPES: dict[str, list[str]] = {
    # LSI / Broadcom MegaRAID — 需要槽位号
    "megaraid_sas":      ["", "megaraid,0", "megaraid,1", "megaraid,2", "megaraid,3",
                           "megaraid,4", "megaraid,5", "megaraid,6", "megaraid,7",
                           "megaraid,8", "megaraid,9", "megaraid,10", "megaraid,11",
                           "megaraid,12", "megaraid,13", "megaraid,14", "megaraid,15"],
    # HP SmartArray
    "hpsa":              ["cciss,0", "cciss,1", "cciss,2", "cciss,3"],
    "hpahcisr":          ["cciss,0", "cciss,1"],
    # Adaptec
    "aacraid":           ["", "aacraid,0", "aacraid,1", "aacraid,2", "aacraid,3",
                           "aacraid,4", "aacraid,5", "aacraid,6", "aacraid,7",
                           "arcmsr"],
    # 3Ware
    "3w-9xxx":           ["3ware,0", "3ware,1", "3ware,2", "3ware,3",
                           "3ware,4", "3ware,5", "3ware,6", "3ware,7",
                           "3ware,8", "3ware,9"],
    "3w-sas":            ["3ware,0", "3ware,1", "3ware,2", "3ware,3",
                           "3ware,4", "3ware,5", "3ware,6", "3ware,7",
                           "3ware,8", "3ware,9"],
    # Marvell SATA 控制器
    "mvsas":             ["", "marvell"],
    "sata_mv":           ["", "marvell"],
    # Areca RAID
    "arcmsr":            ["", "areca,1", "areca,0", "areca,2", "areca,3"],
    # Intel RST / VMD
    "isci":              ["", "sat"],
    "vmd":               ["", "sat"],
    # PMC / Microchip SAS
    "pm80xx":            ["", "sat"],
    "pmcraid":           ["", "sat"],
    # 华为海思 SAS（鲲鹏等 ARM 服务器）
    "hisi_sas":          ["", "sat"],
    # LSI / Broadcom SAS HBA（IT 模式）— 通常默认或 sat 即可
    "mpt3sas":           ["", "sat"],
    "mpt2sas":           ["", "sat"],
    "mptsas":            ["", "sat"],
    # AHCI / ATA — 通常开箱即用
    "ahci":              [""],
    "ata_piix":          [""],
    "sata_sil":          [""],
    "sata_sil24":        [""],
    "sata_nv":           [""],
    "sata_via":          [""],
    "sata_sis":          [""],
    "sata_uli":          [""],
    "sata_promise":      [""],
    "pata_marvell":      [""],
    # ASMedia
    "asmedia":           [""],
    "ahci_asmedia":      [""],
    # JMicron
    "jmicron":           [""],
    "ahci_jmicron":      [""],
    # VirtIO（虚拟机）
    "virtio_scsi":       [""],
    "virtio_blk":        [""],
    # USB 存储 — 可能需要 -d sat
    "usb-storage":       ["", "sat", "usbjmicron", "usbprolific", "usbsunplus"],
    "uas":               ["", "sat", "usbjmicron", "usbprolific", "usbsunplus"],
}

# 未知驱动时的通用回退列表
_GENERIC_DEVICE_TYPES = [
    "", "sat", "auto", "scsi", "sas",
    "megaraid,0", "3ware,0", "cciss,0", "areca,0", "marvell",
]

# 需要跳过的虚拟块设备前缀
_SKIP_DEV_PREFIXES = frozenset([
    "loop",   # 回环设备
    "ram",    # 内存盘
    "zram",   # 压缩内存
    "nbd",    # 网络块设备
    "sr",     # 光驱
    "pmem",   # 持久内存
])

# 需要跳过的虚拟设备名（前缀匹配）
_SKIP_DEV_NAMES = frozenset([
    "dm-",    # device mapper
    "md",     # 软件 RAID
    "zd",     # ZFS zvol
])


# ======================== 传感器名翻译 ========================

_HWMON_NAME_MAP: dict[str, str] = {
    # CPU 传感器
    "coretemp":           "CPU核心",
    "k10temp":            "CPU",
    "zenpower":           "CPU",
    "cpu_thermal":        "CPU",
    "cpu-thermal":        "CPU",
    "pkg_temp_thermal":   "CPU封装",
    # 主板 / 芯片组
    "acpitz":             "主板",
    "pch_cannonlake":     "PCH芯片组",
    "pch_cometlake":      "PCH芯片组",
    "pch_skylake":        "PCH芯片组",
    "pch_alderlake":      "PCH芯片组",
    "pch_raptorlake":     "PCH芯片组",
    "pch_tigerlake":      "PCH芯片组",
    "pch_icelake":        "PCH芯片组",
    "pch_haswell":        "PCH芯片组",
    "pch_broadwell":      "PCH芯片组",
    "pch":                "PCH芯片组",
    # 显卡
    "amdgpu":             "AMD显卡",
    "radeon":             "AMD显卡",
    "nouveau":            "NVIDIA显卡",
    "i915":               "Intel核显",
    "xe":                 "Intel核显",
    "gpu_thermal":        "GPU",
    # 存储（NVMe hwmon 条目）
    "nvme":               "NVMe硬盘",
    "drivetemp":          "SATA硬盘",
    # 网卡
    "iwlwifi_1":          "WiFi网卡",
    "be2net":             "万兆网卡",
    "bnx2x":              "万兆网卡",
    "bnxt_en":            "万兆网卡",
    "mlx4_core":          "万兆网卡",
    "mlx5_core":          "万兆网卡",
    "cxgb4":              "万兆网卡",
    "atlantic":           "万兆网卡",
    "igb":                "千兆网卡",
    "e1000e":             "千兆网卡",
    "r8169":              "千兆网卡",
    "r8125":              "2.5G网卡",
    "r8126":              "5G网卡",
    "tg3":                "千兆网卡",
    "ixgbe":              "万兆网卡",
    "i40e":               "万兆网卡",
    "iavf":               "万兆网卡",
    "ice":                "万兆网卡",
    "ena":                "万兆网卡",
    "enic":               "万兆网卡",
    "sfc":                "万兆网卡",
    "nfp":                "万兆网卡",
    "liquidio":           "万兆网卡",
    "qede":               "万兆网卡",
    "thunderx":           "万兆网卡",
    "netxtreme2":         "万兆网卡",
    "mt7915e":            "WiFi网卡",
    "mt7921e":            "WiFi网卡",
    "mt76":               "WiFi网卡",
    "ath10k":             "WiFi网卡",
    "ath11k":             "WiFi网卡",
    "ath12k":             "WiFi网卡",
    # Super I/O / 硬件监控芯片
    "thinkpad":           "主板",
    "dell_smm":           "主板",
    "it8620":             "主板",
    "it8622":             "主板",
    "it8625":             "主板",
    "it8655":             "主板",
    "it8665":             "主板",
    "it8686":             "主板",
    "it8688":             "主板",
    "it8792":             "主板",
    "it87":               "主板",
    "it8712":             "主板",
    "it8716":             "主板",
    "it8718":             "主板",
    "it8720":             "主板",
    "it8721":             "主板",
    "it8728":             "主板",
    "it8772":             "主板",
    "it8783":             "主板",
    "it8786":             "主板",
    "nct6683":            "主板",
    "nct6686":            "主板",
    "nct6687":            "主板",
    "nct6775":            "主板",
    "nct6776":            "主板",
    "nct6779":            "主板",
    "nct6791":            "主板",
    "nct6792":            "主板",
    "nct6793":            "主板",
    "nct6795":            "主板",
    "nct6796":            "主板",
    "nct6797":            "主板",
    "nct6798":            "主板",
    "nct6106":            "主板",
    "w83627ehf":          "主板",
    "w83627dhg":          "主板",
    "w83627hf":           "主板",
    "w83627thf":          "主板",
    "w83781d":            "主板",
    "w83791d":            "主板",
    "w83792d":            "主板",
    "w83793":             "主板",
    "w83795":             "主板",
    "f71805f":            "主板",
    "f71858":             "主板",
    "f71862":             "主板",
    "f71869":             "主板",
    "f71872":             "主板",
    "f71882":             "主板",
    "f71889":             "主板",
    "f75375":             "主板",
    "f75387":             "主板",
    "fschmd":             "主板",
    "sch5627":            "主板",
    "sch5636":            "主板",
    "dme1737":            "主板",
    "pc87360":            "主板",
    "pc8736x":            "主板",
    "pc87427":            "主板",
    "smsc47b397":         "主板",
    "smsc47m1":           "主板",
    "smsc47m192":         "主板",
    "vt1211":             "主板",
    "vt8231":             "主板",
    "lm63":               "主板",
    "lm64":               "主板",
    "lm70":               "主板",
    "lm73":               "主板",
    "lm75":               "主板",
    "lm77":               "主板",
    "lm78":               "主板",
    "lm80":               "主板",
    "lm83":               "主板",
    "lm85":               "主板",
    "lm87":               "主板",
    "lm90":               "主板",
    "lm92":               "主板",
    "lm93":               "主板",
    "lm95234":            "主板",
    "adm1021":            "主板",
    "adm1025":            "主板",
    "adm1026":            "主板",
    "adm1029":            "主板",
    "adm1031":            "主板",
    "adm9240":            "主板",
    "ds1621":             "主板",
    "ds1780":             "主板",
    "max1619":            "主板",
    "max6650":            "主板",
    "max6696":            "主板",
    "gl518sm":            "主板",
    "gl520sm":            "主板",
    "thmc50":             "主板",
    # 厂商专用
    "asus":               "华硕主板",
    "asuswmi":            "华硕主板",
    "asusec":             "华硕主板",
    "gigabyte_wmi":       "技嘉主板",
    "msi_wmi":            "微星主板",
    "nzxt-smart2":        "NZXT控制器",
    "corsairpsu":         "海盗船电源",
    "corsaircpro":        "海盗船控制器",
    "aquacomputer":       "Aqua电脑",
    # ARM / 嵌入式
    "scpi_sensors":       "系统传感器",
    "sun8i-thermal":      "CPU",
    "sun50i-thermal":     "CPU",
    "rockchip-thermal":   "CPU",
    "imx_thermal":        "CPU",
    "qoriq_thermal":      "CPU",
    "brcmstb_thermal":    "CPU",
    "bcm2835_thermal":    "CPU",
    "raspberrypi-hwmon":  "树莓派",
    "jc42":               "内存温度",
    "tmp421":             "温度传感器",
    "tmp102":             "温度传感器",
    "tmp103":             "温度传感器",
    "tmp108":             "温度传感器",
    "tmp401":             "温度传感器",
    "tmp411":             "温度传感器",
    "tmp431":             "温度传感器",
    "tmp432":             "温度传感器",
    "tmp461":             "温度传感器",
    "tmp464":             "温度传感器",
    "tmp513":             "温度传感器",
    "emc1403":            "温度传感器",
    "emc2103":            "温度传感器",
    "emc6w201":           "温度传感器",
    "adt7462":            "温度传感器",
    "adt7470":            "温度传感器",
    "adt7473":            "温度传感器",
    "adt7475":            "温度传感器",
    "adt7476":            "温度传感器",
    "adt7490":            "温度传感器",
}

# 已知 sysfs 标签 → 中文翻译
_LABEL_MAP: dict[str, str] = {
    "Package id 0":        "CPU封装",
    "Core 0":              "核心0",  "Core 1":  "核心1",
    "Core 2":              "核心2",  "Core 3":  "核心3",
    "Core 4":              "核心4",  "Core 5":  "核心5",
    "Core 6":              "核心6",  "Core 7":  "核心7",
    "Core 8":              "核心8",  "Core 9":  "核心9",
    "Core 10":             "核心10", "Core 11": "核心11",
    "Core 12":             "核心12", "Core 13": "核心13",
    "Core 14":             "核心14", "Core 15": "核心15",
    "Tdie":                "CPU温度",
    "Tctl":                "CPU温度",
    "Tccd1":               "CCD1温度",
    "Tccd2":               "CCD2温度",
    "Composite":           "主控温度",
    "Sensor 1":            "传感器1",  "Sensor 2": "传感器2",
    "Sensor 3":            "传感器3",  "Sensor 4": "传感器4",
    "Ambient":             "环境温度",
    "Edge":                "核心边缘",
    "Junction":            "核心结温",
    "Memory":              "内存温度",
    "VR":                  "供电温度",
    "Vcore":               "核心电压温度",
    "SYSTIN":              "系统温度",
    "CPUTIN":              "CPU温度",
    "AUXTIN0":             "辅温0",
    "AUXTIN1":             "辅温1",
    "AUXTIN2":             "辅温2",
    "AUXTIN3":             "辅温3",
    "SMBUSMASTER 0":       "SMBus主控",
    "PCH_CHIP_CPU_MAX_TEMP": "PCH温度",
    "PCH_CHIP_TEMP":       "PCH温度",
    "PCH_CPU_TEMP":        "PCH温度",
    "TS-on-DIMM":          "内存",
    "CPU":                 "CPU",
    "System":              "系统",
    "Chipset":             "芯片组",
    "MOS":                 "MOS管",
    "VRM":                 "供电模块",
    "GPU":                 "GPU",
    "Hot Spot":            "热点",
    "MEM Hot Spot":        "显存热点",
    "SODIMM":              "内存",
    "PCIe":                "PCIe",
    "PECI":                "CPU(外置)",
    "Board":               "板载",
    "SMBus Master":        "SMBus主控",
    "Thermistor":          "热敏电阻",
    "DIMM":                "内存",
    "DIMM 0":              "内存0",  "DIMM 1": "内存1",
    "DIMM 2":              "内存2",  "DIMM 3": "内存3",
    "PCH Temp":            "PCH温度",
    "MB Temp":             "主板温度",
    "VRM Temp":            "供电温度",
    "SOC Temp":            "SoC温度",
    "DDR Temp":            "内存温度",
}

_TYPE_SUFFIX: dict[str, str] = {
    "temperature": "温度",
    "fan_rpm":     "转速",
    "fan_pwm":     "控制",
}


# ======================== 数据类 ========================

@dataclass
class SensorInfo:
    """检测到的传感器信息。"""
    name: str
    sensor_type: str             # "temperature" | "fan_rpm" | "fan_pwm"
    source: str                  # "hwmon" | "smartctl" | "sysfs"
    hwmon_path: str              # hwmon 基础路径
    channel: int                 # 通道号（如 temp1_input 则为 1）
    label: str = ""
    current_value: float = 0.0
    unit: str = ""
    raw_name: str = ""
    dev_path: str = ""


@dataclass
class HwmonDevice:
    """检测到的 hwmon 设备。"""
    hwmon_path: str
    name: str
    device_path: str = ""
    temperatures: list[SensorInfo] = field(default_factory=list)
    fan_rpms: list[SensorInfo] = field(default_factory=list)
    fan_pwms: list[SensorInfo] = field(default_factory=list)


@dataclass
class DiskInfo:
    """磁盘温度信息。"""
    device: str                  # 如 "/dev/sda"
    dev_name: str = ""           # 如 "sda"
    model: str = ""              # 磁盘型号
    serial: str = ""             # 序列号
    temperature: float = 0.0     # 温度（摄氏度）
    is_nvme: bool = False
    smart_available: bool = True
    temp_source: str = ""        # "sysfs" | "smartctl"


# ======================== 辅助函数 ========================

def _read_sysfs(path: str) -> Optional[str]:
    """读取单个 sysfs 文件，返回去除空白的内容或 None。"""
    try:
        with open(path, "r", encoding="ascii", errors="replace") as f:
            return f.read().strip()
    except (FileNotFoundError, PermissionError, OSError):
        return None


def _read_sysfs_int(path: str) -> Optional[int]:
    """读取 sysfs 整数值。"""
    s = _read_sysfs(path)
    if s is not None:
        try:
            return int(s)
        except ValueError:
            pass
    return None


def translate_sensor_name(hwmon_name: str, channel: int, label: str = "",
                          sensor_type: str = "temperature") -> str:
    """将原始 hwmon 传感器名翻译为中文显示名。"""
    if label:
        # 直接标签翻译
        translated = _LABEL_MAP.get(label)
        if translated:
            return translated
        # 如果标签看起来像硬盘型号（大小写混合、长度>8），保留原始文本
        if any(c.isupper() for c in label) and len(label) > 8:
            suffix = _TYPE_SUFFIX.get(sensor_type, "")
            return f"{label} {suffix}"
        return label or f"{_HWMON_NAME_MAP.get(hwmon_name, hwmon_name)} {_TYPE_SUFFIX.get(sensor_type, '')}"

    dev_name = _HWMON_NAME_MAP.get(hwmon_name, hwmon_name)
    suffix = _TYPE_SUFFIX.get(sensor_type, "")
    if channel == 0:
        return f"{dev_name}{suffix}"
    return f"{dev_name}{channel}{suffix}"


def _is_virtual_block_device(dev_name: str) -> bool:
    """检查 /sys/block 设备是否为虚拟设备（loop、dm、md 等）。"""
    # 精确前缀匹配
    if dev_name[:4] in _SKIP_DEV_PREFIXES:
        return True
    if dev_name[:3] in _SKIP_DEV_PREFIXES:
        return True
    # 前缀匹配（dm-0, md0 等）
    for prefix in _SKIP_DEV_NAMES:
        if dev_name.startswith(prefix):
            return True
    return False


def _find_smartctl() -> Optional[str]:
    """自动检测 smartctl 二进制路径。"""
    for path in _SMARTCTL_CANDIDATES:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    # 最后手段：which
    try:
        result = subprocess.run(
            ["which", "smartctl"], capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return None


# ======================== HBA / sysfs 辅助 ========================

def _get_block_sysfs(dev_name: str, attr: str) -> Optional[str]:
    """读取 /sys/block/<dev>/device/<attr> 属性。"""
    return _read_sysfs(os.path.join(BLOCK_BASE, dev_name, "device", attr))


def _load_hba_info(dev_name: str) -> dict:
    """从 sysfs 收集块设备 HBA/驱动信息。
    返回 dict，包含 driver, transport, vendor, scsi_level, host 等键。
    """
    info: dict = {}
    device_base = os.path.join(BLOCK_BASE, dev_name, "device")

    # 驱动名（readlink .../device/driver）
    driver_link = os.path.join(device_base, "driver")
    try:
        driver_target = os.readlink(driver_link)
        info["driver"] = os.path.basename(driver_target)
    except OSError:
        info["driver"] = ""

    # 传输类型
    transport = os.path.join(device_base, "transport")
    try:
        transport_entries = os.listdir(transport) if os.path.isdir(transport) else []
        info["transport"] = transport_entries[0] if transport_entries else ""
    except OSError:
        info["transport"] = ""

    # SCSI 级别 / 类型
    info["scsi_type"] = _read_sysfs(os.path.join(device_base, "type") or "")
    info["scsi_level"] = _read_sysfs(os.path.join(device_base, "scsi_level") or "")

    # 厂商（如 "ATA     ", "SEAGATE ", "HGST    "）
    info["vendor"] = (_read_sysfs(os.path.join(device_base, "vendor")) or "").strip()

    return info


def _get_smartctl_device_types(hba_info: dict) -> list[str]:
    """Given HBA info, return the recommended smartctl -d device type list
    to try in order.
    """
    driver = hba_info.get("driver", "") or ""
    transport = hba_info.get("transport", "") or ""
    vendor = hba_info.get("vendor", "") or ""

    # 按驱动名查找（支持变体部分匹配）
    for known_drv, types in _HBA_DRIVER_DEVICE_TYPES.items():
        if driver == known_drv or driver.startswith(known_drv):
            return types

    # 基于传输类型的启发式判断
    if transport == "usb":
        return ["", "sat", "usbjmicron", "usbprolific", "usbsunplus"]

    # 未知驱动 — 使用安全的通用列表
    return _GENERIC_DEVICE_TYPES


# ======================== sysfs 磁盘温度 ========================

def _read_disk_temp_from_sysfs(dev_name: str) -> Optional[float]:
    """尝试通过 sysfs hwmon 读取磁盘温度（不需要 smartctl）。

    查找路径：
      1. /sys/block/<dev>/device/hwmon/hwmon*/temp*_input
      2. /sys/block/<dev>/device/hwmon/hwmon*/name（nvme 类型）
    返回摄氏度温度或 None。
    """
    device_base = os.path.join(BLOCK_BASE, dev_name, "device")
    hwmon_dir = os.path.join(device_base, "hwmon")

    if not os.path.isdir(hwmon_dir):
        # 部分 NVMe 在 /sys/class/nvme/<dev>/hwmon* 下暴露
        nvme_base = os.path.join(SYSFS_BASE, "class", "nvme", dev_name, "hwmon")
        if os.path.isdir(nvme_base):
            hwmon_dir = nvme_base
        else:
            return None

    try:
        for hwmon_name in sorted(os.listdir(hwmon_dir)):
            hwmon_path = os.path.join(hwmon_dir, hwmon_name)
            if not os.path.isdir(hwmon_path):
                continue
            # 扫描 temp*_input
            for entry in sorted(os.listdir(hwmon_path)):
                m = re.match(r"^temp(\d+)_input$", entry)
                if m:
                    val = _read_sysfs_int(os.path.join(hwmon_path, entry))
                    if val is not None:
                        return val / 1000.0  # millidegrees → Celsius
    except OSError:
        pass

    return None


def _read_disk_model_serial_from_sysfs(dev_name: str) -> tuple[str, str]:
    """从 sysfs 读取型号和序列号。返回 (model, serial)。"""
    device_base = os.path.join(BLOCK_BASE, dev_name, "device")

    model = (_read_sysfs(os.path.join(device_base, "model")) or "").strip()
    serial = (_read_sysfs(os.path.join(device_base, "serial")) or "").strip()

    # 型号可能是空格分隔的多词，规范化
    if model:
        model = " ".join(model.split())
    if serial:
        serial = serial.strip()

    return model, serial


def _read_disk_rotational(dev_name: str) -> bool:
    """检查块设备是否为机械盘（HDD）。
    HDD 返回 True，SSD/未知 返回 False。
    """
    val = _read_sysfs(os.path.join(BLOCK_BASE, dev_name, "queue", "rotational"))
    return val == "1"


def _read_disk_size_bytes(dev_name: str) -> int:
    """从 sysfs 读取块设备大小（字节）。"""
    val = _read_sysfs_int(os.path.join(BLOCK_BASE, dev_name, "size"))
    if val:
        return val * 512  # sysfs 以 512 字节扇区为单位
    return 0


# ======================== 主扫描器 ========================

class SensorScanner:
    """扫描系统中所有可用的硬件传感器。"""

    def __init__(self, smartctl_path: str = "", enable_smartctl: bool = True):
        # 自动检测 smartctl：先用提供的路径，不行再自动搜索
        if enable_smartctl:
            if smartctl_path and os.path.isfile(smartctl_path):
                pass  # Use provided path
            else:
                if smartctl_path:
                    logger.info(f"smartctl not at {smartctl_path}, auto-detecting...")
                found = _find_smartctl()
                if found:
                    smartctl_path = found
                else:
                    smartctl_path = ""
        else:
            smartctl_path = ""

        self.smartctl_path = smartctl_path
        self.enable_smartctl = bool(smartctl_path and enable_smartctl)
        self.hwmon_devices: list[HwmonDevice] = []
        self.disks: list[DiskInfo] = []

        if self.smartctl_path:
            logger.info(f"smartctl found at: {self.smartctl_path}")
        else:
            logger.info("smartctl not found; will rely on sysfs for disk temperatures")

    # ---- sysfs 辅助（实例方法，保持一致的 SYSFS_BASE）----

    def _sysfs_str(self, path: str) -> Optional[str]:
        return _read_sysfs(path)

    def _sysfs_int(self, path: str) -> Optional[int]:
        return _read_sysfs_int(path)

    def _write_file(self, path: str, value: str) -> bool:
        try:
            with open(path, "w") as f:
                f.write(str(value))
            return True
        except (FileNotFoundError, PermissionError, OSError) as e:
            logger.warning(f"Failed to write {path}: {e}")
            return False

    # =================== hwmon 扫描 ===================

    def scan_hwmon(self) -> list[HwmonDevice]:
        """扫描 /sys/class/hwmon 下所有设备及其传感器。"""
        self.hwmon_devices.clear()

        if not os.path.isdir(HWMON_BASE):
            logger.warning(f"{HWMON_BASE} does not exist — not on Linux?")
            return []

        for hwmon_name in sorted(os.listdir(HWMON_BASE)):
            hwmon_path = os.path.join(HWMON_BASE, hwmon_name)
            if not os.path.isdir(hwmon_path):
                continue

            name = self._sysfs_str(os.path.join(hwmon_path, "name")) or hwmon_name
            device_link = os.path.join(hwmon_path, "device")
            device_path = os.path.realpath(device_link) if os.path.exists(device_link) else ""

            device = HwmonDevice(hwmon_path=hwmon_path, name=name, device_path=device_path)

            # 温度传感器
            for entry in sorted(os.listdir(hwmon_path)):
                m = re.match(r"^temp(\d+)_input$", entry)
                if m:
                    channel = int(m.group(1))
                    label = self._sysfs_str(os.path.join(hwmon_path, f"temp{channel}_label")) or ""
                    device.temperatures.append(SensorInfo(
                        name=translate_sensor_name(name, channel, label, "temperature"),
                        sensor_type="temperature", source="hwmon",
                        hwmon_path=hwmon_path, channel=channel,
                        label=label, unit="C", raw_name=name, dev_path=device_path,
                    ))

            # 风扇转速传感器
            for entry in sorted(os.listdir(hwmon_path)):
                m = re.match(r"^fan(\d+)_input$", entry)
                if m:
                    channel = int(m.group(1))
                    label = self._sysfs_str(os.path.join(hwmon_path, f"fan{channel}_label")) or ""
                    device.fan_rpms.append(SensorInfo(
                        name=translate_sensor_name(name, channel, label, "fan_rpm"),
                        sensor_type="fan_rpm", source="hwmon",
                        hwmon_path=hwmon_path, channel=channel,
                        label=label, unit="RPM", raw_name=name, dev_path=device_path,
                    ))

            # PWM 控制器
            for entry in sorted(os.listdir(hwmon_path)):
                m = re.match(r"^pwm(\d+)$", entry)
                if m:
                    channel = int(m.group(1))
                    device.fan_pwms.append(SensorInfo(
                        name=translate_sensor_name(name, channel, "", "fan_pwm"),
                        sensor_type="fan_pwm", source="hwmon",
                        hwmon_path=hwmon_path, channel=channel,
                        unit="%", raw_name=name, dev_path=device_path,
                    ))

            if device.temperatures or device.fan_rpms or device.fan_pwms:
                self.hwmon_devices.append(device)
                logger.info(
                    f"Found hwmon device: {name} "
                    f"({len(device.temperatures)} temps, "
                    f"{len(device.fan_rpms)} fans, "
                    f"{len(device.fan_pwms)} pwms)"
                )

        return self.hwmon_devices

    # =================== 磁盘扫描 ===================

    async def scan_disks(self) -> list[DiskInfo]:
        """扫描所有物理块设备的温度。

        策略（每个设备）：
          1. 先试 sysfs hwmon 温度（快，不需要 smartctl）。
          2. 读不到则用 smartctl（自动检测 HBA 参数）。

        跳过虚拟设备（loop, dm, md, ram, zram, nbd, sr, pmem）。
        """
        self.disks.clear()

        if not os.path.isdir(BLOCK_BASE):
            logger.warning(f"{BLOCK_BASE} does not exist")
            return []

        # 收集物理块设备
        physical_devs: list[str] = []
        for dev_name in sorted(os.listdir(BLOCK_BASE)):
            if _is_virtual_block_device(dev_name):
                continue
            # 检查是否有真实设备支撑（虚拟块设备无 /sys/block/X/device）
            device_dir = os.path.join(BLOCK_BASE, dev_name, "device")
            if not os.path.exists(device_dir):
                continue
            physical_devs.append(dev_name)

        logger.info(f"Found {len(physical_devs)} physical block devices: {physical_devs}")

        # 逐一处理 — 部分通过 sysfs，部分通过 smartctl
        # 收集 smartctl 任务，稍后并行执行
        smartctl_tasks: list[tuple[str, str, bool, dict]] = []

        for dev_name in physical_devs:
            dev_path = f"{DEV_BASE}/{dev_name}"
            is_nvme = dev_name.startswith("nvme")

            # 第一步：尝试 sysfs 温度
            sysfs_temp = _read_disk_temp_from_sysfs(dev_name)
            model, serial = _read_disk_model_serial_from_sysfs(dev_name)

            if sysfs_temp is not None and sysfs_temp > 0:
                disk = DiskInfo(
                    device=dev_path, dev_name=dev_name,
                    model=model, serial=serial,
                    temperature=float(sysfs_temp),
                    is_nvme=is_nvme, temp_source="sysfs",
                    smart_available=bool(self.smartctl_path),
                )
                self.disks.append(disk)
                logger.info(f"Disk {dev_path} [sysfs]: {model} - {sysfs_temp:.1f}C")
                continue

            # 第二步：需要 smartctl
            if not self.smartctl_path:
                # 即使没有温度也记录磁盘（至少显示其存在）
                if model:
                    disk = DiskInfo(
                        device=dev_path, dev_name=dev_name,
                        model=model, serial=serial,
                        temperature=0.0, is_nvme=is_nvme,
                        smart_available=False, temp_source="none",
                    )
                    self.disks.append(disk)
                    logger.info(f"Disk {dev_path}: {model} — no temp (no smartctl)")
                continue

            hba_info = _load_hba_info(dev_name)
            smartctl_tasks.append((dev_name, dev_path, is_nvme, hba_info))

        # 并行执行 smartctl 查询（分批，每批=并发上限）
        if smartctl_tasks:
            concurrency = min(len(smartctl_tasks), 8)  # 最多 8 个并发
            semaphore = asyncio.Semaphore(concurrency)

            async def _query_one(dev_name: str, dev_path: str, is_nvme: bool,
                                  hba_info: dict) -> Optional[DiskInfo]:
                async with semaphore:
                    return await self._smartctl_query_disk(
                        dev_name, dev_path, is_nvme, hba_info
                    )

            results = await asyncio.gather(*[
                _query_one(dn, dp, nv, hi) for dn, dp, nv, hi in smartctl_tasks
            ])

            for disk in results:
                if disk is not None:
                    self.disks.append(disk)

        # 按设备名排序，保持输出一致
        self.disks.sort(key=lambda d: d.dev_name)
        return self.disks

    async def _smartctl_query_disk(
        self, dev_name: str, dev_path: str, is_nvme: bool, hba_info: dict
    ) -> Optional[DiskInfo]:
        """查询单个磁盘（smartctl），尝试推荐的设备类型。"""
        device_types = _get_smartctl_device_types(hba_info)

        model, serial = _read_disk_model_serial_from_sysfs(dev_name)

        for dev_type in device_types:
            try:
                cmd = [self.smartctl_path]
                if dev_type:
                    cmd.extend(["-d", dev_type])
                cmd.extend(["-A", "-j", dev_path])

                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await proc.communicate()

                json_str = stdout.decode("utf-8", errors="replace").strip()
                if not json_str or json_str == "null":
                    continue

                data = json.loads(json_str)

                # 如果 sysfs 没有型号/序列号，从 smartctl 输出提取
                smart_model = data.get("model_name", "") or data.get("product", "") or ""
                smart_serial = data.get("serial_number", "") or ""
                if not model:
                    model = smart_model
                if not serial:
                    serial = smart_serial

                # 没有任何有意义数据则跳过
                has_attrs = bool(data.get("ata_smart_attributes"))
                has_temp = bool(data.get("temperature"))
                if not smart_model and not model and not has_attrs and not has_temp:
                    continue

                # 提取温度
                temp_val = 0

                if is_nvme:
                    temp_data = data.get("temperature", {})
                    temp_val = temp_data.get("current", 0)
                else:
                    temp_val = self._parse_sata_temp(data)

                # Log success
                if temp_val > 0:
                    logger.info(
                        f"Disk {dev_path} [smartctl -d {dev_type or 'auto'}]: "
                        f"{model or smart_model} - {temp_val}C"
                    )
                else:
                    logger.info(
                        f"Disk {dev_path} [smartctl -d {dev_type or 'auto'}]: "
                        f"{model or smart_model} — identified but no temp read"
                    )

                return DiskInfo(
                    device=dev_path, dev_name=dev_name,
                    model=model or smart_model,
                    serial=serial or smart_serial,
                    temperature=float(temp_val),
                    is_nvme=is_nvme,
                    smart_available=True,
                    temp_source="smartctl" if temp_val > 0 else "none",
                )

            except json.JSONDecodeError:
                continue
            except Exception as e:
                logger.debug(f"smartctl -d {dev_type or 'auto'} on {dev_path}: {e}")
                continue

        # 所有类型都失败了 — 有型号名的话仍然记录该磁盘
        if model:
            return DiskInfo(
                device=dev_path, dev_name=dev_name,
                model=model, serial=serial,
                temperature=0.0, is_nvme=is_nvme,
                smart_available=False, temp_source="none",
            )

        return None

    def _parse_sata_temp(self, data: dict) -> int:
        """从 SATA/SAS smartctl -A -j JSON 输出中提取温度。

        兼容不同厂商的 ATA 属性格式
        （希捷、西数、日立、东芝、三星等）。
        """
        attributes = data.get("ata_smart_attributes", {}).get("table", [])
        for attr in attributes:
            attr_id = attr.get("id", 0)
            attr_name = attr.get("name", "")

            # 标准温度属性：194, 190, 231
            is_temp_attr = (
                attr_id in (190, 194, 231) or
                "Temperature" in attr_name or
                "temperature" in attr_name.lower()
            )
            if not is_temp_attr:
                continue

            # --- 方法 1：归一化值（大部分盘直接就是摄氏度）---
            norm_val = attr.get("value", 0)
            if isinstance(norm_val, (int, float)) and 0 < norm_val <= 200:
                return int(norm_val)

            # --- 方法 2：raw value 字典 ---
            raw = attr.get("raw", {})
            if isinstance(raw, dict):
                # 'value' 字段（整数）
                raw_int = raw.get("value", 0)
                if isinstance(raw_int, int) and 0 < raw_int <= 200:
                    return raw_int
                # 'string' 字段：常见格式 "45" 或 "45 (Min/Max 30/60)"
                raw_str = raw.get("string", "")
                if raw_str:
                    m = re.match(r"^(\d+)", raw_str.strip())
                    if m:
                        parsed = int(m.group(1))
                        if 0 < parsed <= 200:
                            return parsed
            elif isinstance(raw, (int, float)):
                if 0 < raw <= 200:
                    return int(raw)

            # 找到了温度属性但无法解析 — 停止查找
            break

        # --- Method 3: top-level temperature field (SAS drives, some NVMe) ---
        temp_data = data.get("temperature", {})
        if temp_data:
            if isinstance(temp_data, (int, float)):
                if 0 < temp_data <= 200:
                    return int(temp_data)
            if isinstance(temp_data, dict):
                current = temp_data.get("current", 0)
                if isinstance(current, (int, float)) and 0 < current <= 200:
                    return int(current)

        # --- Method 4: SCSI/SAS temperature log pages ---
        scsi_temp = data.get("current_temperature")
        if scsi_temp is not None:
            try:
                t = int(scsi_temp)
                if 0 < t <= 200:
                    return t
            except (ValueError, TypeError):
                pass

        return 0

    # =================== 传感器读取 ===================

    def read_temperature(self, sensor: SensorInfo) -> float:
        val = self._sysfs_int(os.path.join(sensor.hwmon_path, f"temp{sensor.channel}_input"))
        return (val / 1000.0) if val is not None else 0.0

    def read_fan_rpm(self, sensor: SensorInfo) -> int:
        return self._sysfs_int(os.path.join(sensor.hwmon_path, f"fan{sensor.channel}_input")) or 0

    def read_pwm(self, sensor: SensorInfo) -> int:
        return self._sysfs_int(os.path.join(sensor.hwmon_path, f"pwm{sensor.channel}")) or 0

    # =================== 风扇控制 ===================

    def write_pwm(self, hwmon_path: str, channel: int, value: int) -> bool:
        value = max(0, min(255, int(value)))
        return self._write_file(os.path.join(hwmon_path, f"pwm{channel}"), str(value))

    def set_fan_mode(self, hwmon_path: str, channel: int, mode: int) -> bool:
        """设置风扇模式。mode: 0=全速, 1=手动(PWM), 2=自动, 3=禁用。"""
        enable_path = os.path.join(hwmon_path, f"pwm{channel}_enable")
        if self._write_file(enable_path, str(mode)):
            return True
        mode_path = os.path.join(hwmon_path, f"pwm{channel}_mode")
        return self._write_file(mode_path, str(mode))

    def get_fan_mode(self, hwmon_path: str, channel: int) -> Optional[int]:
        val = self._sysfs_int(os.path.join(hwmon_path, f"pwm{channel}_enable"))
        if val is not None:
            return val
        return self._sysfs_int(os.path.join(hwmon_path, f"pwm{channel}_mode"))

    # =================== 批量读取 ===================

    def get_all_temperatures(self) -> dict[str, float]:
        result: dict[str, float] = {}
        for dev in self.hwmon_devices:
            for sensor in dev.temperatures:
                val = self.read_temperature(sensor)
                sensor.current_value = val
                result[sensor.name] = val
        for disk in self.disks:
            label = f"硬盘 {disk.model or disk.dev_name}"
            result[label] = disk.temperature
        return result

    def get_all_fan_rpms(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for dev in self.hwmon_devices:
            for sensor in dev.fan_rpms:
                rpm = self.read_fan_rpm(sensor)
                sensor.current_value = rpm
                result[sensor.name] = rpm
        return result

    def get_all_pwms(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for dev in self.hwmon_devices:
            for sensor in dev.fan_pwms:
                pwm = self.read_pwm(sensor)
                sensor.current_value = pwm
                result[sensor.name] = pwm
        return result

    # =================== 序列化 ===================

    def to_dict(self) -> dict:
        return {
            "hwmon_devices": [
                {
                    "name": dev.name,
                    "hwmon_path": dev.hwmon_path,
                    "device_path": dev.device_path,
                    "temperatures": [
                        {"name": s.name, "label": s.label, "channel": s.channel,
                         "current_value": s.current_value, "unit": s.unit}
                        for s in dev.temperatures
                    ],
                    "fan_rpms": [
                        {"name": s.name, "label": s.label, "channel": s.channel,
                         "current_value": s.current_value, "unit": s.unit}
                        for s in dev.fan_rpms
                    ],
                    "fan_pwms": [
                        {"name": s.name, "channel": s.channel,
                         "current_value": s.current_value, "unit": s.unit}
                        for s in dev.fan_pwms
                    ],
                }
                for dev in self.hwmon_devices
            ],
            "disks": [
                {
                    "device": d.device,
                    "dev_name": d.dev_name,
                    "model": d.model,
                    "display_name": f"{d.model or d.dev_name}",
                    "temperature": d.temperature,
                    "is_nvme": d.is_nvme,
                    "temp_source": d.temp_source,
                }
                for d in self.disks
            ],
        }

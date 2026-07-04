#!/bin/bash
#
# FNOS Fan Controller - Installation Script
# For FNOS (飞牛OS) / Debian-based Linux NAS systems
#
# Usage: sudo bash install.sh
#

set -e

APP_NAME="fnos-fan-control"
INSTALL_DIR="/opt/$APP_NAME"
SERVICE_FILE="/etc/systemd/system/$APP_NAME.service"
CONFIG_DIR="/etc/$APP_NAME"
VENV_DIR="/opt/$APP_NAME/venv"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}========================================${NC}"
echo -e "${CYAN}  FNOS Fan Controller Installer${NC}"
echo -e "${CYAN}========================================${NC}"
echo ""

# Check root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Error: Please run as root (use sudo)${NC}"
    exit 1
fi

# Check Python
echo -e "${YELLOW}Step 1: Checking Python...${NC}"
if command -v python3 &>/dev/null; then
    PYTHON_VERSION=$(python3 --version 2>&1)
    echo -e "  Found: ${PYTHON_VERSION}"
else
    echo -e "${RED}  Python3 not found. Installing...${NC}"
    apt-get update
    apt-get install -y python3 python3-venv python3-pip
fi

# Install system dependencies
echo -e "${YELLOW}Step 2: Installing system dependencies...${NC}"
apt-get update -qq
apt-get install -y -qq smartmontools curl >/dev/null 2>&1 || {
    echo -e "${YELLOW}  Warning: Some packages may not be available${NC}"
}
echo -e "  Done"

# Create directories
echo -e "${YELLOW}Step 3: Creating directories...${NC}"
mkdir -p "$INSTALL_DIR" "$CONFIG_DIR"
echo -e "  $INSTALL_DIR"
echo -e "  $CONFIG_DIR"

# Copy files
echo -e "${YELLOW}Step 4: Copying application files...${NC}"
cp -r "$PROJECT_DIR/backend/"* "$INSTALL_DIR/"
cp -r "$PROJECT_DIR/frontend/" "$INSTALL_DIR/frontend/"
echo -e "  Done"

# Create virtual environment
echo -e "${YELLOW}Step 5: Creating Python virtual environment...${NC}"
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip -q
"$VENV_DIR/bin/pip" install -r "$INSTALL_DIR/requirements.txt" -q
echo -e "  Done"

# Create default config
echo -e "${YELLOW}Step 6: Creating configuration...${NC}"
if [ ! -f "$CONFIG_DIR/config.json" ]; then
    cat > "$CONFIG_DIR/config.json" << 'EOF'
{
    "update_interval": 2,
    "data_history_length": 300,
    "enable_smartctl": true,
    "smartctl_path": "/usr/sbin/smartctl",
    "web_port": 8070,
    "fans": [],
    "auto_detect": true,
    "log_level": "INFO",
    "enable_alerts": false,
    "alert_temp_cpu": 85.0,
    "alert_temp_disk": 60.0
}
EOF
    echo -e "  Created default config at $CONFIG_DIR/config.json"
else
    echo -e "  Config already exists, keeping existing configuration"
fi

# Create systemd service
echo -e "${YELLOW}Step 7: Creating systemd service...${NC}"
cat > "$SERVICE_FILE" << EOF
[Unit]
Description=FNOS Fan Controller
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
ExecStart=$VENV_DIR/bin/python main.py
Environment=FNOS_FAN_CONFIG=$CONFIG_DIR/config.json
Environment=PYTHONUNBUFFERED=1
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=$APP_NAME

[Install]
WantedBy=multi-user.target
EOF
echo -e "  Service created at $SERVICE_FILE"

# Reload and enable
echo -e "${YELLOW}Step 8: Enabling service...${NC}"
systemctl daemon-reload
systemctl enable "$APP_NAME"
echo -e "  Service enabled"

# Start service
echo -e "${YELLOW}Step 9: Starting service...${NC}"
systemctl restart "$APP_NAME"
sleep 2

# Check status
if systemctl is-active --quiet "$APP_NAME"; then
    echo -e "${GREEN}  Service is running!${NC}"
else
    echo -e "${RED}  Service failed to start. Check logs:${NC}"
    echo -e "  journalctl -u $APP_NAME -f"
    exit 1
fi

# Get IP
IP_ADDR=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Installation Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "  Web UI:  ${CYAN}http://$IP_ADDR:8070${NC}"
echo -e "  Config:  $CONFIG_DIR/config.json"
echo -e "  Logs:    journalctl -u $APP_NAME -f"
echo -e "  Status:  systemctl status $APP_NAME"
echo -e "  Stop:    systemctl stop $APP_NAME"
echo -e "  Restart: systemctl restart $APP_NAME"
echo ""
echo -e "${YELLOW}Note: PWM fan control requires root access.${NC}"
echo -e "${YELLOW}      The service runs as root by default.${NC}"
echo ""

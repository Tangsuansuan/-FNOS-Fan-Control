#!/bin/bash
set -e

# ============================================================
# FNOS Fan Controller - FPK Build Script (Non-Docker)
# Creates a .fpk package for fnOS application installation
# ============================================================
#
# Usage:
#   bash build-fpk.sh [x86|arm]
#
# Output:
#   dist/fnos-fan-control_1.1.0_x86.fpk
# ============================================================

# Determine paths
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
FPK_SRC="$SCRIPT_DIR"
BACKEND_SRC="$PROJECT_ROOT/backend"
FRONTEND_SRC="$PROJECT_ROOT/frontend"

# Read version from manifest
VERSION=$(grep '^version' "$FPK_SRC/manifest" | awk -F'=' '{print $2}' | tr -d '"' | tr -d ' ')
APPNAME=$(grep '^appname' "$FPK_SRC/manifest" | awk -F'=' '{print $2}' | tr -d '"' | tr -d ' ')

if [ -z "$VERSION" ]; then
    VERSION="1.0.0"
fi
if [ -z "$APPNAME" ]; then
    APPNAME="fnos-fan-control"
fi

PLATFORM="${1:-x86}"
case "$PLATFORM" in
    x86|x86_64|amd64)  PLATFORM="x86" ;;
    arm|arm64|aarch64)  PLATFORM="arm" ;;
    *) error "Unknown platform: $PLATFORM (use x86 or arm)" ;;
esac
FPK_NAME="${APPNAME}_${VERSION}_${PLATFORM}.fpk"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

echo -e "${CYAN}========================================${NC}"
echo -e "${CYAN}  FPK Build Script (Non-Docker)${NC}"
echo -e "${CYAN}  App: $APPNAME v$VERSION ($PLATFORM)${NC}"
echo -e "${CYAN}========================================${NC}"
echo ""

# Step 1: Verify source files exist
info "Step 1: Verifying source files..."

[ -f "$FPK_SRC/manifest" ]         || error "manifest not found"
[ -f "$FPK_SRC/ICON.PNG" ]         || error "ICON.PNG not found (run generate_icons.py first)"
[ -f "$FPK_SRC/ICON_256.PNG" ]    || error "ICON_256.PNG not found (run generate_icons.py first)"
[ -f "$FPK_SRC/cmd/main" ]        || error "cmd/main not found"
[ -f "$FPK_SRC/cmd/install_init" ] || error "cmd/install_init not found"
[ -f "$FPK_SRC/config/privilege" ] || error "config/privilege not found"
[ -f "$FPK_SRC/config/resource" ]  || error "config/resource not found"
[ -f "$FPK_SRC/ui/config" ]       || error "ui/config not found"
[ -f "$FPK_SRC/health.json" ]     || error "health.json not found"

info "  All source files verified"

# Step 2: Copy application code into app/ directory
info "Step 2: Copying application code into app/..."

APP_DIR="$FPK_SRC/app"
mkdir -p "$APP_DIR"

# Copy backend (exclude __pycache__, .pyc)
if [ -d "$BACKEND_SRC" ]; then
    rm -rf "$APP_DIR/backend"
    mkdir -p "$APP_DIR/backend"
    cp -r "$BACKEND_SRC"/* "$APP_DIR/backend/"
    # Clean up Python cache
    find "$APP_DIR/backend" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find "$APP_DIR/backend" -name "*.pyc" -delete 2>/dev/null || true
    info "  Backend code copied"
else
    error "Backend source not found: $BACKEND_SRC"
fi

# Copy frontend
if [ -d "$FRONTEND_SRC" ]; then
    rm -rf "$APP_DIR/frontend"
    cp -r "$FRONTEND_SRC" "$APP_DIR/frontend"
    info "  Frontend code copied"
else
    error "Frontend source not found: $FRONTEND_SRC"
fi

# Copy ui/ into app.tgz (fnOS may need it there for desktop entry)
if [ -d "$FPK_SRC/ui" ]; then
    rm -rf "$APP_DIR/ui"
    cp -r "$FPK_SRC/ui" "$APP_DIR/ui"
    info "  UI config & icons copied into app"
fi

# Step 3: Create temporary build directory
info "Step 3: Assembling FPK package..."

WORK_DIR="$(cd "$SCRIPT_DIR" && pwd)/.build-tmp"
rm -rf "$WORK_DIR"
PKG_DIR="$WORK_DIR/package"
mkdir -p "$PKG_DIR"

# Step 4: Create app.tgz from app/ directory
info "Step 4: Creating app.tgz..."
( cd "$APP_DIR" && tar -czf "$PKG_DIR/app.tgz" . )
APP_TGZ_SIZE=$(wc -c < "$PKG_DIR/app.tgz")
info "  app.tgz created ($APP_TGZ_SIZE bytes)"

# Step 5: Copy files to package directory
info "Step 5: Copying package files..."

# manifest
cp "$FPK_SRC/manifest" "$PKG_DIR/manifest"

# cmd/ scripts
cp -r "$FPK_SRC/cmd" "$PKG_DIR/cmd"
chmod +x "$PKG_DIR/cmd/"* 2>/dev/null || true

# config/
cp -r "$FPK_SRC/config" "$PKG_DIR/config"

# ui/
cp -r "$FPK_SRC/ui" "$PKG_DIR/ui"

# Icons
cp "$FPK_SRC/ICON.PNG" "$PKG_DIR/ICON.PNG"
cp "$FPK_SRC/ICON_256.PNG" "$PKG_DIR/ICON_256.PNG"

# health.json
cp "$FPK_SRC/health.json" "$PKG_DIR/health.json"

# Step 6: Verify package contents
info "Step 6: Verifying package contents..."
for f in manifest app.tgz ICON.PNG ICON_256.PNG health.json; do
    [ -f "$PKG_DIR/$f" ] || error "Missing in package: $f"
done
for d in cmd config ui; do
    [ -d "$PKG_DIR/$d" ] || error "Missing directory in package: $d"
done
info "  Package verified"

# Step 7: Create .fpk file
info "Step 7: Creating .fpk file..."

DIST_DIR="$PROJECT_ROOT/dist"
mkdir -p "$DIST_DIR"

( cd "$PKG_DIR" && tar -czf "$DIST_DIR/$FPK_NAME" . )

FPK_SIZE=$(wc -c < "$DIST_DIR/$FPK_NAME" 2>/dev/null || stat -c%s "$DIST_DIR/$FPK_NAME" 2>/dev/null || echo "?")

# Cleanup
rm -rf "$WORK_DIR"

# Clean up app context (remove copied source files)
rm -rf "$APP_DIR/backend" "$APP_DIR/frontend" "$APP_DIR/ui"

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Build Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "  Output: ${CYAN}$DIST_DIR/$FPK_NAME${NC}"
echo -e "  Size:   ${CYAN}${FPK_SIZE} bytes${NC}"
echo ""
echo -e "${YELLOW}Installation:${NC}"
echo -e "  1. Upload $FPK_NAME to your fnOS device"
echo -e "  2. Open fnOS App Center (应用中心)"
echo -e "  3. Click 'Manual Install' (手动安装) at bottom-left"
echo -e "  4. Select the .fpk file and install"
echo ""
echo -e "${YELLOW}Or via SSH:${NC}"
echo -e "  scp $FPK_NAME root@<nas-ip>:/tmp/"
echo -e "  ssh root@<nas-ip> 'appcenter-cli install-fpk /tmp/$FPK_NAME'"
echo ""

# Also output the path for scripting
echo "$DIST_DIR/$FPK_NAME"

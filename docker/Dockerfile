# Use debian slim base (more reliable than python:xxx-slim on Chinese mirrors)
FROM debian:bookworm-slim AS base

LABEL maintainer="FNOS Fan Controller"
LABEL description="Fan control and temperature monitoring for FNOS (飞牛OS)"

# Configure apt to use Aliyun mirror for faster downloads in China
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list 2>/dev/null || true

# Install Python 3 and system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    smartmontools \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3 /usr/bin/python \
    && ln -sf /usr/bin/pip3 /usr/bin/pip

# Configure pip to use Tsinghua mirror
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple \
    && pip config set global.trusted-host pypi.tuna.tsinghua.edu.cn

# Set working directory
WORKDIR /app

# Copy requirements and install
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY backend/ .

# Copy frontend
COPY frontend/ /app/frontend

# Create config directory
RUN mkdir -p /etc/fnos-fan-control /app/config

# Expose web port
EXPOSE 8070

# Environment variables
ENV FNOS_FAN_CONFIG=/etc/fnos-fan-control/config.json
ENV FNOS_FAN_PORT=8070
ENV PYTHONUNBUFFERED=1
ENV SYSFS_PATH=/host/sys
ENV DEV_PATH=/dev

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8070/api/status')" || exit 1

# Run the application
CMD ["python", "main.py"]

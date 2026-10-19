#!/usr/bin/env bash
# Ubuntu 24.04; run as root after extracting the source archive to /opt/roblox-trend-monitor.
set -euo pipefail
APP=/opt/roblox-trend-monitor
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3-venv python3-pip nginx
if ! id roblox-monitor >/dev/null 2>&1; then
    useradd --system --home-dir /var/lib/roblox-trend-monitor --shell /usr/sbin/nologin roblox-monitor
fi
install -d -o roblox-monitor -g roblox-monitor -m 0750 /var/lib/roblox-trend-monitor
if [ -f /var/lib/roblox-trend-monitor/market.sqlite ]; then
    chown roblox-monitor:roblox-monitor /var/lib/roblox-trend-monitor/market.sqlite
    chmod 0640 /var/lib/roblox-trend-monitor/market.sqlite
fi
install -d -o roblox-monitor -g roblox-monitor -m 0750 "$APP/data" "$APP/reports"
python3 -m venv "$APP/.venv"
"$APP/.venv/bin/python" -m pip install --disable-pip-version-check -r "$APP/requirements-lock.txt"
if [ ! -f /etc/roblox-trend-monitor.env ]; then
    printf '%s\n' 'RTM_DATABASE=/var/lib/roblox-trend-monitor/market.sqlite' 'RTM_TARGET_GAMES=400' 'RTM_REQUEST_INTERVAL=0.6' 'RTM_DISCOVERY_COUNTRY=all' 'RTM_DISCOVERY_DEVICE=computer' > /etc/roblox-trend-monitor.env
    chmod 0644 /etc/roblox-trend-monitor.env
fi
install -m 0644 "$APP/deploy/roblox-dashboard.service" /etc/systemd/system/roblox-dashboard.service
install -m 0644 "$APP/deploy/roblox-collector.service" /etc/systemd/system/roblox-collector.service
install -m 0644 "$APP/deploy/nginx.conf" /etc/nginx/sites-available/roblox-trend-monitor
ln -sfn /etc/nginx/sites-available/roblox-trend-monitor /etc/nginx/sites-enabled/roblox-trend-monitor
nginx -t
systemctl daemon-reload
systemctl enable --now roblox-dashboard roblox-collector nginx
systemctl reload nginx

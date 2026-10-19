# Ubuntu 24.04 VPS deployment

The dashboard and hourly collector run as separate systemd services under the unprivileged `roblox-monitor` account. Nginx proxies HTTP/WebSockets to Streamlit on loopback. Both application services start after reboot and restart on process failure.

- Application: `/opt/roblox-trend-monitor`
- Persistent SQLite: `/var/lib/roblox-trend-monitor/market.sqlite`
- Environment: `/etc/roblox-trend-monitor.env`
- Reports: `/opt/roblox-trend-monitor/reports`
- Collector log: `/opt/roblox-trend-monitor/data/collector.log`
- Initial URL: `http://212.227.231.84`

The initial IP endpoint exposes only the public-data dashboard. For a chosen domain, update `server_name`, point DNS to the VPS, and configure HTTPS at the reverse proxy. Authentication can then be added for private access.

Source transfer uses `git archive`, excluding local databases, credentials, SSH keys and virtual environments. Existing SQLite history is transferred separately with SQLite's online backup API and only seeded if no server database exists.

Useful commands on the VPS:

```bash
systemctl status roblox-dashboard roblox-collector --no-pager
journalctl -u roblox-collector -n 50 --no-pager
journalctl -u roblox-dashboard -n 50 --no-pager
systemctl restart roblox-dashboard
systemctl restart roblox-collector
curl http://127.0.0.1:8501/_stcore/health
```

Closing SSH or turning off the Windows PC does not stop server collection. Use the VPS collector as the primary source of new history; the local collector uses a separate database and does not synchronize automatically. Stop the local collector with Ctrl+C to avoid maintaining two independent histories.

For future updates, replace source files without touching `/var/lib/roblox-trend-monitor`, update dependencies as needed and restart both services. Back up the live SQLite database with SQLite's backup API before migrations. Never copy only a live `.sqlite` file while ignoring its WAL.

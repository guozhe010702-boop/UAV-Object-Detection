#!/usr/bin/env bash
set -Eeuo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
[[ "$EUID" == 0 ]] || { echo 'Run as root to install the dedicated systemd service'; exit 1; }
[[ "$root" == /userdata/uav-object-detection ]] || { echo 'Deploy to /userdata/uav-object-detection first'; exit 1; }
[[ -x "$root/.venv/bin/python" && -f "$root/frontend/dist/index.html" ]] || { echo 'Prepare the private environment and frontend first'; exit 1; }
id uav-web >/dev/null 2>&1 || useradd --system --home-dir "$root" --no-create-home --shell /usr/sbin/nologin uav-web
mkdir -p "$root/data"
chown -R uav-web:uav-web "$root/data"
chmod 700 "$root/data"
cat > /etc/systemd/system/uav-object-detection.service <<EOF
[Unit]
Description=UAV local web console (inference not connected)
After=network.target

[Service]
Type=simple
User=uav-web
Group=uav-web
WorkingDirectory=$root/backend
Environment=PYTHONPATH=$root/backend
Environment=UAV_DATA_DIR=$root/data
ExecStart=$root/.venv/bin/python -m uav_app.cli serve --host 0.0.0.0 --port 8088
Restart=on-failure
RestartSec=3
TimeoutStopSec=15
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
UMask=0077
ReadWritePaths=$root/data

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
# Import the binary and metadata as data; no RKNN runtime is imported or executed.
if [[ -f "$root/model-bundle/manifest.json" ]]; then
    runuser -u uav-web -- env "PYTHONPATH=$root/backend" "UAV_DATA_DIR=$root/data" \
        "$root/.venv/bin/python" -m uav_app.cli import-model --bundle "$root/model-bundle"
fi
systemctl enable --now uav-object-detection.service
echo 'Web service enabled. It does not open a camera or initialize the NPU.'

#!/usr/bin/env bash
set -Eeuo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
[[ "$EUID" == 0 ]] || { echo 'Run as root to install the dedicated systemd service'; exit 1; }
[[ "$root" == /userdata/uav-object-detection ]] || { echo 'Deploy to /userdata/uav-object-detection first'; exit 1; }
[[ -x "$root/.venv/bin/python" && -f "$root/frontend/dist/index.html" ]] || { echo 'Prepare the private environment and frontend first'; exit 1; }
id uav-web >/dev/null 2>&1 || useradd --system --home-dir "$root" --no-create-home --shell /usr/sbin/nologin uav-web
for group in video render; do
    if getent group "$group" >/dev/null; then usermod -aG "$group" uav-web; fi
done
mkdir -p "$root/data"
chown -R uav-web:uav-web "$root/data"
chmod 700 "$root/data"
cat > /etc/systemd/system/uav-object-detection.service <<EOF
[Unit]
Description=UAV local NPU detection console
After=network.target

[Service]
Type=simple
User=uav-web
Group=uav-web
WorkingDirectory=$root/backend
Environment=PYTHONPATH=$root/backend
Environment=UAV_DATA_DIR=$root/data
Environment=UAV_RKNN_LIBRARY=$root/runtime/lib/librknnrt.so
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
cat > /etc/systemd/system/uav-npu-metrics.service <<EOF
[Unit]
Description=Read-only NPU load sampler for UAV console
PartOf=uav-object-detection.service
After=uav-object-detection.service

[Service]
Type=simple
User=root
Environment=PYTHONPATH=$root/backend
ExecStart=/usr/bin/python3 -m uav_app.npu_metrics
RuntimeDirectory=uav-object-detection
RuntimeDirectoryMode=0755
Restart=on-failure
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
PrivateNetwork=true
CapabilityBoundingSet=CAP_DAC_READ_SEARCH
RestrictAddressFamilies=AF_UNIX
ReadWritePaths=/run/uav-object-detection
UMask=0022

[Install]
WantedBy=uav-object-detection.service
EOF
systemctl daemon-reload
# Import the binary and metadata as data; no RKNN runtime is imported or executed.
if [[ "${1:-}" != --upgrade && -f "$root/model-bundle/manifest.json" ]]; then
    runuser -u uav-web -- env "PYTHONPATH=$root/backend" "UAV_DATA_DIR=$root/data" \
        "$root/.venv/bin/python" -m uav_app.cli import-model --bundle "$root/model-bundle"
fi
systemctl enable --now uav-object-detection.service
systemctl enable --now uav-npu-metrics.service
echo 'Web service enabled. Detection runs only on an explicit request or saved autostart setting.'

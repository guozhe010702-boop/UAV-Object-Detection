ARG BASE_IMAGE=ubuntu:22.04
FROM ${BASE_IMAGE}
ENV DEBIAN_FRONTEND=noninteractive OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 \
    YOLO_AUTOINSTALL=false YOLO_CONFIG_DIR=/tmp/yolo MPLCONFIGDIR=/tmp/matplotlib
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-pip git ca-certificates libglib2.0-0 libgl1 \
    && rm -rf /var/lib/apt/lists/*
RUN python3 -m pip install --no-cache-dir torch==2.2.2 torchvision==0.17.2 --index-url https://download.pytorch.org/whl/cpu
COPY requirements.txt /tmp/requirements-conversion.txt
RUN python3 -m pip install --no-cache-dir -r /tmp/requirements-conversion.txt
RUN git clone https://github.com/airockchip/ultralytics_yolo11.git /opt/rk-yolo11 \
    && git -C /opt/rk-yolo11 checkout --detach 0692e9297670acf4cc6d0cec773d7a9493cb8a5f \
    && test "$(git -C /opt/rk-yolo11 rev-parse HEAD)" = 0692e9297670acf4cc6d0cec773d7a9493cb8a5f
ENV PYTHONPATH=/opt/rk-yolo11
WORKDIR /project
ENTRYPOINT ["python3", "conversion/convert.py"]

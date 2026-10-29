# RK3588 部署模型

此目录提供两个 RKNN 部署模型、各自的清单和模型还原脚本。由于 GitHub 文件写入接口限制，模型以 Base64 分片保存；克隆仓库后可按下方命令还原为原始二进制文件，脚本会逐个核对 SHA-256。

| 文件 | 精度 | 文件 SHA-256 | 备注 |
|---|---|---|---|
| 还原后 `rk3588-yolo11n/visdrone-yolo11n-int8-640-rk3588.rknn` | INT8 | `79a3047684f14c55c3b5c875a7701f71b12aaccc3187ed3cd1d277492f35df3a` | 默认部署；64 张训练集图像校准后，在 548 张验证图上评测 |
| 还原后 `rk3588-yolo11n/visdrone-yolo11n-fp16-640-rk3588.rknn` | FP16 | `d6ebc76ac8715310375fe77f598a9a74f6d3ba8980257711551d39299de499f9` | 精度回退对照 |

在 **仓库根目录**执行：

```bash
python model-assets/restore_models.py
```

脚本把 `chunks/` 中的分片解码到 `rk3588-yolo11n/`，先写临时文件，再核对 SHA-256 后原子替换。分片不匹配或缺失时会报错，不留下不完整的模型文件。

对应 `.manifest.json` 记录输入预处理、类别、输出张量布局、导出器与校验值。两个模型面向 RK3588、640×640 RGB NHWC 输入，使用 Rockchip RKNN 2.3.2 工具链导出。电脑或其它板端环境需要自行准备兼容的 RKNN Runtime 与驱动；本仓库不分发运行库或内核驱动。

模型来源是 [dronefreak/visdrone-yolo11n](https://huggingface.co/dronefreak/visdrone-yolo11n)，固定 revision `c453ee5`。模型卡标注 AGPL-3.0，并指出 VisDrone 数据集的 CC BY-NC-SA 3.0 条件适用于基于该数据训练的模型。本模型文件按署名、相同方式共享和非商业研究条件提供。商业使用或再分发前，请向原权利人确认授权。

模型精度与实时性能的脱敏验收摘要见 [`../reports/`](../reports/)。本目录不含训练图片、相机视频、校准图、原始预测、设备数据库或运行日志。

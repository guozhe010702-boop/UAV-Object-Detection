# 来源与使用边界

| 部分 | 固定来源 | 说明 |
|---|---|---|
| YOLO11n VisDrone 权重 | [dronefreak 模型库](https://huggingface.co/dronefreak/visdrone-yolo11n)，revision `c453ee5`、SHA-256 见 `models.lock.json` | 模型卡标注 AGPL-3.0，并单独说明 VisDrone 数据集使用条件；不将它宣传为无条件商业授权 |
| 开源训练/参考工程 | [VisDrone-dataset-python-toolkit](https://github.com/dronefreak/VisDrone-dataset-python-toolkit) | GitHub 工程提供模型库入口；本项目未复制整套训练代码 |
| 导出器 | [airockchip/ultralytics_yolo11](https://github.com/airockchip/ultralytics_yolo11/tree/0692e9297670acf4cc6d0cec773d7a9493cb8a5f) | AGPL-3.0，独立容器固定提交，使用其 RK 优化检测头 |
| RKNN 转换工具 | [RKNN-Toolkit2](https://github.com/airockchip/rknn-toolkit2)，2.3.2 | 遵守其 SDK 许可证；没有重新分发板端驱动或覆盖 runtime |
| 输出契约依据 | [Rockchip Model Zoo YOLO11](https://github.com/airockchip/rknn_model_zoo/tree/main/examples/yolo11) | 标准单输出 ONNX 与 RK 九输出模型不同，不能混用后处理 |
| VisDrone 标注 | [VisDrone-Dataset](https://github.com/VisDrone/VisDrone-Dataset) | 常见 Ultralytics 配置为 10 类，本选定 checkpoint 实际为 11 类；“其他”类有效性以模型卡说明为准 |
| 网页及服务 | React 18.3.1、Vite 5.4.21、FastAPI 0.115.6、SQLite | 依赖版本见各自锁定文件；运行时不从 CDN 加载脚本或字体 |

模型卡说明“其他”类没有有效训练样本、报告 AP 为 0；前端保留标签并标记待验证，不虚构这一类别的识别能力。模型卡中的第三方性能数据不是当前 EVM3588 的实测数据。

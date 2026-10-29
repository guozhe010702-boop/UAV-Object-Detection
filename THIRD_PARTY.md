# 来源与使用边界

| 部分 | 固定来源 | 说明 |
|---|---|---|
| YOLO11n VisDrone 权重与派生 RKNN | [dronefreak 模型库](https://huggingface.co/dronefreak/visdrone-yolo11n)，revision `c453ee5`、SHA-256 见 `models.lock.json`；部署文件位于 `model-assets/rk3588-yolo11n/` | 模型卡标注 AGPL-3.0，并说明训练数据集 CC BY-NC-SA 3.0 的非商业研究条件适用于模型；按署名、相同方式共享与非商业条件发布。商业用途前需自行取得权利人许可 |
| 开源训练/参考工程 | [VisDrone-dataset-python-toolkit](https://github.com/dronefreak/VisDrone-dataset-python-toolkit) | GitHub 工程提供模型库入口；本项目未复制整套训练代码 |
| 导出器 | [airockchip/ultralytics_yolo11](https://github.com/airockchip/ultralytics_yolo11/tree/0692e9297670acf4cc6d0cec773d7a9493cb8a5f) | AGPL-3.0，独立容器固定提交，使用其 RK 优化检测头 |
| RKNN 转换工具 | [RKNN-Toolkit2](https://github.com/airockchip/rknn-toolkit2)，2.3.2 | 遵守其 SDK 许可证，不分发或修改板端驱动 |
| NPU 运行库和 API | [Rockchip RKNN 2.3.2 C API](https://github.com/airockchip/rknn-toolkit2/blob/v2.3.2/rknpu2/runtime/Linux/librknn_api/include/rknn_api.h) | 独立 ctypes 绑定依据官方 ABI；运行库私有保存，摘要见 runtime.lock.json，不覆盖系统 runtime；本地离线包中的 SDK 二进制遵守 Rockchip 原始使用条款 |
| 输出契约依据 | [Rockchip Model Zoo YOLO11](https://github.com/airockchip/rknn_model_zoo/tree/main/examples/yolo11) | 标准单输出 ONNX 与 RK 九输出模型不同，不能混用后处理 |
| VisDrone 标注 | [VisDrone-Dataset](https://github.com/VisDrone/VisDrone-Dataset) | 常见 Ultralytics 配置为 10 类，本选定 checkpoint 实际为 11 类；“其他”类有效性以模型卡说明为准 |
| 实测原图 | [Voxel51 VisDrone2019-DET 镜像](https://huggingface.co/datasets/Voxel51/VisDrone2019-DET) 的 `0000001_02999_d_0000005.jpg` | 未画框航拍原图，按 VisDrone 数据条款仅本地验证；不将上游画框示例当成本项目推理输出，不把图片放入源码仓库 |
| 视频采集与解码 | 当前板端已有的 FFmpeg Rockchip 私有构建 | 使用原有 FFmpeg 可执行文件，子进程单独设置库路径，避免 RKNN/RGA 库污染；源码仓库与新部署包不重新分发 FFmpeg |
| 网页及服务 | React 18.3.1、Vite 5.4.21、FastAPI 0.115.6、SQLite | 依赖版本见各自锁定文件；运行时不从 CDN 加载脚本或字体 |

模型卡说明“其他”类没有有效训练样本、报告 AP 为 0；前端保留标签并标记待验证，不虚构这一类别的识别能力。模型卡中的第三方性能数据不是当前 EVM3588 的实测数据。

v0.3.0 公开数据验证：DET 镜像固定 `3c3b9e9bd44c91121c1fc19fce428f0e6b71bba2`；MOT 连续帧镜像固定 `3330e2096cf866ec0a70ae663681b6a5c8a967d9`。两者遵守 VisDrone 原始非商业研究条件，不把页面顶部简化的许可标签当作商业授权。原始图像、视频、标注大文件均只保留本地。评分使用 pycocotools 2.0.7（COCO API，BSD 来源），并公开自定义忽略区域规则，不冒充官方挑战工具输出。

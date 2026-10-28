# 01 + 03 验证记录

日期：2026-10-28。范围为模型转换和网页应用，**没有执行摄像头/NPU 实时检测**。

## 模型转换：实际执行

- 原始 PT：5,545,754 字节，SHA-256 `97d78d933f46d693f68817fca253c728444aafcec92be42c86ad703ed67d40d5`。
- x86 Linux CPU 容器，PyTorch 2.2.2、Rockchip 导出 fork 固定提交、RKNN-Toolkit2 2.3.2。
- 从 checkpoint 实际读取 11 类：pedestrian、people、bicycle、car、van、truck、tricycle、awning-tricycle、bus、motor、others。
- ONNX：10,410,830 字节，SHA-256 `5ec0587ed1354de854072d57cd548b4d0085e0e23b51c317bb5ca2213bc70aa1`；ONNX checker 通过，三尺度九输出契约匹配。
- 固定随机输入的 PyTorch/ONNX 分支数值对照通过，最大绝对误差 `8.296966552734375e-05`。这项检查不构成航拍检测精度评估。
- RKNN：6,959,878 字节，FP16，SHA-256 `d6ebc76ac8715310375fe77f598a9a74f6d3ba8980257711551d39299de499f9`。
- 首次转换进程记录约 3.77 秒，不含首次镜像/依赖下载构建时间。产物为 `artifacts/visdrone-yolo11n-fp16-640/`，转换记录明确 `validated_on_board=false`。

## 网页与数据管理

- 后端 14 项自动测试通过：鉴权/退出、跨站请求拒绝、设置校验与持久化、图片上传/坏图清理、拒绝 PT 执行、RKNN 清单与摘要、类别容量、CSV 公式保护、统计口径、路径越界、上传上限和推理未接入状态。
- React 生产构建通过；资源全部本地打包，无外部 CDN。
- 真实无界面浏览器访问实际后端：登录、上传本次真实 RKNN 与清单、设为待用模型、五个页面、保存设置均通过。
- 1440 宽桌面、390 宽手机检查；修正隐藏文件控件显示和手机导航裁切，无页面横向溢出、无前端脚本异常。截图与浏览器结果在 `.cache/browser-check/`。
- 测试夹具仅在测试私有目录使用，不向实际应用数据库填充模拟记录；首页 FPS/推理时间/当前目标数保持缺失状态。

## 板端检查与部署

- 只读检查确认现有板子为 Ubuntu 20.04.5、Python 3.8.10、aarch64；检查时 `/dev/video44` 无占用。
- 已准备匹配 Python 3.8 / ARM64 的固定离线 wheels，应用运行不需要板端联网。
- 网页部署结果以 `.cache/board-install.log` 与板端 `installation.json` 为准；本文不以“有安装脚本”等同于实机部署通过。
- 实际离线安装通过，`uav-object-detection.service` 为 `active` / `enabled`，运行用户 `uav-web`，页面监听 8088；已读取真实模型 1 份、类别 11 个、检测记录 0 条。
- 板端 API 回读通过，`inference_connected=false`、处理 FPS 为 `null`；检查时相机无占用。运行中的 `app.py` 摘要与电脑源码一致。
- 实际访问入口为 `http://192.168.2.221:8088`；未停止原视频服务，未调用 RKNN runtime，未重启或升级开发板。
- 电脑通过局域网访问板端 `/api/health` 返回 HTTP 200，版本 0.1.0、`inference_connected=false`。

## 未完成或不在本轮范围

- 尚未验证 RKNN 与当前 NPU 驱动的实际推理兼容性、FP16/INT8 精度、摄像头/RTSP 实时采集和检测框。
- 未宣称实现 25 FPS、NPU 25% 或三核加速效果；没有帧率长测。
- 记录/截图接口已经具备，但没有推理就不会自动产生检测记录；统计不是跨帧去重车流量。
- systemd 可配置开机启动网页；本轮不重启开发板验证，不修改现有视频服务和固件。

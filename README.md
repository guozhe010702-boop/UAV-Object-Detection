# UAV Object Detection：RK3588 无人机视角目标检测工作台

独立工程目录：`av_dev/UAV Object Detection/`。目标硬件是现有 EVM3588，不是另购设备。**01 模型转换、02 板端 NPU 推理、03 本地网页**现已接通。v0.2.0 已在当前板子验证真实 IMX415 与未画框的 VisDrone 航拍图，不使用合成画面或模拟检测计数。

独立仓库：[guozhe010702-boop/UAV-Object-Detection](https://github.com/guozhe010702-boop/UAV-Object-Detection)。从这里克隆时，仓库本身就是工程根目录，不需要外层 `av_dev`，也不需要再创建同名子文件夹。仓库上传源码、锁定信息和文档；访问码、数据库、媒体、模型二进制、虚拟环境和生成包留在本地。

## 当前可用范围

| 部分 | 已实现 | 实际边界 |
|---|---|---|
| 模型来源 | 公开 VisDrone YOLO11n，固定下载 SHA-256 | 第三方权重，不是本项目重新训练 |
| 模型转换 | CPU 上 PT→RK 优化 ONNX→RKNN，640×640、FP16 | 不需要显卡；转换在电脑 Linux 容器，不在板子上进行 |
| 类别 | 从 checkpoint 读取 11 类，导出中英文映射 | “其他”在作者模型卡中为 0 AP，不能承诺可靠识别 |
| 实时检测 | 独立 RKNN 进程、单 context 三核模式、DFL/NMS、同帧中文框 | 当前 FP16 实摄像头短测约 15 FPS，不承诺 25 FPS；没有 INT8 或精度长测 |
| 网页 | React 中文五页面，由同一个 FastAPI 服务提供 | 不依赖 CDN 或云端；原片预览与真实检测画面分开 |
| 数据管理 | SQLite、媒体上传、记录查询/CSV、截图下载接口、模型清单校验、设置 | 检测期间按秒采样保存真实计数和中文框截图 |
| 设备资源 | 真实 CPU、内存、存储、温度；可读取时显示三核 NPU 负载 | 电脑本地运行显示电脑资源；无法读取的指标显示 — |
| 开机使用 | 独立虚拟环境、离线 ARM64 wheel、systemd 服务 | 网页默认开机启动；检测需按钮启动，也可显式勾选自动检测 |

现有开发板检查结果为 **Ubuntu 20.04.5 / Python 3.8.10 / aarch64**；未升级系统或内核。原 `av_dev` 视频控制与 `rk-yoloworld` 不参与本服务的运行。

## 目录与程序职责

```text
UAV Object Detection/
├─ backend/
│  ├─ requirements.txt          板端 Python 3.8 兼容的固定运行依赖
│  ├─ requirements-dev.txt      电脑测试依赖
│  └─ uav_app/
│     ├─ app.py                FastAPI、登录、上传/下载、CSV、静态页面
│     ├─ schema.py             模型契约和设置校验
│     ├─ store.py              SQLite、UUID 文件、上传校验及磁盘保护
│     ├─ engine.py             检测进程启停、日志、退出清理、状态与过期判断
│     ├─ worker.py             实际 NPU 推理、最新帧通信、中文框和异步记录
│     ├─ rknn_backend.py       RKNN 2.3.2 C API 绑定、张量/摘要校验和三核绑定
│     ├─ postprocess.py        RGB letterbox、DFL 解码、分类 NMS 与坐标还原
│     ├─ inference_io.py       文件/RTSP/V4L2、FFmpeg 采集、完整帧拼接和字体
│     ├─ npu_metrics.py        独立只读 NPU 负载采样，不让网页以 root 运行
│     ├─ resources.py          主机 CPU 差分、内存、温度、三核 NPU
│     └─ cli.py                启动服务、查看访问码、导入模型
├─ frontend/
│  ├─ src/main.jsx             实时检测、记录、统计、模型、设置五个页面
│  ├─ src/style.css            响应式布局，视频保持比例，不裁切
│  ├─ verify-ui.mjs            真实浏览器回归，无摄像头/NPU 调用
│  ├─ package*.json            锁定 React/Vite 构建依赖
│  └─ dist/                    已构建静态页面，仅本地生成
├─ conversion/
│  ├─ Dockerfile               独立 x86 Linux CPU 转换环境
│  ├─ requirements.txt         PyTorch 周边和 RKNN-Toolkit2 版本
│  └─ convert.py               九输出导出、ONNX 数值对照、RKNN 构建和清单
├─ tools/
│  ├─ download_model.py        固定公开权重下载与 SHA-256 校验
│  ├─ bootstrap_node.py        项目私有 Node，校验官方摘要，不改系统 PATH
│  ├─ bootstrap_venv.py        板端离线创建私有 Python 环境
│  ├─ board_probe.py           只读检查板端环境，不打开相机
│  ├─ deploy_board.py          首次独立部署，不覆盖已有安装
│  ├─ verify_board.py          只读回读服务、模型、相机占用与源码摘要
│  ├─ upgrade_board.py         备份程序后升级本服务，保留数据库和访问码
│  ├─ prepare_runtime.py       按摘要下载私有 RKNN 2.3.2 运行库
│  ├─ validate_npu.py          板端图片推理基准与数值对照数据
│  └─ package_release.py       源码包、模型包与离线网页部署包
├─ systemd/install.sh          独立低权限服务、开机启动和故障重启
├─ tests/                     后端接口、鉴权、路径、模型与统计回归
├─ runtime.lock.json          RKNN 运行库来源、版本与 SHA-256
├─ runtime/lib/               本地/板端私有运行库，不入 Git
├─ models.lock.json           权重摘要、导出源码提交和来源
├─ models/source/             原始 PT，只留本地
├─ artifacts/                 ONNX/RKNN/清单与转换记录，只留本地
├─ data/                      访问码、SQLite、上传文件和截图，只留本地
├─ releases/                  本地交付 ZIP 和校验文件
├─ .cache/、.venv/             私有工具、离线依赖、测试缓存与环境
├─ run_windows.ps1            电脑本地网页预览入口
├─ VALIDATION.md              实测与未完成事项
└─ todo.md                    实施进度
```

板端独立运行目录为 `/userdata/uav-object-detection/`。模型、视频、访问码、数据库、缓存和生成包不进入 Git；本项目不会修改 `rk-yoloworld` 的模型或原 `av_dev` 服务。当前采集复用板端已有 `/userdata/av_dev/ffmpeg_pipeline/runtime/bin/ffmpeg`，它包含 NV12M 兼容补丁；FFmpeg 的独立库路径仅对子进程生效。新板需要自行提供匹配 FFmpeg，可设置 `UAV_FFMPEG`，普通发行版 FFmpeg 不保证支持本板 NV12M。

## 打开板端网页

部署成功后，在同一局域网的电脑或手机浏览器访问 **`http://板子IP:8088`**。地址以板端实际 IP 为准，不依赖外网。

2026-10-28 已在当前板子部署并回读：**http://192.168.2.221:8088**，服务为 `active/enabled`，已导入一份真实转换模型，NPU 实时检测已接通。仍未重启板子验证开机过程。

**板端 Linux，root 终端，任意目录：**

```bash
hostname -I
```

解释：查看板端 IP，选择电脑能访问的局域网地址，不要把电脑 IP 当成板子 IP。

```bash
cat /userdata/uav-object-detection/data/admin-token.txt
```

解释：查看当前设备随机生成的访问码，在网页登录框输入；访问码只在设备私有数据目录保存，不写入源码或网页。不要将其截图公开。

登录后即可在“实时检测”查看已启动的 IMX415。若尚未运行，按下面步骤启动。

## 02 实时检测怎么用

1. **模型管理**：本机已导入 VisDrone YOLO11n；选“设为待用模型”。已执行过真实 NPU 推理会显示“板端实际推理通过”，这不等于 mAP 精度验收。
2. **设备设置**：选择源，填写阈值，保存。运行中必须先停止检测，保存接口会拒绝直接修改，避免页面参数与实际运行不同。
3. **实时检测**：点“开始检测”。错误显示在阶段栏，“检测日志”可查看 RKNN 与 FFmpeg 详情；没有可用 NPU 时明确失败，不改用 CPU 模型。
4. **停止检测**：只终止本服务的 RKNN 与采集进程；不会终止原 av_dev 或 YOLO-World。关闭浏览器不会停止板端检测。

源的配置方法：

| 源 | 操作 | 当前验证情况 |
|---|---|---|
| 航拍图片 | 上传图片，选择模型，点“检测此素材” | 未画框 VisDrone 原图实测，通过；每张只推理一次，完成后保留结果 |
| 视频文件 | 上传 MP4/MOV/MKV，点“检测此素材” | 真实 IMX415 录制文件验证；按原速读，文件结束显示“检测完成”，不自动循环 |
| IMX415 | 选择 IMX415、`/dev/video44`、1920×1080、请求 30 FPS、NV12 | 实际双平面 NV12M 已验证；当前实验驱动可能仍输出约 60 FPS，以取帧计数为准 |
| RTSP | 选择 RTSP，填写不含凭据的有效 RTSP 地址 | 独立本机 TCP 发布流实测；外部带认证的网络相机待扩展，不把密码写进地址 |
| USB | 选择实际 `/dev/videoN`，按设备支持选择 YUYV/MJPEG/NV12 及尺寸 | 接口已实现，当前没有 USB 相机，未做该硬件实测 |

相机由其他程序占用时会报告占用者，不自动杀进程；可先在原程序停止采集，或者改用原程序发布的 RTSP 共享流。采集尺寸和 FPS 是请求值，节点/传感器是否接受以日志和实际取帧为准。

### 数据与线程逻辑

```text
真实图片 / 文件视频 / RTSP / V4L2
  → FFmpeg 解码或 NV12M 采集，按比例缩到预览宽度
  → 一个最新等待帧（满时丢旧）
  → RGB uint8、640×640 黑色 letterbox
  → RKNN 单 context、CORE_0_1_2（掩码 7）
  → 九输出 DFL + 分类 NMS + 还原到当前预览帧坐标
  → 同帧中文框 JPEG → 浏览器；秒级计数/截图 → SQLite
```

一个独立推理进程内，主线程负责 NPU/后处理/绘制；一个采集线程接收完整 RGB 帧，一个记录线程异步保存。图片不需要采集线程。FFmpeg 是独立子进程，SDK 可能自行创建内部线程。这里不是之前 YOLO-World 的九 context 工程。

预处理缩放、颜色转换、DFL/NMS 与 JPEG 在 CPU 上，神经网络前向计算在 NPU；本版不是全 RGA 零拷贝流水线。三核掩码不保证三核均匀负载，实际负载必须读取指标。等待队列只有一个槽；不复制旧帧补足目标 FPS，不将旧帧检测框贴到新帧。源结束后会处理最后一个等待帧。

变化中的 JPEG/状态放在私有 tmpfs，避免持续写 eMMC；磁盘上只保留按间隔采样的截图、SQLite 和有上限的日志。记录上限 10,000 条，超过后清理最早记录及对应截图；空间不足 1 GiB 时暂停记录、提示错误，检测继续。上传素材不会自动清理。

### 指标怎么看

- 处理 FPS：已完成检测帧增量 / 单调时间增量，包含预处理、NPU、后处理与画框，不是源声明 FPS。
- 取帧 FPS：采集读取线程实际收到的完整帧增量 / 同一单调时间间隔；相机请求值另报。
- 推理 ms：`inputs_set → run → outputs_get` 实际耗时及输出拷贝，不包含 JPEG；不能用其倒数冒充全链路 FPS。
- 帧年龄 P95：读出 RGB 帧到发布结果的时间；不等于镜头到屏幕延迟。
- CPU/内存是板端整机指标，CPU 归一化到 0–100%。NPU 是驱动报告的三个核忙碌率，不是模型“占用四分之一”的保证。
- 浏览器拉取最新同帧 JPEG，一次只允许一个请求；慢网络跳过预览机会，不积压旧画面。浏览器绘制速度与 NPU 处理 FPS 分开，不声称二者完全相同。
- 超过 5 秒未更新会标为过期、隐藏旧计数；断流报错不会继续显示“健康”。

计数是当前画面目标数及采样观察次数累计，没有跨帧追踪去重，不能直接当作车辆通过总数。

### 板端命令控制（不需要重新开一个检测进程）

以下均在 **开发板 Linux 终端**执行，Windows PowerShell 不能直接执行这些 Linux 路径。

```bash
cd /userdata/uav-object-detection
```

解释：进入当前板端独立项目，后面的相对路径以这里为起点。

```bash
PYTHONPATH=backend .venv/bin/python -m uav_app.cli start
```

解释：用私有环境向已运行的网页服务发送“开始检测”；沿用网页保存的模型与视频源。`PYTHONPATH=backend` 只为这次命令指定源码位置，不会另外创建控制器或抢占相机。

```bash
PYTHONPATH=backend .venv/bin/python -m uav_app.cli status
```

解释：返回当前进程、真实 FPS、NPU 运行库、三核负载、计数和错误的 JSON，不启动检测。

```bash
PYTHONPATH=backend .venv/bin/python -m uav_app.cli stop
```

解释：请求监督进程正常停止自己启动的检测和 FFmpeg，保留网页、媒体与记录。

```bash
PYTHONPATH=backend .venv/bin/python -m uav_app.cli logs
```

解释：读取最近的 RKNN 与采集日志；没有重新连接视频源的副作用。

开机自动检测需先保存有效模型/源，再显式勾选“服务启动时自动开始检测”。当前默认仍为关闭；开机即开网页和自动占用相机分别控制。

## 在电脑预览网页

以下命令在 **Windows PowerShell** 执行：

```powershell
Set-Location 'C:\Users\dvsense_docker\Desktop\work\RK3588\av_dev\UAV Object Detection'
```

解释：进入独立工程，目录名有空格，路径必须加引号。

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run_windows.ps1 -Token
```

解释：`-NoProfile` 不加载个人配置，`-ExecutionPolicy Bypass` 仅对这次进程生效，`-File` 指定入口，`-Token` 查看电脑这份服务的访问码；它与板端访问码分别保存。

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run_windows.ps1
```

解释：使用项目 `.venv` 启动本机服务，浏览器打开 **http://127.0.0.1:8088**。保持终端运行；Ctrl+C 正常停止电脑服务，不影响板端。

新电脑需要先创建私有环境并安装 `backend/requirements-dev.txt`；现有这台电脑已准备好。网页静态文件已构建，无需启动 Node 开发服务器才能使用。

## 从 GitHub 克隆后首次启动

已有本地工程可跳过本节。以下在 **Windows PowerShell、准备保存工程的父目录**执行，需要已安装 Git 和 Python 3.8～3.10：

```powershell
git clone https://github.com/guozhe010702-boop/UAV-Object-Detection.git
```

解释：下载独立仓库，保存在新目录 `UAV-Object-Detection`；不克隆原视频或 YOLO-World 工程。

```powershell
Set-Location .\UAV-Object-Detection
```

解释：进入新克隆的工程，后面的首次准备命令均从这里执行。

```powershell
python -m venv .venv
```

解释：在当前工程创建独立 Python 环境，不修改系统或其它项目的依赖。

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
```

解释：在私有环境安装固定版本的后端和测试依赖；`-r` 指定依赖清单，首次准备需要联网。

```powershell
python tools\bootstrap_node.py
```

解释：下载并核对项目私有 Node 构建工具，保存在 `.cache/`，不进行系统安装。

```powershell
$env:PATH = (Resolve-Path '.cache\node-v22.16.0-win-x64').Path + ';' + $env:PATH
```

解释：仅给当前 PowerShell 增加私有 Node 的搜索路径，使 npm 的构建子进程也能找到 node。

```powershell
Push-Location frontend
```

解释：进入前端目录，并记住原目录；这里执行 npm 可以避免带空格的路径参数被错误拆分。

```powershell
npm.cmd ci --no-audit --no-fund
```

解释：按 `package-lock.json` 安装锁定依赖，跳过额外审计/赞助提示；需要联网。`ci` 用于首次可重复准备，不用于保留已有手改的 node_modules。

```powershell
npm.cmd run build
```

解释：生成本地静态网页到 `frontend/dist/`，运行网页时不需要 Node 服务。

```powershell
Pop-Location
```

解释：返回工程根目录，然后按上节查看本机访问码并运行 `run_windows.ps1`。无需模型即可验证网页、上传素材和保存设置；电脑缺少 RK3588 NPU，点击检测会明确失败；真实检测请打开板端地址。

ADB 工具不随仓库分发。电脑安装了 adb 时自动从 PATH 查找；需要指定其它位置时，**PowerShell、工程根目录**可执行：

```powershell
$env:UAV_ADB = 'C:\Android\platform-tools\adb.exe'
```

解释：指定本次终端使用的 adb 路径；将示例替换为实际位置。原电脑仍支持已有 RKDevTool 的相对路径作为后备。

## 01 模型转换如何复现

以下命令在 **Windows PowerShell、上述工程根目录**执行。

```powershell
python tools/download_model.py
```

解释：下载选定权重到 `models/source/`，核对固定 SHA-256；已有正确文件时复用，不执行网络模型中的 pickle。加载 PT 只发生在下一步隔离转换容器中。

```powershell
docker build --build-arg BASE_IMAGE=dvsense_cmake_builder_ubuntu22:v1.1.4 -t uav-yolo11-converter:2.3.2 -f conversion/Dockerfile conversion
```

解释：复用本机已有 Ubuntu 22.04 基础镜像，构建独立 CPU 转换环境；`-t` 指定镜像名，`-f` 指定 Dockerfile，最后是构建目录。普通新电脑可省略 `--build-arg ...`，使用 Dockerfile 默认的 `ubuntu:22.04`。首次下载环境耗时不计入模型转换时间。

```powershell
docker run --rm --init --network none --cpus 4 --memory 8g --mount "type=bind,source=$($PWD.Path),target=/project" uav-yolo11-converter:2.3.2 --pt models/source/visdrone-yolo11n.pt --output artifacts/visdrone-yolo11n-fp16-640-new
```

解释：容器禁用网络，最多 4 个 CPU、8 GiB 内存，只挂载本工程；`--pt` 指定已校验 PT，`--output` 必须是新空目录，防止覆盖已有成果。`--rm` 退出后移除临时容器，产物保留在电脑。没有 CUDA 或板端 NPU 调用。

产物包括 `model.onnx`、`model.rknn`、`classes.json`、`manifest.json` 和 `conversion-result.json`。导出器固定为瑞芯微 fork 提交 `0692e9297670acf4cc6d0cec773d7a9493cb8a5f`，RKNN-Toolkit2 为 2.3.2；图像输入 640×640，三尺度各输出 DFL、类别分数和分数和，共九个张量。

默认 FP16 不需要校准集。需要 INT8 时追加 `--int8 --calibration 数据目录`，至少提供 20 张真实、有代表性的航拍图片；本轮没有用彩条或 COCO 图片冒充航拍校准，也没有交付已验证的 INT8 模型。

公开模型以 1280 尺寸训练，缩到 640 后的小目标精度必须另测。PyTorch/ONNX 分支数值对照不等于 RKNN 板端检测精度；下一阶段应使用真实航拍验证集比对框、类别、置信度和 mAP。

## 私有 NPU 运行环境与更新

**Windows PowerShell、工程根目录：**

```powershell
python tools/prepare_runtime.py
```

解释：按 `runtime.lock.json` 下载并校验 RKNN 2.3.2 ARM64 运行库，只写项目 `runtime/lib/`；不替换板端系统库，不升级驱动。当前电脑已经准备好。

```powershell
python tools/upgrade_board.py
```

解释：通过 ADB 备份现有程序、停止本服务、更新后端/页面/私有运行库和固定依赖，再等待健康检查；保留 `data/` 中的访问码、数据库与媒体。需预先准备前端构建与 ARM64 离线 wheels。本次升级已实际执行。

模型清单中的 `validated_on_board=false` 保留为转换当时事实，不改写原转换产物。首次真实推理成功后在 SQLite `model_validation` 单独记录运行库、驱动和三核掩码，模型管理以这份运行证据显示状态。

## 03 服务管理与部署

首次离线部署工具会上传源码、构建后的页面、配套 RKNN 和 Python 3.8 ARM64 wheels，创建专用用户 `uav-web`，只允许服务写自己的 `data/`。它不重装系统、不运行 PT、不启动 NPU 检测、不停止原相机服务。

**Windows PowerShell、工程根目录：**

```powershell
python tools/package_release.py
```

解释：生成 `releases/` 中的源码、模型和板端离线包；需要先准备 `.cache/board-wheels/`。这些文件已在当前电脑生成。模型包与应用源码分开，避免大权重混入 Git。

```powershell
python tools/deploy_board.py
```

解释：通过当前 ADB 首次部署到 `/userdata/uav-object-detection/`，校验传输摘要并启用服务。已有安装时拒绝覆盖；已有安装使用 `tools/upgrade_board.py`，先备份程序、保留数据库与访问码；请勿反复运行首次安装。

下列命令均在 **板端 Linux root 终端、任意目录**执行：

```bash
systemctl status uav-object-detection.service --no-pager
```

解释：查看网页服务状态，`--no-pager` 一次性输出；服务名与原视频服务不同。

```bash
systemctl stop uav-object-detection.service
```

解释：停止网页以及它管理的 NPU/采集子进程，保留数据库、上传文件和访问码，不停止其它相机程序。

```bash
systemctl start uav-object-detection.service
```

解释：再次启动网页服务。

```bash
systemctl disable --now uav-object-detection.service
```

解释：同时关闭当前服务并取消其开机启动；数据继续保留。恢复自动启动用安装后的服务启用流程。安装默认启用的是网页，**本轮没有重启板子验证开机流程**。

## 验证与后续优化

后端用独立环境运行自动测试，浏览器测试实际调用后端并上传本次 RKNN；手机页面检查导航与横向溢出。原始报告留在 `.cache/`，结论见 [VALIDATION.md](VALIDATION.md)。

本版 FP16 + Python 路径的实际摄像头处理约 15 FPS；25 FPS 仍未达成。下一步应准备代表性航拍校准集导出 INT8，比较 640/1280 小目标精度，再评估多 context / RGA 优化；不能先写性能目标再当作实测结果。USB 硬件、带认证 RTSP、完整验证集 mAP 和长时间运行均需继续验收。

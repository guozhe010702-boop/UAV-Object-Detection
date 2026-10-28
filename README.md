# UAV Object Detection：RK3588 无人机视角目标检测工作台

独立工程目录：`av_dev/UAV Object Detection/`。目标硬件是现有 EVM3588，不是另购设备。本轮按你的选择完成 **01 模型转换 + 03 网页应用**；**02 摄像头/NPU 实时检测留到下一阶段**。页面不填充虚构检测框、FPS、推理延迟或记录。

独立仓库：[guozhe010702-boop/UAV-Object-Detection](https://github.com/guozhe010702-boop/UAV-Object-Detection)。从这里克隆时，仓库本身就是工程根目录，不需要外层 `av_dev`，也不需要再创建同名子文件夹。仓库上传源码、锁定信息和文档；访问码、数据库、媒体、模型二进制、虚拟环境和生成包留在本地。

## 当前可用范围

| 部分 | 已实现 | 实际边界 |
|---|---|---|
| 模型来源 | 公开 VisDrone YOLO11n，固定下载 SHA-256 | 第三方权重，不是本项目重新训练 |
| 模型转换 | CPU 上 PT→RK 优化 ONNX→RKNN，640×640、FP16 | 不需要显卡；转换在电脑 Linux 容器，不在板子上进行 |
| 类别 | 从 checkpoint 读取 11 类，导出中英文映射 | “其他”在作者模型卡中为 0 AP，不能承诺可靠识别 |
| 网页 | React 中文五页面，由同一个 FastAPI 服务提供 | 不依赖 CDN 或云端；上传素材现在只能原片预览 |
| 数据管理 | SQLite、媒体上传、记录查询/CSV、截图下载接口、模型清单校验、设置 | 未接入检测，因此不会自动产生记录和截图 |
| 设备资源 | 真实 CPU、内存、存储、温度；可读取时显示三核 NPU 负载 | 电脑本地运行显示电脑资源；无法读取的指标显示 — |
| 开机使用 | 独立虚拟环境、离线 ARM64 wheel、systemd 服务 | 开机启动网页不等于开机启动检测；不会占用摄像头 |

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
│  └─ package_release.py       源码包、模型包与离线网页部署包
├─ systemd/install.sh          独立低权限服务、开机启动和故障重启
├─ tests/                     后端接口、鉴权、路径、模型与统计回归
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

板端独立运行目录为 `/userdata/uav-object-detection/`。模型、视频、访问码、数据库、缓存和生成包不进入 Git；本项目不会修改 `rk-yoloworld` 的模型或原 `av_dev` 服务。

## 打开板端网页

部署成功后，在同一局域网的电脑或手机浏览器访问 **`http://板子IP:8088`**。地址以板端实际 IP 为准，不依赖外网。

2026-10-28 已在当前板子部署并回读：**http://192.168.2.221:8088**，服务为 `active/enabled`，已导入一份真实转换模型，NPU 实时推理未启动。没有重启板子验证开机过程。

**板端 Linux，root 终端，任意目录：**

```bash
hostname -I
```

解释：查看板端 IP，选择电脑能访问的局域网地址，不要把电脑 IP 当成板子 IP。

```bash
cat /userdata/uav-object-detection/data/admin-token.txt
```

解释：查看当前设备随机生成的访问码，在网页登录框输入；访问码只在设备私有数据目录保存，不写入源码或网页。不要将其截图公开。

登录后可上传图片/视频检查原片、上传 RKNN 和清单、设为待用模型、保存源与阈值。**页面中的实时检测仍标为“待接入”**，选择 RTSP/USB/IMX415 不会立即打开输入源。

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

解释：返回工程根目录，然后按上节查看本机访问码并运行 `run_windows.ps1`。无需模型即可验证网页、上传素材和保存设置；检测保持未接入状态。

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

解释：通过当前 ADB 首次部署到 `/userdata/uav-object-detection/`，校验传输摘要并启用服务。已有安装时拒绝覆盖；升级应另做保留数据库和访问码的版本迁移，不能反复运行首次安装覆盖数据。

下列命令均在 **板端 Linux root 终端、任意目录**执行：

```bash
systemctl status uav-object-detection.service --no-pager
```

解释：查看网页服务状态，`--no-pager` 一次性输出；服务名与原视频服务不同。

```bash
systemctl stop uav-object-detection.service
```

解释：停止当前网页服务，保留数据库、上传文件和访问码，也不停止其它相机程序。

```bash
systemctl start uav-object-detection.service
```

解释：再次启动网页服务。

```bash
systemctl disable --now uav-object-detection.service
```

解释：同时关闭当前服务并取消其开机启动；数据继续保留。恢复自动启动用安装后的服务启用流程。安装默认启用的是网页，**本轮没有重启板子验证开机流程**。

## 验证与下一阶段

后端用独立环境运行自动测试，浏览器测试实际调用后端并上传本次 RKNN；手机页面检查导航与横向溢出。原始报告留在 `.cache/`，结论见 [VALIDATION.md](VALIDATION.md)。

下一阶段才接入 NPU：优先用航拍文件验证 RKNN 精度和后处理，再加入 RTSP/USB/IMX415，处理独占采集、队列丢旧帧、中文框绘制与秒级记录。25 FPS、NPU 25%、三核同时处理一帧等指标都需要单独实测，不能由模型文件或网页完成情况推断。

# 湖大多模态情感机械狗

赛道一情感交互原型。采用官方机器狗平台接口、本地 SenseVoice 中文语音与音频情绪识别、Silero VAD、Ollama 多模态模型和 Windows 中文语音合成。Dify 用 Docker Compose 本地部署，提供可导入的文本共情工作流。

## 本机目录与启动

工作目录为 `E:\机械狗比赛开发`：

- `00_比赛资料`：原始比赛材料的本地副本，不上传仓库。
- `01_项目代码/emotion_dog`：本仓库代码；`01_项目代码/dify`：官方 Dify 1.17.1 源码。
- `02_运行环境`：Python、虚拟环境、Docker Desktop、Docker 数据盘和 Ollama。
- `03_模型`：中文语音模型、VAD 和 Ollama 模型。
- `04_下载缓存`：安装包、依赖缓存及带 SHA256 的下载来源记录。
- `05_日志`：服务日志与按轮处理耗时。
- `06_测试素材`：官方测试语音与生成的播报音频。

双击根目录的 `启动情感机械狗.cmd`，或在 PowerShell 执行本仓库的 `start.ps1`。操作页面为 `http://127.0.0.1:8765`，API 文档为 `/docs`。

双击 `启动Dify.cmd`，或执行 `start-dify.ps1`。Dify 页面为 `http://127.0.0.1:8080`，首次初始化路径为 `/install`。

Dify 使用比赛专用的 `EmotionDogUbuntu` WSL 和 Docker Engine，虚拟磁盘位于 `02_运行环境/wsl`。首次启动可下载安装专用 Ubuntu 和 Docker。启动脚本保留已安装的镜像，并支持从官方注册表下载、校验及导入离线镜像包，缓存放在 `04_下载缓存/docker-images`。数据库及应用存储使用 Docker 命名卷。原有 Ubuntu 虚拟磁盘发生挂载错误，原文件保留。

本机现有下载代理端口为 7897。WSL 通过 Windows 启动进程的标准输入输出访问该代理和本机模型。下载目的地限定为上游官方域名，HTTPS 校验保持开启；Ollama 监听 Windows 本机回环地址，Dify 容器通过 Docker 私有桥接地址调用它。首次下载需要网络，已有镜像和模型可复用。分段下载保留续传文件，并在完成后校验官方 SHA256；未完成校验的模型不会登记为可用模型。安装、模型、镜像、音频和下载缓存均指定到 E 盘，Windows 用户目录仅保留少量工具及配置。

## 交互流程

页面支持文字测试、音频与图片上传，以及本机麦克风/摄像头、机器狗 WebRTC 音视频。点击“连接输入”后由用户授予设备权限；点击“开始对话”后按停顿切分语音，后端使用 Silero VAD 复核人声。浏览器保留短时图像缓存，取接近最后发声时刻的图像。后端识别文字及音频情绪，将其与图像送入本地多模态模型，生成情绪推测、依据及共情回复，再合成 WAV。播报期间暂停提交音频，以免将机器自己的声音当成下一轮输入。

浏览器 RMS 只用于快速判断提交时机，不代替后端 VAD。图像时间采用同一浏览器时钟；机器狗流不同轨道的源端时间戳与延迟仍需实体联调验证，不应据此宣称严格的源端同步。

情绪结果属于模型推测，置信度是模型自评，未经校准。该原型未验证方案中的 90% 准确率、2.5 秒延迟或现场成功率。缺图时支持音文对话；无音频时支持文字测试。模型服务故障会明确报错，不伪造模型结果。

## 机器狗接口

在本地 `.env` 中填写平台配置，参考 `.env.example`。实际凭证不进入版本控制。当前基础地址来自官方教学视频，配置可调整。适配器支持设备查询、WHEP SDP 协商、文本播报和少量预设动作。

签名实现按照接口文档附录1排序、URL编码、HMAC及Base64。文档未明确 HMAC 摘要算法和所有请求体边界条件，因此使用可配置的 `ROBOT_HMAC_ALGORITHM` 与 `ROBOT_BODY_SIGN_MODE`；默认 SHA1 与 content 方式须与组委会前置脚本及实际服务核对。GET 设备信息可先用于鉴权验证。

`ROBOT_ALLOW_PLAYBACK` 和 `ROBOT_ALLOW_ACTIONS` 默认关闭。现场确认设备、周围空间和操作资格后再启用。仅显式点击动作按钮才会提交动作；模型提出的动作建议不会自动执行。API 的“submitted”仅表示指令提交，不等于设备已经执行成功。

## Dify 与本地模型

默认后端为 Ollama，本机模型为 `qwen3.5:4b`。模型只需首次下载，后续推理可在本机完成。也可将 `.env` 的 `LLM_BACKEND` 改为 `dify` 并配置本地 Dify 应用 API Key。机器狗平台的 Access Key 不用于 Dify 模型鉴权。

`deploy/empathy-chatflow.yml` 是 Dify 文本工作流模板，通过 HTTP 节点访问本机 Ollama；图片交互默认走原生 Ollama 后端。Dify 文本后端目前不接受图片，遇到图片会明确提示，避免将图片静默丢弃。

## 测试与迁移

`python -m pytest -q` 验证签名编码、输入限制、模型动作白名单、跨站请求限制及音文图交互接口的衔接。`python scripts/verify_local.py` 验证真实语音模型、VAD、TTS 和本地模型服务，默认不访问机器狗平台。`python scripts/verify_end_to_end.py` 测试运行中的页面后端、真实文字/图像/音频模型及可下载的语音文件。平台恢复后可使用 `python scripts/verify_local.py --with-robot` 单独检查设备查询；播报和动作另需现场测试。

当前交付以代码为主，中移杭研平台联调待平台恢复。实际完成和未完成的项目见 `DEPLOYMENT_STATUS.md`，不要以启动说明替代实测记录。

迁移时保持目录层级，将本仓库放到根目录的 `01_项目代码/emotion_dog`，执行 `setup.ps1`；另从官方仓库取得 Dify 1.17.1 的 docker 目录。设置 `.env` 的模型和日志路径即可换盘。大模型、虚拟环境、赛事资料和密钥均留在本地，不作为 Git 文件上传。

## 上游来源

- [Dify 官方 Docker Compose 部署](https://docs.dify.ai/en/self-host/deploy/quick-start/docker-compose)
- [Ollama Windows 官方部署](https://docs.ollama.com/windows)
- [Qwen3.5 模型页](https://ollama.com/library/qwen3.5)
- [sherpa-onnx SenseVoice](https://k2-fsa.github.io/sherpa/onnx/sense-voice/index.html)
- [官方 SenseVoice ONNX 模型](https://huggingface.co/csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17)

模型与软件的使用遵守各自上游许可。此仓库不转发赛事限制传播的原始资料。


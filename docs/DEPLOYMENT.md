# 部署配置与依赖

## 主机配置

config.example.json 提供当前兼容接口、gpt-6.1-sol、xhigh、ComfyUI 8189 和急急 8765。bootstrap.py 写入独立 cache 的绝对路径；如果已有 config.json，它不会覆盖。JIJI_BIND、JIJI_PORT、JIJI_CACHE_ROOT 可以在启动前覆盖服务设置，JIJI_COMFY_URL 可单独覆盖图片客户端地址。建议统一修改 config.json 的 comfy_url，让图片和视频走同一服务。

导演密钥可通过界面保存 api_key，或通过 JUNFLOW_API_KEY / 根目录 secrets.json 加载。图片客户端需要 COMFY_API_KEY；复制 secrets.example.json 为 secrets.json 后填写，或使用同名环境变量。视频节点的 LimAPI 等服务密钥在 ComfyUI 节点环境中配置。空模板不会提供实际服务权限。

新仓库的 api_keys.py 只读取明确的环境变量和仓库根目录 secrets.json，不扫描桌面父项目或其他 ComfyUI 的 .env。图片结果通过 ComfyUI /view 获取，不依赖 D 盘共享目录。

## 必须由现有环境提供

Python 3.11 / 3.12；Pillow 用于图像预览；FFmpeg 用于视频解析、抽帧和处理。网页使用静态 HTML / CSS / JS，运行不需要 Node.js；开发时 Node.js 22 用于语法检查。

ComfyUI 默认节点应包含 LoadImage、ImageBatch、SaveImage、CreateVideo / SaveVideo 等。当前模型还需要：

- 生图：GeminiNanoBanana2、OpenAIGPTImageNodeV2、ByteDanceSeedreamNodeV3，按实际选择配置相关账号权限。
- Seedance：LimAPISeedanceGenerate、SeedanceRefPack、SeedanceAudioPack、LoadAudio。
- H3：MiniMaxH3Director、MiniMaxH3DirectorGroupReferenceToVideo、MiniMaxH3DirectorGroupImageToVideo，以及配置匹配的 UNET / CLIP / VAE 权重。

视频成片读取仍要求急急主机能够访问 ComfyUI 的 output 目录，通过 config.json 的 comfy_output_dir 指定，默认 D:/ComfyUI/output。图片结果可走远程 /view，但完整视频链路当前按同机 / 可访问输出目录部署。

本仓库保留当前节点调用约定，不包含 ComfyUI、第三方节点安装器或大模型权重。更换节点版本时先检查 /object_info 的字段和枚举，不能把当前生成图当成通用官方接口文档。

## 局域网访问

主机访问 http://127.0.0.1:8765；同事使用 http://主机真实局域网IPv4:8765，同一网络内连接。当前主机曾使用 192.168.31.22，DHCP 地址可能变化，以本次启动输出为准。

连接失败时先看启动窗口错误，再在主机测试 /api/health；主机成功后检查同事是否在同一网段及防火墙的专用网络入站规则。不要把监听地址 0.0.0.0 当链接。不要为修复访问关闭整机防火墙。仓库配置不会修改防火墙。

## 上传与读取

剧本支持 docx / txt / md；表格支持 xlsx / csv / tsv，最多 40MB，导演文本超过 4 万字截断并提示。有内容列超过 256 列应收窄表格；只读取文字与保存的公式结果，不识别嵌入图片。带任务、分镜或素材的项目不能直接换上传文件，先新建项目。

参考视频需要 ffmpeg，分析需要图像接口。转写需要配置实际转写服务，未转写时不能声称已经听懂对白。视频解析与生成是不同阶段；上传不会自动提交成片任务。

## 数据存放和备份

cache_root 下保存项目、素材、输出和主动保存的偏好；config.json / secrets.json 保留在部署目录。源码版本管理不备份这些数据，需单独备份缓存及配置。不要在程序运行中直接编辑 session.json，也不要删除 unknown 任务来绕过重交保护。

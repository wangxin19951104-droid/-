# 本次检查记录

交付日期：2026-10-12（Asia/Shanghai）。这是源码整理与本地检查记录。远程上传进度见仓库提交记录，CI 结果见 Actions；源码上传不代表生产部署。

## 已完成的实际检查

- 对现用桌面版 server、核心模块、网页和六份导演 Skill 做源码清点与读取。
- 4 段网页 JavaScript（journey.js、intelligence.js 及 index.html 内联脚本）由 Node vm.Script 解析通过；tools/check_web.mjs 本身也已执行。
- config.example.json / secrets.example.json 可解析，示例 API 密钥为空。
- 使用显式文件清单构建目录，未复制 config.json、secrets.json、session.json、项目、素材、缓存、日志或 Python 缓存。
- 文本凭据前缀与私钥模式扫描未命中；这项扫描不是对任意未知凭据的完整证明，排除实际私有文件是主要保护。
- 批处理内容使用 ASCII 与 CRLF；Git 属性约定批处理 CRLF、源码 LF。
- 图片客户端纳入本仓库，凭据读取仅使用显式本地来源；图片输出通过 ComfyUI /view 读取。
- 视频输出目录增加 comfy_output_dir 配置，移除固定个人桌面路径。完整视频链路要求主机可以访问 ComfyUI 输出目录。

## 未运行或尚未完成

- Python 测试尝试执行时，终端因 Windows 沙箱执行限制未能启动进程，因此所有 Python 回归检查均未获得运行结果，包括新上传表格与多人回归检查。
- GitHub Actions 工作流已编写。本地没有运行 GitHub 工作流；远程结果以 Actions 中对应提交的实际运行记录为准。
- 没有调用收费的模型、生图、视频生成、解析或转写接口。
- 没有启动仓库准备版、替换桌面应用或改变原配置 / 缓存；实际启动与同事网络访问需部署时验证。
- 已通过公开 API 核实远程仓库为 Public。Windows 终端执行限制阻止了代理直接运行 Git；后续使用用户已登录的 GitHub 网页上传整理后的源码。

## 下次验证入口

在独立目录安装 Python / Pillow 和 FFmpeg 后，执行 python tools/run_checks.py；它会运行本地回归，网络仅允许测试创建的本地 HTTP 服务。执行 node tools/check_web.mjs 检查网页脚本。

测试覆盖提示词确认与原文提交、引用与上下文变更失效、全阶段 Skill、局部计划、计费任务幂等、多项目占用、表格读取、参考视频抽帧 / 转写模拟，以及新仓库配置与图片结果读取。通过这些测试也不代表真实第三方模型接口已验证。

## 远程仓库

用户选择公开仓库：https://github.com/wangxin19951104-droid/- ，默认分支 main。真实仓库名为单个连字符 -。用户已完成内置浏览器登录，后续通过网页上传源码；最新状态以仓库文件、提交记录和 Actions 为准。

## 首次远程检查与修复

首次 Actions 在 Windows 的 Python 3.11 和 3.12 分别运行 69 项回归，两组均为 68 项通过、1 项失败。失败断言测试“仅本机”模式，但默认配置已启用局域网；测试没有显式设置监听模式。已将测试固定为本机模式并在结束时恢复配置，同时验证局域网 Host 可访问、相同来源请求成功、外部来源被拒绝。未为通过测试改变程序的局域网行为。最终检查结果以 Actions 最新提交的运行状态为准。

# GitHub 公开仓库准备

已确认远程仓库：https://github.com/wangxin19951104-droid/- ，可见性 Public，默认分支 main。真实仓库名是单个连字符 -，不是此前命令中的 -1。GitHub 公开 API 可以读取该仓库。源码上传状态以 main 分支的文件和提交记录为准，自动检查结果见 Actions。

## 注册 / 登录

用 https://github.com/login 登录。Google 登录是 GitHub 身份验证入口之一；如果还未建立 GitHub 账号，按页面完成用户名 / 账号设置。密码、短信验证码和注册条款由账号本人在页面完成，不写入仓库或聊天。普通浏览器和 Codex 内置浏览器不共享登录状态。

## 创建与上传

用户已选择公开源码：任何人都可以查看和下载仓库内容。仅发布已经整理的程序源码、规则和文档；实际配置、密钥、项目素材与生成记录继续留在主机。公开仓库仍需 GitHub 账号，且不会自动提供可访问的急急网页服务。

目标仓库已经创建并公开，远程地址是 https://github.com/wangxin19951104-droid/-.git 。上传此目录的源文件，并保留 .github、.cursor、.gitignore 等隐藏目录 / 文件的层级；ZIP 是传输包，不应作为唯一源码文件上传。

在 GitHub 网页上传时，每个文件不超过 25 MiB，一次最多 100 个文件。若浏览器无法保持隐藏目录和文件层级，使用 GitHub Desktop 的 Add local repository / Publish repository，发布时选择 public。上传后核对 main 分支的 README、skills、web、tests 和 .github/workflows/checks.yml，确认 config.json / secrets.json 与项目素材不在仓库。

建议在 GitHub Settings 的 Rules / Branches 为 main 配置 PR 与检查要求；可用能力依账号方案而异，须看到设置成功才算已启用。当前交付仅包含 PR 模板和检查工作流，未更改远程保护设置、没有邀请同事。让同事仅使用网页创作无需 GitHub 账号；共同修改源码才需要仓库访问。

## 研究依据

- [GitHub 创建仓库文档](https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-new-repository)：已读取，确认私有可见性与新建流程。
- [向仓库添加文件](https://docs.github.com/en/repositories/working-with-files/managing-files/adding-a-file-to-a-repository)：已读取，确认网页单文件 25 MiB、单批 100 文件限制。
- [Actions 工作流语法](https://docs.github.com/en/actions/using-workflows/workflow-syntax-for-github-actions)：本次读取超时；配置尚待 GitHub 实际运行确认。
- 应用 rules 来自当前源码和六份 skills 文档，不把模型能力假设当作已验证接口支持。

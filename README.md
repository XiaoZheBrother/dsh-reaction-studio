# 大肥鱼陪看工作室 · dsh-reaction-studio

让 Agent 一段段看影片，积累剧情后自主决定继续看、说话或暂停分析，再把原片、语音、字幕和 Live2D 合成正常速度视频。面向离线制作，不是实时直播，也不替你发布作品。

> 本鱼也亲自参与制作啦！大家可以拿去用，给自己的小鱼搭个陪看房间。如果帮到你，麻烦给本鱼一颗星星 ⭐ 呗，求求啦～ —— 大肥鱼

当前 **0.1.0-alpha.1 开发预览**。核心流程在本机完成过完整一集制作；新版音画理解做过三分钟样片。提取后的安装包经过测试，不代表任意模型和新电脑都完成了实机验收。

## 能做什么

- **观察与开口分离**：连续积累事件，记得刚说了什么、说了多久；不设置固定发言次数或冷却时间。
- **只看已发生内容**：画面、字幕和听觉证据按时间公开，不预读结局。可回看最近内容。
- **自主表演**：复用直播插件的表情、动作与退出动作控制；可以保持原样，没有“惊讶就必须做某动作”的规则。
- **自主暂停分析**：长话可暂停原片，讲完继续；短反应在对应位置叠加。可选择片尾感想。
- **统一制作时间轴**：正常速度原片、正常语速、24 fps 导出、多行字幕和口型；原片音量保持不压低。
- **可续作任务**：保存观看记录、选择、声音和制作状态；重复调用同一任务 ID 不重复启动。
- **可选听觉实验**：时间戳转写、匿名声音候选和人物归属依据。不把当前出镜人物直接当作说话者。

## 安装

需要 DSH 0.2.1-rc.5 或兼容版本、Node.js 22.19+、Python 3.11+、Chromium，以及已经可用的鲸语本机模型服务。先安装配套 [dsh-live-studio](https://github.com/XiaoZheBrother/dsh-live-studio) **0.2.0-alpha.1**，它提供人设/记忆/前缀读取与 Live2D 公共组件；只做陪看时不用启用直播服务。

在同一个 DSH home / profile 中安装两个仓库的 Release tgz，先直播插件、后本插件：

```powershell
$env:DSH_HOME = 'D:\my-agent-data'
dsh plugin --profile web add '<dsh-live-studio tgz 的绝对路径>'
dsh plugin --profile web add '<dsh-reaction-studio tgz 的绝对路径>'
```

也可分别克隆源码执行 `npm pack`。不要把制作目录、密钥、影片或模型放进插件源码目录。升级插件不应删除用户数据目录。

在本插件目录创建媒体环境：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
```

复制 [配置例子](examples/config.json) 到自己的数据目录，填写绝对路径。`chromium` 填 Playwright 下载的浏览器可执行文件位置；`materials` 仅列允许 Agent 使用的素材及最大秒数。`home`、`persona` 指向现有人设和数据，不复制、不重建记忆。`jingyu_url` 仅允许本机 HTTP；当前适配神宫凉子鲸鱼娘模型的命名，不承诺任意 Live2D 即插即用。模型与运行库需自行准备，模型服务要提供 `/model/`、`/vendor/` 静态资源。

模型请求沿用直播插件的 DeepSeek 调用和 `home/bili-duty/comment-prefill.json` 开关/填充词，API 密钥通过环境或现有 DSH 凭据读取，不写在示例里。Edge TTS 和模型请求需要网络。

在 DSH 插件设置中配置 `python` 为媒体环境 Python 的绝对路径，`configPath` 为刚才配置文件绝对路径，再设 `enabled: true`。**仅注册工具，不自动观看、开播或运行 B 站任务。**

## 主对话怎么用

可以说：“先列出可陪看的素材，然后用 episode01 做三分钟样片，什么时候开口、暂停或用表情由你决定，先不发布。”

| 工具 | 用途 |
|---|---|
| reaction_catalog | 查看授权素材和已有任务 |
| reaction_start | 启动/恢复任务，支持裁切秒数、片尾感想 |
| reaction_status | 查询进度、请求回执和本地成片路径 |
| reaction_observation | 读取已经看过的剧情理解和近期发言 |
| reaction_pause_analysis | 请求在安全边界暂停展开，讲完继续 |
| reaction_replay | 回看最近 1–10 秒，不提前看剧情 |

工具回执不是成片完成通知；用原任务 ID 查询状态。不要同时启用旧的手动 MCP 注册与本插件。Windows 的 `launcher: windows-task` 使用当前用户独立计划任务；没有重复触发器，同一个数据目录一次制作一个任务。关闭对话不会取消正在制作的任务；停用插件也不会自动结束独立任务，需要在系统任务计划程序停止对应 `Feiyu-Reaction-<job_id>`。请在任务空闲后升级。

## 可选听觉信息

另建 Python 环境安装 `backend/requirements-hearing.txt`，配置 `hearing_python` 和 `hearing_models`，新任务才会启用音画事件模式。已有任务继续使用创建时的配置，不覆盖历史。

详见 [音画理解及参考项目](docs/reaction-audiovisual.md)。本地 ASR 默认日语 small 模型；声音候选在音乐、短句、混音和动画声线下容易分裂，置信度未校准，未知人物应保留未知。**不启用 hearing 时使用旧的视觉观察流程，不等于已完成音画识别。**

## 与其他插件的分工

- [直播工作室](https://github.com/XiaoZheBrother/dsh-live-studio)：直播、语音、人设读取、可复用 Live2D 表演组件。
- [成长插件](https://github.com/XiaoZheBrother/dsh-agent-growth)：长期学习和经验复查。本插件只记录制作任务，不自动改写正式记忆。
- [B 站工作台](https://github.com/XiaoZheBrother/dsh-bilibili-dafeiyu)：账号、作品、互动和发布管理。

原片、声音、输出视频、模型与私人数据不随包分发。使用自己有权处理的素材；缩小原片画面不意味着获得公开传播授权。

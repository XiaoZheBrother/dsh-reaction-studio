# 连续陪看与制作边界

本次公开连续理解、归属证据、观看决策、上下文预算和合成改进。保留已有 DSH 六个工具；安装不会启动观看、评论或直播任务。

## 两条入口

- 主对话 `reaction_start` 继续使用 `reaction_produce.py`，配置快照中的 `interaction_version` 可选择交互版本；不指定仍为 3。版本 4 分离理解和表达，版本 5 增加连续剧情工作状态。已有任务不自动更换算法。
- 新的关系证据流程是显式运行的实验入口 `python backend/reaction_trace.py --job <job.json>`，并非六个工具自动启用。设置 `relation_graph: true` 后分别记录画面人物、匿名声音、叙述主体、对白、动作及其关系；判断允许修订，保留原始证据和失败断点。

关系流程的任务文件需提供 `home`、`persona`、`output`、`frames`、`hearing` 的绝对路径，以及 `start_seconds`、`seconds`（结束位置）、`step` 和 `voice_chars_per_second`。`frames` 使用从 1 开始的六位数字 JPG，每秒一帧；听觉文件为带时间戳的 `cues`。运行前将配套直播插件的 `backend` 加入 `PYTHONPATH`。先在授权素材的短片段试运行，模型调用会产生费用。

## 她自己决定什么

连续观察保留自己的看法、关注点和近期发言。可以继续观看、自发反应、暂停分析或回看证据，没有固定发言频率或情绪动作规则。影片字幕和声音属于影片观察，不作为搭档的真实提问。人物共现或声音聚类不足以证明台词归属；事实检查不要求主观感受得到证明。

关系流程可设置 `reaction_prefix` 作为观看场景前缀，但仍服从工作台原有总开关，不改写人设和正式记忆。

## 从记录到声音

`reaction_trace_dub.py` 消费已经审阅的完整 `trace.json`。review 文件必须包含 `status: accepted_for_preview` 和与该文件一致的 `trace_sha256`，通过 `--job --review --trace --production --output` 指定输入输出。它需要另行配置本地 IndexTTS2 音频模块，仓库不提供模型、参考音频或该私有模块。

观看时的暂停选择优先。配音较长本身不触发重新决定暂停；仅在真实语音重叠时交回角色选择等待或暂停。字幕按面板容量换行，语音、口型和动作共享时间轴，原片音量不因角色说话自动降低。片尾支持读取这次关系流程的观看记录生成感想。

## 预算与听觉限制

离线请求统一经过 `reaction_context.py`：人设、当前证据和推理前缀保留，历史与可选记忆按预算投影和去重，完整记录留在磁盘。`reaction_usage.py` 提供按阶段汇总 provider 用量的函数；预算估算不等于精确计费，缺失 usage 的请求不能算作零消耗。

可选 `reaction_pyannote.py` 提供对齐及 pyannote/CAM++ 后端，依赖见 `requirements-pyannote.txt`、`requirements-campplus.txt`，详见命令 `--help`。pyannote 所需模型权限需用户自行取得；CAM++ 路径不依赖 Hugging Face 账号，但仍需模型与 SpeakerLab 环境。两者都不能保证辨认内心独白或人物身份，音乐、重叠声音和短句仍可能导致误判。

本次自动测试验证数据边界、决策保留、断点和时间轴；不代表任意素材、模型或新电脑已完成真实生成验收。发布仍由用户确认，工具不自动投稿。

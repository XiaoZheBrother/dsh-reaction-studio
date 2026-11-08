# 持续观察与自主开口（本地试验）

本流程不设置发言配额或冷却秒数。感知层积累连续事件、对白与角色归属证据，不写台词；形成阶段结果或出现突发变化时，才让角色结合累计经历及自己的发言占用情况决定继续看、开口或回看。同一事件结果只审议一次，正在说话时继续观察，不排队下一条台词。

30/60/120 秒窗口只用于展示近期声音占比，不作为发言门槛。角色仍沿用原人设、记忆读取和工作台推理前缀。感知层不使用角色口吻，也不修改正式记忆。

## 听觉链路

独立 Python 环境安装 `backend/requirements-hearing.txt`。Windows 可用 PyTorch 官方 CPU wheel，避免占用 Live2D 的显存。运行：

```powershell
python backend/reaction_hearing.py --video '<原片绝对路径>' --seconds 180 --output '<hearing.json绝对路径>' --models '<模型缓存绝对路径>'
```

使用 faster-whisper small 转写日语原声，记录段落和单词时间戳；SpeechBrain ECAPA 提取匿名声音候选。当前是保守的顺序声纹匹配，不是完整的重叠语音分离系统。配乐、短句、多声音混合和动画声线都会影响结果。相似度不是概率，新声音编号也不代表已经验证为不同人物。

每个音频处理块的结果只在该块听完后公开给感知层（`available_at`），且声纹只与之前的候选比较，不能泄露后续剧情。角色署名需引用 cue_id，附自评置信度和音频/语言/口型依据；仅“画面里出现此人”或背景关系不足以署名。未知和矛盾保留在记录中，自评置信度不声称经过统计校准。

## 接入制作工具

MCP 服务配置可增加 `hearing_python`（独立环境的 Python 绝对路径）和 `hearing_models`（本地模型缓存）。新任务会先生成听觉证据，再启动事件积累流程；原任务继续使用它创建时的配置，不更换已存在的观看记录。也可在制作 job 中传入已有的 `hearing` 文件。

有 `attention_version: 3` 的观看记录会保留 observation、角色归属依据、是否进入发言审议，以及每条真实语音的时间和时长。原字幕、原声音量、正常速度合成和自主暂停工具保持原有行为。不公开发布，也不启动 B 站值班任务。

## 参考与边界

- [WhisperX](https://github.com/m-bain/whisperX)：参考转写、强制对齐和说话人分离的分层方式；本试验没有宣称采用了 WhisperX 的强制对齐。
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper)：实际使用的本地 ASR。
- [SpeechBrain ECAPA](https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb)：实际使用的声音特征模型；其训练域不等同于日语动画。
- [pyannote](https://github.com/pyannote/pyannote-audio)：完整说话人分离可选路线，需要满足对应模型的访问条件；当前未部署。
- [LiveKit turn detection](https://docs.livekit.io/agents/logic/turns/turn-detector/)：参考“连续感知”和“语义边界”分开处理的设计，不把一句对白结束自动等同于角色应该回应。

这些组件不能直接解决“角色是否有趣”或准确命名动漫角色。最终仍需样片判断发言密度、理解和观看体验。

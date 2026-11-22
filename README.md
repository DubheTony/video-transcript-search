# 视频知识提取（vkn）

[中文](README.md) | [English](README.en.md)

本地命令行工具：从视频、录音或视频链接获取带时间戳的文字稿，建立可搜索的本地索引，再按关键词或时间点导出片段。能拿到平台字幕时优先用字幕；否则提取音频并做本地语音识别。

这个仓库只提供程序源码。原始音视频、字幕、转写稿、索引数据库、模型权重和对比资料均不包含在内。

## 环境与安装

- Python 3.11+；从本仓库根目录执行 `python -m pip install -e .`，以可编辑模式安装。目前主要在 Windows 验证；程序按源码位置定位数据和模型目录，尚未验证普通 wheel 安装后的目录布局。
- `ffmpeg`、`ffprobe` 在 `PATH` 上；处理链接时还需要 `yt-dlp`。若安装了 `videodl`，程序会对部分非 YouTube 链接先尝试用它下载音频，失败后仍会尝试 `yt-dlp`。
- 本地 ASR 模型需自行准备：`模型/sensevoice/` 存在时，中文默认用 SenseVoice（该引擎在脚本里固定使用 CPU）；否则使用 Whisper。Whisper 读取本地缓存（`local_files_only=True`），**不会在首次使用时自动下载模型**；可预先缓存默认模型 `large-v3-turbo`，或把兼容 faster-whisper 的 CTranslate2 模型放在自己的本地目录，并在 `add` 时传 `--engine whisper --model 本地模型目录`。模型的获取和使用须遵守各自许可证；没有准备模型、也没有可用字幕时，首次转写无法完成。
- GPU 运行依赖列在 [pyproject.toml](pyproject.toml) 中；不使用 GPU 时可以通过 `--device cpu` 运行 Whisper。模型体积及首次安装所需空间可能较大。

## 常用命令

安装后可用 `vkn`，也可用 `python -m vkn`：

```bash
vkn add "path/to/video.mp4"
vkn add "https://www.youtube.com/watch?v=VIDEO_ID" --proxy ""
vkn add --batch "input-list.txt"
vkn search "关键词" --top 5
vkn show VIDEO_ID --at 12:30
vkn export --video VIDEO_ID --at 12:30 --span 3
vkn compose VIDEO_ID
```

链接取回目前默认使用 `http://127.0.0.1:9674` 代理；你的电脑若没有运行这个代理，可传 `--proxy ""` 改为直连，或传 `--proxy http://主机:端口` 指定自己的代理。链接可用性取决于平台、地区、网络和下载工具版本。默认不处理播放列表。

`add` 在项目内的 `数据/VIDEO_ID/` 写入 `transcript.srt`、`transcript.jsonl`、`transcript.txt` 和 `meta.json`；已有转写时默认跳过，`--force` 会重新生成并覆盖这些结果。**`add` 不会自动生成 `notes.md`**，需要时另执行 `vkn compose VIDEO_ID`（再次运行会改写已有笔记）。完成后通常会尝试更新 `索引/` 下的 SQLite FTS5 索引，也可以手动运行 `vkn index`。搜索支持分词和拼音匹配；片段时间、章节切分是估算结果，重要内容要回听原音频。

### 说话人标注与清理

`vkn diarize VIDEO_ID` 需要保留该条记录的 `audio.wav`，并自行准备 `模型/diarization/` 所需模型；`--align-only` 只把既有文字按时间分配给说话人。不要在需要说话人标注的记录上使用 `add --delete-audio`。

`vkn clean VIDEO_ID --dry-run` 可以预览待清理文件。**不带 `--dry-run` 时会删除项目内 `_源材料/VIDEO_ID/` 整个目录（若存在）及 `数据/VIDEO_ID/audio.wav`，不会删除传入的项目外本地视频文件**；但如果你自行把原始文件放进了该 `_源材料/VIDEO_ID/` 目录，它也会一起被删。程序不会替你确认文字稿是否正确或是否已备份。请自行核对后再执行；尤其不要把 `clean --all` 当作例行命令。

## 本地数据与隐私

`数据/` 可能包含会议录音、完整转写稿、说话人信息；`索引/` 保存可搜索文字，`meta.json` 可能记录原始本机路径或视频链接。它们都不属于源码，不要提交到公开仓库。所用视频、字幕、模型的版权及使用范围由各自来源决定；工具本身不授予转载这些材料的权限。

本项目源码采用 [MIT 许可证](LICENSE)；不包括第三方模型、媒体和下载工具。

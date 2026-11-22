# Video Knowledge Extraction (vkn)

[中文](README.md) | [English](README.en.md)

A local command-line tool that turns videos, audio recordings, or video links into timestamped transcripts, builds a searchable local index, and exports excerpts by keyword or time. It uses platform subtitles when available; otherwise, it extracts audio and runs local speech recognition.

This repository contains source code only. Original video and audio, subtitles, transcripts, index databases, model weights, and comparison materials are not included.

## Requirements and Installation

- Python 3.11+. From the repository root, run `python -m pip install -e .` for an editable installation. The tool has mainly been tested on Windows. It locates data and model directories relative to the source code; the directory layout after a regular wheel installation has not yet been verified.
- `ffmpeg` and `ffprobe` must be on `PATH`; processing links also requires `yt-dlp`. If `videodl` is installed, the tool first tries it to download audio from some non-YouTube links; if that fails, it still tries `yt-dlp`.
- You must provide a local ASR model: when `模型/sensevoice/` exists, Chinese defaults to SenseVoice (the script fixes this engine to CPU); otherwise, it uses Whisper. Whisper reads from the local cache (`local_files_only=True`) and **does not automatically download a model on first use**. You can pre-cache the default model, `large-v3-turbo`, or put a CTranslate2 model compatible with faster-whisper in your own local directory and pass `--engine whisper --model 本地模型目录` to `add`. Obtain and use each model in accordance with its license. Without a prepared model or usable subtitles, the first transcription cannot complete.
- GPU runtime dependencies are listed in [pyproject.toml](pyproject.toml). If you are not using a GPU, Whisper can run with `--device cpu`. Models and the initial installation may require substantial disk space.

## Common Commands

After installation, use `vkn` or `python -m vkn`:

```bash
vkn add "path/to/video.mp4"
vkn add "https://www.youtube.com/watch?v=VIDEO_ID" --proxy ""
vkn add --batch "input-list.txt"
vkn search "关键词" --top 5
vkn show VIDEO_ID --at 12:30
vkn export --video VIDEO_ID --at 12:30 --span 3
vkn compose VIDEO_ID
```

Fetching links currently uses `http://127.0.0.1:9674` as the default proxy. If that proxy is not running on your computer, pass `--proxy ""` to connect directly, or `--proxy http://主机:端口` to specify your own proxy. Whether a link works depends on the platform, region, network, and downloader version. Playlists are not processed by default.

`add` writes `transcript.srt`, `transcript.jsonl`, `transcript.txt`, and `meta.json` to `数据/VIDEO_ID/` inside the project. By default, it skips a record that already has a transcript; `--force` regenerates and overwrites those results. **`add` does not automatically create `notes.md`**; run `vkn compose VIDEO_ID` separately if you need it (running it again rewrites existing notes). After processing, the tool usually attempts to update the SQLite FTS5 index under `索引/`; you can also run `vkn index` manually. Search supports word segmentation and pinyin matching. Excerpt timestamps and chapter boundaries are estimates; listen to the original audio to check important content.

### Speaker Labels and Cleanup

`vkn diarize VIDEO_ID` requires the record's `audio.wav` to be retained, and you must provide the models required under `模型/diarization/`. `--align-only` only assigns existing text to speakers by time. Do not use `add --delete-audio` on records that need speaker labels.

`vkn clean VIDEO_ID --dry-run` previews files slated for removal. **Without `--dry-run`, it deletes the entire project-local `_源材料/VIDEO_ID/` directory (if present) and `数据/VIDEO_ID/audio.wav`; it does not delete an external local video file passed as input.** If you placed original files in `_源材料/VIDEO_ID/` yourself, those will be deleted too. The tool does not check for you whether the transcript is correct or backed up. Check it yourself before running cleanup, and in particular, do not treat `clean --all` as a routine command.

## Local Data and Privacy

`数据/` may contain meeting recordings, full transcripts, and speaker information. `索引/` stores searchable text, and `meta.json` may record local source paths or video links. These are not source code and should not be committed to a public repository. Copyright and permitted uses of videos, subtitles, and models depend on their respective sources; the tool does not grant permission to republish them.

The project's source code is under the [MIT License](LICENSE); this does not include third-party models, media, or download tools.

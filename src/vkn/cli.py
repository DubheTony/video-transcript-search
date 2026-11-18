"""命令行入口：本地文件 / 链接 / 批量，统一产出 srt/jsonl/txt。"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from . import __version__, config, diarize as diarize_mod, download, index as index_mod, subs
from .asr import (
    Segment,
    fmt_clock,
    load_model,
    run_asr,
    run_sensevoice,
    write_jsonl,
    write_srt,
    write_txt,
)
from .audio import extract_audio, probe_duration
from .clean import clean
from .compose import compose_notes
from .export import export_at, export_search
from .fetch import FetchError, is_url, make_id, make_video_id, resolve_media, write_meta


def _setup_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _wanted_langs(video_language: str | None) -> list[str]:
    """视频是英文时先找英文，否则先找中文。"""
    if (video_language or "").lower().startswith("en"):
        return ["en", "en-US", "en-GB", "zh-Hans", "zh-CN", "zh"]
    return ["zh-Hans", "zh-CN", "zh", "en"]


def _choose_engine(args: argparse.Namespace, language: str | None) -> str:
    """auto：英文用 Whisper，中文/未知用 SenseVoice（模型存在时）。"""
    if args.engine != "auto":
        return args.engine
    if (language or "").lower().startswith("en"):
        return "whisper"
    if config.SENSEVOICE_DIR.is_dir():
        return "sensevoice"
    return "whisper"


def _write_outputs(out_dir: Path, segments: list, meta: dict) -> None:
    write_srt(out_dir / "transcript.srt", segments)
    write_jsonl(out_dir / "transcript.jsonl", segments)
    write_txt(out_dir / "transcript.txt", segments)
    meta["segments"] = len(segments)
    meta["generated_at"] = datetime.now().isoformat(timespec="seconds")
    write_meta(out_dir / "meta.json", meta)


def _process_local(raw: str, args: argparse.Namespace) -> Path:
    media = resolve_media(raw)
    video_id = make_video_id(media)
    out_dir = config.DATA_DIR / video_id
    out_dir.mkdir(parents=True, exist_ok=True)

    srt_path = out_dir / "transcript.srt"
    if srt_path.exists() and not args.force:
        print(f"已存在，跳过：{srt_path}")
        return out_dir

    wav_path = out_dir / "audio.wav"
    print(f"视频：{media.name}")
    print(f"输出：{out_dir}")
    print("抽音轨……")
    extract_audio(media, wav_path)

    progress_path = out_dir / "progress.json"
    if args.force:
        progress_path.unlink(missing_ok=True)

    engine = _choose_engine(args, args.language)
    t0 = time.time()
    load_seconds = 0.0
    if engine == "sensevoice":
        print("SenseVoice 分块识别……")
        dev = "cpu"
        model_name = "sensevoice"
        segments, duration = run_sensevoice(
            wav_path,
            config.SENSEVOICE_DIR,
            language=args.language or "zh",
            progress_path=progress_path,
        )
    else:
        dev = args.device or config.device()
        compute = config.compute_type(dev)
        model_name = args.model
        print(f"加载模型 {model_name}（{dev}/{compute}）……")
        model = load_model(model_name, dev, compute)
        load_seconds = time.time() - t0
        print("转写……")
        segments, duration = run_asr(wav_path, model, language=args.language)
    t1 = time.time()
    asr_seconds = t1 - t0 - load_seconds

    meta = {
        "id": video_id,
        "title": media.stem,
        "source": str(media),
        "platform": "local",
        "duration": duration or probe_duration(media),
        "language": args.language,
        "model": model_name,
        "device": dev,
        "engine": engine,
        "subtitle_source": "asr",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "timing": {
            "load_seconds": round(load_seconds, 1),
            "asr_seconds": round(asr_seconds, 1),
            "realtime_factor": round(duration / asr_seconds, 2) if asr_seconds and duration else None,
        },
    }
    _write_outputs(out_dir, segments, meta)
    progress_path.unlink(missing_ok=True)

    if args.delete_audio:
        wav_path.unlink(missing_ok=True)

    print(
        f"完成：{len(segments)} 段，音频 {fmt_clock(duration)}，引擎 {engine}，"
        f"耗时 {fmt_clock(asr_seconds)}（{meta['timing']['realtime_factor']}x 实时）"
    )
    if not segments:
        print("提示：没有识别到语音内容（可能是纯音乐或静音）")
    for name in ("transcript.srt", "transcript.jsonl", "transcript.txt", "meta.json"):
        print(f"  {out_dir / name}")
    return out_dir


def _process_url(url: str, args: argparse.Namespace) -> Path:
    proxy = args.proxy
    print(f"链接：{url}")
    info = download.probe(url, proxy)
    video_id = make_id(info.title, f"{info.platform}:{info.id}")
    out_dir = config.DATA_DIR / video_id
    src_dir = config.SOURCE_DIR / video_id
    out_dir.mkdir(parents=True, exist_ok=True)

    srt_path = out_dir / "transcript.srt"
    if srt_path.exists() and not args.force:
        print(f"已存在，跳过：{srt_path}")
        return out_dir

    wanted = _wanted_langs(info.language)
    manual = download.pick_lang(info.manual_langs, wanted)
    auto = download.pick_lang(info.auto_langs, wanted)
    # YouTube 元数据常常没有 language，用字幕语言推断
    video_lang = (info.language or manual or auto or "").lower()
    is_english = video_lang.startswith("en")

    segments: list | None = None
    source = ""
    dev = None
    model_name = None
    engine = None
    duration = info.duration

    if manual:
        print(f"使用人工字幕：{manual}")
        path = download.download_subs(url, src_dir, manual, proxy, auto=False)
        segments = subs.parse_subtitle(path)
        source = "manual"
    elif is_english and auto:
        print(f"使用平台自动字幕：{auto}")
        path = download.download_subs(url, src_dir, auto, proxy, auto=True)
        segments = subs.parse_subtitle(path)
        source = "auto"
    elif args.auto_subs and auto:
        print(f"使用平台自动字幕：{auto}")
        path = download.download_subs(url, src_dir, auto, proxy, auto=True)
        segments = subs.parse_subtitle(path)
        source = "auto"

    if segments is None:
        print("没有可用字幕，下载音频……")
        media = download.download_audio(url, src_dir, proxy)
        wav_path = out_dir / "audio.wav"
        extract_audio(media, wav_path)

        if is_english:
            language = "en"
        elif video_lang.startswith("zh"):
            language = "zh"
        else:
            language = args.language or None
        progress_path = out_dir / "progress.json"
        if args.force:
            progress_path.unlink(missing_ok=True)
        engine = _choose_engine(args, language)
        if engine == "sensevoice":
            print("SenseVoice 分块识别……")
            dev = "cpu"
            model_name = "sensevoice"
            segments, duration = run_sensevoice(
                wav_path,
                config.SENSEVOICE_DIR,
                language=language or "zh",
                progress_path=progress_path,
            )
        else:
            dev = args.device or config.device()
            compute = config.compute_type(dev)
            model_name = args.model
            print(f"加载模型 {model_name}（{dev}/{compute}）……")
            model = load_model(model_name, dev, compute)
            print(f"转写（language={language or 'auto'}）……")
            segments, duration = run_asr(wav_path, model, language=language)
        source = "asr"
        if args.delete_audio:
            wav_path.unlink(missing_ok=True)
            media.unlink(missing_ok=True)

    meta = {
        "id": video_id,
        "title": info.title,
        "source": info.url,
        "url": url,
        "platform": info.platform,
        "platform_id": info.id,
        "uploader": info.uploader,
        "duration": duration,
        "language": info.language or manual or auto or args.language,
        "model": model_name,
        "device": dev,
        "engine": engine,
        "subtitle_source": source,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    _write_outputs(out_dir, segments, meta)
    (out_dir / "progress.json").unlink(missing_ok=True)
    print(f"完成：{len(segments)} 段，字幕来源 {source}")
    if not segments:
        print("提示：没有识别到语音内容（可能是纯音乐或静音）")
    for name in ("transcript.srt", "transcript.jsonl", "transcript.txt", "meta.json"):
        print(f"  {out_dir / name}")

    if args.compare_subs:
        _compare_subs(info, out_dir, src_dir, proxy, args, segments, source, video_lang)
    return out_dir


def _compare_subs(
    info: download.LinkMeta,
    out_dir: Path,
    src_dir: Path,
    proxy: str | None,
    args: argparse.Namespace,
    primary: list,
    primary_source: str,
    video_lang: str,
) -> None:
    """把自动字幕和本地 ASR 放在一起，输出粗略的质检报告。"""
    wanted = _wanted_langs(info.language)
    other: list | None = None
    other_source = ""
    try:
        if primary_source == "asr":
            lang = download.pick_lang(info.auto_langs, wanted)
            if not lang:
                print("对比跳过：没有自动字幕")
                return
            path = download.download_subs(info.url, src_dir, lang, proxy, auto=True)
            other = subs.parse_subtitle(path)
            other_source = f"auto:{lang}"
        else:
            media = download.download_audio(info.url, src_dir, proxy)
            wav_path = out_dir / "audio.wav"
            extract_audio(media, wav_path)
            dev = args.device or config.device()
            model = load_model(args.model, dev, config.compute_type(dev))
            if video_lang.startswith("en"):
                language = "en"
            elif video_lang.startswith("zh"):
                language = "zh"
            else:
                language = args.language or None
            other, _ = run_asr(wav_path, model, language=language)
            other_source = "asr"
    except Exception as exc:
        print(f"对比失败：{exc}")
        return

    pairs = list(zip(primary, other))
    sims = [
        difflib.SequenceMatcher(None, a.text, b.text).ratio()
        for a, b in pairs
    ]
    avg = sum(sims) / len(sims) if sims else 0.0
    lines = [
        "# 字幕对比",
        "",
        f"- 主输出：{primary_source}，{len(primary)} 段",
        f"- 对比：{other_source}，{len(other)} 段",
        f"- 按顺序配对 {len(pairs)} 组，平均文本相似度 {avg:.3f}",
        "- 相似度只作粗略参考，不代表准确率",
        "",
        "## 抽样",
        "",
        "| 主输出 | 对比 |",
        "|---|---|",
    ]
    for a, b in pairs[:10]:
        lines.append(f"| {a.text} | {b.text} |")
    (out_dir / "compare_subs.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"对比报告：{out_dir / 'compare_subs.md'}")


def cmd_add(args: argparse.Namespace) -> int:
    config.ensure_dirs()

    inputs = list(args.input)
    if args.batch:
        batch_path = Path(args.batch)
        if not batch_path.exists():
            print(f"清单不存在：{batch_path}", file=sys.stderr)
            return 2
        for line in batch_path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                inputs.append(line)
    if not inputs:
        print("没有输入。用法：vkn add <文件或链接> ……", file=sys.stderr)
        return 2

    failures: list[tuple[str, str]] = []
    for raw in inputs:
        try:
            if is_url(raw):
                _process_url(raw, args)
            else:
                _process_local(raw, args)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            print(f"失败：{raw}\n  {exc}", file=sys.stderr)
            failures.append((raw, str(exc)))

    if failures:
        print(f"\n完成 {len(inputs) - len(failures)}/{len(inputs)}，失败 {len(failures)} 条")
        for raw, err in failures:
            print(f"  {raw}: {err}")
        return 1

    try:
        videos, chunks = index_mod.build()
        print(f"索引：{videos} 个视频，{chunks} 个片段 → {index_mod.DB_PATH}")
    except Exception as exc:
        print(f"索引失败：{exc}", file=sys.stderr)
    return 0


def _parse_time(text: str) -> float:
    parts = [float(p) for p in text.split(":")]
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    raise ValueError(f"时间格式不对：{text}")


def cmd_index(args: argparse.Namespace) -> int:
    videos, chunks = index_mod.build()
    print(f"已建索引：{videos} 个视频，{chunks} 个片段")
    print(f"  {index_mod.DB_PATH}")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    hits = index_mod.search(args.query, top_k=args.top)
    if not hits:
        print("没有命中")
        return 0
    for hit in hits:
        print(
            f"[{fmt_clock(hit['start'])}-{fmt_clock(hit['end'])}] "
            f"{hit['title']}  ({hit['video_id']})"
        )
        print(f"  {hit['text'][:200]}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    at = _parse_time(args.at)
    hits = index_mod.show(args.video_id, at, span=args.span * 60)
    if not hits:
        print("没有找到该时间点附近的片段")
        return 0
    for hit in hits:
        print(f"[{fmt_clock(hit['start'])}-{fmt_clock(hit['end'])}] {hit['text']}")
    return 0


def cmd_compose(args: argparse.Namespace) -> int:
    out = compose_notes(config.DATA_DIR / args.video_id)
    print(out)
    return 0


def cmd_diarize(args: argparse.Namespace) -> int:
    video_dir = config.DATA_DIR / args.video_id
    wav = video_dir / "audio.wav"
    jsonl = video_dir / "transcript.jsonl"
    meta_path = video_dir / "meta.json"
    if not wav.exists():
        print("缺少 audio.wav；先运行 vkn add", file=sys.stderr)
        return 1

    embedding = config.DIARIZATION_DIR / (
        "3dspeaker_speech_eres2netv2_sv_zh-cn_16k-common.onnx"
        if args.embedding == "eres2netv2"
        else "3dspeaker_speech_campplus_sv_zh-cn_16k-common.onnx"
    )
    print(
        f"说话人分离（{args.embedding}，阈值 {args.threshold}，"
        f"人数 {args.num_clusters or '自动'}）……"
    )
    t0 = time.time()
    speakers = diarize_mod.run_diarization(
        wav,
        threshold=args.threshold,
        num_clusters=args.num_clusters,
        embedding_model=embedding,
    )
    speakers = diarize_mod.clean_speaker_segments(
        speakers, min_duration=args.min_duration
    )

    if args.align_only:
        if not jsonl.exists():
            print("缺少 transcript.jsonl，无法只做对齐", file=sys.stderr)
            return 1
        segments = []
        for line in jsonl.read_text(encoding="utf-8").splitlines():
            if line.strip():
                item = json.loads(line)
                segments.append(
                    Segment(float(item["start"]), float(item["end"]), item["text"])
                )
        rows = diarize_mod.assign_speakers(segments, speakers)
    else:
        print(f"按 {len(speakers)} 个说话人段重新识别……")
        rows = diarize_mod.transcribe_by_speaker(
            wav,
            speakers,
            config.SENSEVOICE_DIR,
            language=args.language,
        )
    t1 = time.time()

    diarize_mod.write_speakers_jsonl(video_dir / "transcript.speakers.jsonl", rows)
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    diarize_mod.write_speakers_md(
        video_dir / "notes.speakers.md",
        meta.get("title", args.video_id),
        rows,
    )

    used = sorted({row["speaker"] for row in rows if row["speaker"] >= 0})
    print(
        f"完成：{len(used)} 个说话人，{len(rows)} 段，耗时 {fmt_clock(t1 - t0)}"
    )
    print(f"  {video_dir / 'transcript.speakers.jsonl'}")
    print(f"  {video_dir / 'notes.speakers.md'}")
    return 0


def cmd_clean(args: argparse.Namespace) -> int:
    return clean(args.video_id, all_=args.all, dry_run=args.dry_run)


def cmd_export(args: argparse.Namespace) -> int:
    if args.video:
        if not args.at:
            print("--video 需要配合 --at 使用", file=sys.stderr)
            return 2
        text = export_at(args.video, _parse_time(args.at), span_minutes=args.span)
    else:
        text = export_search(args.search, top_k=args.top)

    if not text:
        print("没有可导出的内容")
        return 0
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(args.out)
    else:
        print(text, end="")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vkn", description="视频知识提取")
    parser.add_argument("--version", action="version", version=f"vkn {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="处理本地文件或链接：字幕优先，必要时转写")
    p_add.add_argument("input", nargs="*", help="本地文件或视频链接")
    p_add.add_argument("--batch", metavar="FILE", help="批量清单，一行一个链接/路径")
    p_add.add_argument("--model", default=config.DEFAULT_MODEL)
    p_add.add_argument("--language", default=config.DEFAULT_LANGUAGE,
                       help="本地/中文视频的语言，默认 zh；传空字符串则自动检测")
    p_add.add_argument("--device", choices=["cuda", "cpu"], default=None)
    p_add.add_argument("--engine", choices=["auto", "whisper", "sensevoice"], default="auto",
                       help="auto：英文 Whisper、中文 SenseVoice（模型存在时）")
    p_add.add_argument("--force", action="store_true", help="重跑已完成的转写")
    p_add.add_argument("--delete-audio", action="store_true",
                       help="转写完成后删除 audio.wav 和下载的原始音频")
    p_add.add_argument("--auto-subs", action="store_true",
                       help="中文视频也允许使用平台自动字幕")
    p_add.add_argument("--compare-subs", action="store_true",
                       help="输出自动字幕与本地 ASR 的对比报告")
    p_add.add_argument("--proxy", default=download.DEFAULT_PROXY,
                       help=f"链接取回代理，默认 {download.DEFAULT_PROXY}；传空字符串禁用")
    p_add.set_defaults(func=cmd_add)

    p_index = sub.add_parser("index", help="重建全文索引")
    p_index.set_defaults(func=cmd_index)

    p_search = sub.add_parser("search", help="检索关键词")
    p_search.add_argument("query")
    p_search.add_argument("--top", type=int, default=10)
    p_search.set_defaults(func=cmd_search)

    p_show = sub.add_parser("show", help="查看某个时间点附近的片段")
    p_show.add_argument("video_id")
    p_show.add_argument("--at", required=True, help="时间点，如 12:30 或 01:02:03")
    p_show.add_argument("--span", type=float, default=3, help="前后分钟数，默认 3")
    p_show.set_defaults(func=cmd_show)

    p_compose = sub.add_parser("compose", help="重新生成 notes.md")
    p_compose.add_argument("video_id")
    p_compose.set_defaults(func=cmd_compose)

    p_export = sub.add_parser("export", help="导出片段为纯文本")
    group = p_export.add_mutually_exclusive_group(required=True)
    group.add_argument("--video", help="视频 ID")
    group.add_argument("--search", help="检索词")
    p_export.add_argument("--at", help="--video 时的时间点，如 20:00")
    p_export.add_argument("--span", type=float, default=3, help="前后分钟数")
    p_export.add_argument("--top", type=int, default=5)
    p_export.add_argument("--out", help="写入文件；默认打印到 stdout")
    p_export.set_defaults(func=cmd_export)

    p_clean = sub.add_parser("clean", help="删除源媒体，保留文字稿")
    group = p_clean.add_mutually_exclusive_group(required=True)
    group.add_argument("video_id", nargs="?", help="只清理这个视频的源媒体")
    group.add_argument("--all", action="store_true", help="清理所有源媒体")
    p_clean.add_argument("--dry-run", action="store_true", help="只列出将删除的内容")
    p_clean.set_defaults(func=cmd_clean)

    p_diarize = sub.add_parser("diarize", help="给已有转写加说话人")
    p_diarize.add_argument("video_id")
    p_diarize.add_argument("--threshold", type=float, default=0.5,
                           help="聚类阈值，越大越容易合并成同一人")
    p_diarize.add_argument("--num-clusters", type=int, default=-1,
                           help="已知人数时直接指定，默认自动判断")
    p_diarize.add_argument("--embedding", choices=["eres2netv2", "campplus"],
                           default="eres2netv2",
                           help="说话人嵌入模型；CAM++ 更快但完整会议容易丢第二人")
    p_diarize.add_argument("--language", default="zh", help="SenseVoice 语言，默认 zh")
    p_diarize.add_argument("--min-duration", type=float, default=0.5,
                           help="过滤短于该秒数的噪声段")
    p_diarize.add_argument("--align-only", action="store_true",
                           help="不重新识别，只把已有转写按时间对齐到说话人")
    p_diarize.set_defaults(func=cmd_diarize)
    return parser


def main(argv: list[str] | None = None) -> int:
    _setup_console()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (FetchError, KeyboardInterrupt) as exc:
        print(f"\n中断：{exc}", file=sys.stderr)
        return 130 if isinstance(exc, KeyboardInterrupt) else 1
    except Exception as exc:
        print(f"\n错误：{exc}", file=sys.stderr)
        return 1

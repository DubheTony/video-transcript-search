"""转写：faster-whisper，带时间戳，输出 srt / jsonl / txt。"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from . import config


@dataclass
class Segment:
    start: float
    end: float
    text: str


def fmt_clock(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def fmt_srt_time(seconds: float) -> str:
    ms = max(0, int(round(seconds * 1000)))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def load_model(model_name: str, dev: str, compute: str):
    from faster_whisper import WhisperModel

    return WhisperModel(
        config.resolve_model(model_name),
        device=dev,
        compute_type=compute,
        local_files_only=True,
    )


def run_asr(
    wav: Path,
    model,
    *,
    language: str = config.DEFAULT_LANGUAGE,
    progress: bool = True,
) -> tuple[list[Segment], float]:
    """转写整段音频。返回 (段落列表, 音频总时长秒)。"""
    segments_iter, info = model.transcribe(
        str(wav),
        language=language or None,
        beam_size=5,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
        condition_on_previous_text=False,
        no_speech_threshold=0.6,
        compression_ratio_threshold=2.4,
        log_prob_threshold=-1.0,
    )

    total = float(info.duration or 0.0)
    result: list[Segment] = []
    for seg in segments_iter:
        text = seg.text.strip()
        if not text:
            continue
        result.append(Segment(seg.start, seg.end, text))
        if progress and total:
            pct = min(100, int(seg.end / total * 100))
            print(
                f"\r  转写 {pct:3d}%  [{fmt_clock(seg.end)} / {fmt_clock(total)}]",
                end="",
                file=sys.stderr,
                flush=True,
            )
    if progress:
        print("\r" + " " * 60 + "\r", end="", file=sys.stderr, flush=True)
    return result, total


def write_srt(path: Path, segments: list[Segment]) -> None:
    lines: list[str] = []
    for i, seg in enumerate(segments, 1):
        lines.append(str(i))
        lines.append(f"{fmt_srt_time(seg.start)} --> {fmt_srt_time(seg.end)}")
        lines.append(seg.text)
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_jsonl(path: Path, segments: list[Segment]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for seg in segments:
            f.write(
                json.dumps(
                    {"start": round(seg.start, 3), "end": round(seg.end, 3), "text": seg.text},
                    ensure_ascii=False,
                )
                + "\n"
            )


def write_txt(path: Path, segments: list[Segment]) -> None:
    path.write_text("\n".join(seg.text for seg in segments) + "\n", encoding="utf-8")


def run_sensevoice(
    wav: Path,
    model_dir: Path,
    *,
    language: str = "zh",
    num_threads: int = 8,
    chunk_seconds: int = 300,
    progress_path: Path | None = None,
) -> tuple[list[Segment], float]:
    """SenseVoice 分块识别。

    SenseVoice 单次输入太长会返回空结果，所以先按 VAD 找语音段，
    把相邻语音段合并成不超过 chunk_seconds 的块；块边界落在静音处，
    既保留上下文，又能给出块级时间戳。
    """
    import sherpa_onnx
    from faster_whisper.audio import decode_audio
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    if not model_dir.is_dir():
        raise FileNotFoundError(f"SenseVoice 模型目录不存在：{model_dir}")

    model_file = next(model_dir.rglob("model.int8.onnx"), None)
    tokens = next(model_dir.rglob("tokens.txt"), None)
    if not model_file or not tokens:
        raise FileNotFoundError(f"SenseVoice 模型文件不完整：{model_dir}")

    samples = decode_audio(str(wav), sampling_rate=16000)
    duration = len(samples) / 16000

    speech = get_speech_timestamps(
        samples,
        VadOptions(
            min_silence_duration_ms=500,
            speech_pad_ms=200,
            max_speech_duration_s=30,
        ),
    )
    blocks: list[tuple[int, int]] = []
    cur_start: int | None = None
    cur_end = 0
    for item in speech:
        start, end = item["start"], item["end"]
        if cur_start is None:
            cur_start, cur_end = start, end
        elif (end - cur_start) / 16000 <= chunk_seconds:
            cur_end = end
        else:
            blocks.append((cur_start, cur_end))
            cur_start, cur_end = start, end
    if cur_start is not None:
        blocks.append((cur_start, cur_end))

    recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=str(model_file),
        tokens=str(tokens),
        num_threads=num_threads,
        use_itn=True,
        language=language or "auto",
        debug=False,
    )

    done: dict[tuple[float, float], str] = {}
    if progress_path and progress_path.exists():
        try:
            for item in json.loads(progress_path.read_text(encoding="utf-8")):
                done[(round(item["start"], 3), round(item["end"], 3))] = item["text"]
        except Exception:
            done = {}

    def save_progress() -> None:
        if progress_path is None:
            return
        payload = [
            {"start": k[0], "end": k[1], "text": v} for k, v in done.items()
        ]
        progress_path.write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )

    segments: list[Segment] = []
    for start, end in blocks:
        key = (round(start / 16000, 3), round(end / 16000, 3))
        if key in done:
            text = done[key]
        else:
            stream = recognizer.create_stream()
            stream.accept_waveform(16000, samples[start:end])
            recognizer.decode_stream(stream)
            text = stream.result.text.strip()
            done[key] = text
            save_progress()
        if text:
            segments.append(Segment(key[0], key[1], text))
    return segments, duration

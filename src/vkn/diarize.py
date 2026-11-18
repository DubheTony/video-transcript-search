"""说话人分离：sherpa-onnx 的 pyannote 分割 + 3D-Speaker 嵌入。

ASR 给"说了什么"，这里给"谁说的"，按时间重叠对齐。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from . import config
from .asr import Segment, fmt_clock


@dataclass
class SpeakerSegment:
    start: float
    end: float
    speaker: int


def _model_paths() -> tuple[Path, Path]:
    segmentation = (
        config.DIARIZATION_DIR
        / "sherpa-onnx-pyannote-segmentation-3-0"
        / "model.onnx"
    )
    eres = (
        config.DIARIZATION_DIR
        / "3dspeaker_speech_eres2netv2_sv_zh-cn_16k-common.onnx"
    )
    cam = (
        config.DIARIZATION_DIR
        / "3dspeaker_speech_campplus_sv_zh-cn_16k-common.onnx"
    )
    # ERes2NetV2 在完整会议上明显更好（CAM++ 会把第二人丢成碎片）；
    # 没有 ERes 时回退 CAM++。
    embedding = eres if eres.exists() else cam
    if not segmentation.exists() or not embedding.exists():
        raise FileNotFoundError(
            f"说话人分离模型不完整，检查 {config.DIARIZATION_DIR}"
        )
    return segmentation, embedding


def run_diarization(
    wav: Path,
    *,
    num_threads: int = 4,
    threshold: float = 0.5,
    num_clusters: int = -1,
    window_shift_ratio: float | None = None,
    min_duration_on: float = 0.3,
    min_duration_off: float = 0.5,
    embedding_model: Path | None = None,
) -> list[SpeakerSegment]:
    """返回按开始时间排序的说话人时间段。"""
    import sherpa_onnx
    from faster_whisper.audio import decode_audio

    seg_model, default_emb_model = _model_paths()
    emb_model = embedding_model or default_emb_model
    if not Path(emb_model).exists():
        raise FileNotFoundError(f"说话人嵌入模型不存在：{emb_model}")

    pyannote_cfg = sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
        model=str(seg_model)
    )
    if window_shift_ratio is not None:
        pyannote_cfg.window_shift_ratio = window_shift_ratio

    seg_cfg = sherpa_onnx.OfflineSpeakerSegmentationModelConfig()
    seg_cfg.pyannote = pyannote_cfg
    seg_cfg.num_threads = num_threads
    seg_cfg.debug = False
    seg_cfg.provider = "cpu"

    emb_cfg = sherpa_onnx.SpeakerEmbeddingExtractorConfig()
    emb_cfg.model = str(emb_model)
    emb_cfg.num_threads = num_threads
    emb_cfg.debug = False
    emb_cfg.provider = "cpu"

    clu_cfg = sherpa_onnx.FastClusteringConfig()
    clu_cfg.num_clusters = num_clusters
    clu_cfg.threshold = threshold

    cfg = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        seg_cfg, emb_cfg, clu_cfg, min_duration_on, min_duration_off
    )
    sd = sherpa_onnx.OfflineSpeakerDiarization(cfg)

    samples = decode_audio(str(wav), sampling_rate=16000)
    result = sd.process(samples)
    segments = [
        SpeakerSegment(float(s.start), float(s.end), int(s.speaker))
        for s in result.sort_by_start_time()
    ]
    return segments


def clean_speaker_segments(
    segments: list[SpeakerSegment],
    *,
    min_duration: float = 0.5,
    max_gap: float = 0.5,
) -> list[SpeakerSegment]:
    """过滤过短的噪声段，合并相邻同说话人段。"""
    kept = [s for s in segments if s.end - s.start >= min_duration]
    merged: list[SpeakerSegment] = []
    for seg in kept:
        if (
            merged
            and merged[-1].speaker == seg.speaker
            and seg.start - merged[-1].end <= max_gap
        ):
            merged[-1].end = seg.end
        else:
            merged.append(SpeakerSegment(seg.start, seg.end, seg.speaker))
    return merged


def transcribe_by_speaker(
    wav: Path,
    speaker_segments: list[SpeakerSegment],
    model_dir: Path,
    *,
    language: str = "zh",
    num_threads: int = 8,
) -> list[dict]:
    """按说话人段逐段识别，文本天然带 speaker。

    会议场景比"先整段转写再对齐"更可靠，因为 ASR 的段落粒度
    往往比说话人切换粗得多。
    """
    import sherpa_onnx
    from faster_whisper.audio import decode_audio

    model_file = next(model_dir.rglob("model.int8.onnx"), None)
    tokens = next(model_dir.rglob("tokens.txt"), None)
    if not model_file or not tokens:
        raise FileNotFoundError(f"SenseVoice 模型文件不完整：{model_dir}")

    recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=str(model_file),
        tokens=str(tokens),
        num_threads=num_threads,
        use_itn=True,
        language=language or "auto",
        debug=False,
    )
    samples = decode_audio(str(wav), sampling_rate=16000)
    total = len(samples)

    rows: list[dict] = []
    for seg in speaker_segments:
        start = max(0, int(seg.start * 16000))
        end = min(total, int(seg.end * 16000))
        if end <= start:
            continue
        stream = recognizer.create_stream()
        stream.accept_waveform(16000, samples[start:end])
        recognizer.decode_stream(stream)
        text = stream.result.text.strip()
        if text:
            rows.append(
                {
                    "start": round(seg.start, 3),
                    "end": round(seg.end, 3),
                    "speaker": seg.speaker,
                    "text": text,
                }
            )
    return rows


def assign_speakers(
    transcript: list[Segment],
    speakers: list[SpeakerSegment],
) -> list[dict]:
    """每句选时间重叠最长的说话人；完全没重叠标 -1。"""
    rows: list[dict] = []
    for seg in transcript:
        best = None
        best_overlap = 0.0
        for sp in speakers:
            overlap = min(seg.end, sp.end) - max(seg.start, sp.start)
            if overlap > best_overlap:
                best_overlap = overlap
                best = sp
        rows.append(
            {
                "start": round(seg.start, 3),
                "end": round(seg.end, 3),
                "text": seg.text,
                "speaker": best.speaker if best else -1,
            }
        )
    return rows


def write_speakers_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_speakers_md(path: Path, title: str, rows: list[dict]) -> None:
    speakers = sorted({row["speaker"] for row in rows if row["speaker"] >= 0})
    lines = [
        f"# {title}（说话人版）",
        "",
        f"- 说话人数：{len(speakers)}",
        f"- 片段数：{len(rows)}",
        "",
    ]
    for speaker in speakers:
        lines.append(f"## 说话人 {speaker}")
        for row in rows:
            if row["speaker"] == speaker:
                lines.append(
                    f"[{fmt_clock(row['start'])}-{fmt_clock(row['end'])}] {row['text']}"
                )
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

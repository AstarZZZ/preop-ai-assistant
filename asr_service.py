#!/usr/bin/env python3
"""Local-only SenseVoice + VAD + CAM++ transcription service."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile


ROOT_DIR = Path(__file__).resolve().parent
MODELS_ROOT = Path(os.environ.get("PREOP_MODELS_ROOT", ROOT_DIR / "models")).resolve()
MAX_AUDIO_BYTES = int(os.environ.get("PREOP_ASR_MAX_AUDIO_BYTES", 512 * 1024 * 1024))


def _default_model_path(folder: str) -> str:
    return str(MODELS_ROOT / "modelscope" / "models" / folder / "snapshots" / "master")


MODEL_PATHS = {
    "asr": os.environ.get("PREOP_ASR_MODEL", _default_model_path("iic--SenseVoiceSmall")),
    "vad": os.environ.get(
        "PREOP_VAD_MODEL",
        _default_model_path("iic--speech_fsmn_vad_zh-cn-16k-common-pytorch"),
    ),
    "speaker": os.environ.get(
        "PREOP_SPK_MODEL",
        _default_model_path("iic--speech_campplus_sv_zh-cn_16k-common"),
    ),
    "punctuation": os.environ.get(
        "PREOP_PUNC_MODEL",
        _default_model_path("iic--punc_ct-transformer_cn-en-common-vocab471067-large"),
    ),
}
MODEL_IDS = {
    "asr": "iic/SenseVoiceSmall",
    "vad": "fsmn-vad",
    "speaker": "cam++",
    "punctuation": "ct-punc",
}


def clean_sensevoice_text(text: str) -> str:
    value = re.sub(r"<\s*\|\s*[^>]+?\s*\|\s*>", "", text or "")
    value = re.sub(r"\s+", "", value)
    value = re.sub(r"([。！？；，])\1+", r"\1", value)
    return value.strip()


class SenseVoiceEngine:
    def __init__(self) -> None:
        self.model = None
        self.state = "loading"
        self.error = ""
        self.loaded_seconds = None
        self.inference_lock = threading.Lock()

    def load(self) -> None:
        started = time.perf_counter()
        try:
            missing = [name for name, path in MODEL_PATHS.items() if not Path(path).exists()]
            allow_download = os.environ.get("PREOP_ALLOW_MODEL_DOWNLOAD") == "1"
            if missing and not allow_download:
                raise RuntimeError("缺少本地模型目录：{}".format("、".join(missing)))
            os.environ.setdefault("MODELSCOPE_CACHE", str(MODELS_ROOT / "modelscope"))
            os.environ.setdefault("HF_HOME", str(MODELS_ROOT / "huggingface"))
            from funasr import AutoModel

            selected = {
                name: (path if Path(path).exists() else MODEL_IDS[name])
                for name, path in MODEL_PATHS.items()
            }
            self.model = AutoModel(
                model=selected["asr"],
                trust_remote_code=True,
                vad_model=selected["vad"],
                vad_kwargs={"max_single_segment_time": 30000},
                spk_model=selected["speaker"],
                spk_mode="punc_segment",
                punc_model=selected["punctuation"],
                device=os.environ.get("PREOP_ASR_DEVICE", "cpu"),
                ncpu=int(os.environ.get("PREOP_ASR_CPU_THREADS", "6")),
                disable_update=True,
                disable_pbar=True,
            )
            self.loaded_seconds = round(time.perf_counter() - started, 3)
            self.state = "ready"
        except Exception as exc:
            self.error = str(exc)
            self.state = "error"
            raise

    def transcribe(self, input_path: str, expected_speakers: int, hotwords: str = "") -> dict:
        if self.state != "ready" or self.model is None:
            raise RuntimeError(self.error or "ASR模型尚未就绪")
        options = {
            "input": input_path,
            "cache": {},
            "language": "zh",
            "use_itn": True,
            "batch_size_s": 60,
            "merge_vad": True,
            "merge_length_s": 15,
            "sentence_timestamp": True,
            "preset_spk_num": max(1, min(int(expected_speakers or 2), 8)),
        }
        if hotwords.strip():
            options["postprocess_hotwords"] = [word for word in hotwords.split(",") if word.strip()]
        started = time.perf_counter()
        speaker_intervals = []
        with self.inference_lock:
            try:
                result = self.model.generate(**options)
            except TypeError as primary_error:
                # FunASR 1.3.26 can expose a None timestamp when punctuation and
                # token timestamps differ. VAD-level diarization remains valid.
                original_mode = self.model.spk_mode
                self.model.spk_mode = "vad_segment"
                try:
                    result = self.model.generate(**options)
                except Exception as fallback_error:
                    raise RuntimeError(
                        "讲话人分段失败：{} / {}".format(primary_error, fallback_error)
                    ) from fallback_error
                finally:
                    self.model.spk_mode = original_mode
            if expected_speakers > 1:
                speaker_intervals = self._diarize_intervals(input_path, expected_speakers)
        elapsed = round(time.perf_counter() - started, 3)
        if not result:
            raise RuntimeError("模型未返回识别结果")

        first = result[0]
        segments = self._segments_from_words(first, speaker_intervals)
        for item in first.get("sentence_info") or []:
            if segments:
                break
            text = clean_sensevoice_text(item.get("text", ""))
            if not text:
                continue
            speaker = item.get("spk")
            segments.append({
                "id": str(uuid.uuid4()),
                "start_ms": max(0, int(item.get("start", 0))),
                "end_ms": max(0, int(item.get("end", item.get("start", 0)))),
                "speaker_id": "speaker_{}".format(int(speaker) + 1) if speaker is not None else "speaker_1",
                "speaker_role": "",
                "text": text,
                "corrected_text": text,
                "overlap": False,
                "review_status": "unreviewed",
            })
        transcript = clean_sensevoice_text(first.get("text", ""))
        if not segments and transcript:
            timestamps = first.get("timestamp") or []
            end_ms = int(timestamps[-1][1]) if timestamps else 0
            segments = [{
                "id": str(uuid.uuid4()),
                "start_ms": int(timestamps[0][0]) if timestamps else 0,
                "end_ms": end_ms,
                "speaker_id": "speaker_1",
                "speaker_role": "",
                "text": transcript,
                "corrected_text": transcript,
                "overlap": False,
                "review_status": "unreviewed",
            }]
        return {
            "segments": segments,
            "transcript": transcript or "".join(item["text"] for item in segments),
            "detected_speakers": len({item["speaker_id"] for item in segments}),
            "inference_seconds": elapsed,
        }

    def _diarize_intervals(self, input_path: str, expected_speakers: int) -> list:
        """Preserve CAM++ window boundaries instead of collapsing them by punctuation."""
        import numpy as np
        import torch
        import torchaudio
        from funasr.models.campplus.utils import postprocess, sv_chunk

        waveform, sample_rate = torchaudio.load(input_path)
        if sample_rate != 16000:
            waveform = torchaudio.functional.resample(waveform, sample_rate, 16000)
        samples = waveform[0].cpu().numpy().astype("float32")
        vad_result = self.model.inference(
            input_path,
            model=self.model.vad_model,
            kwargs=self.model.vad_kwargs,
            disable_pbar=True,
        )
        regions = (vad_result[0].get("value") if vad_result else None) or []
        vad_audio = []
        for start_ms, end_ms in regions:
            start_sample = max(0, int(start_ms * 16))
            end_sample = min(len(samples), int(end_ms * 16))
            if end_sample > start_sample:
                vad_audio.append([start_ms / 1000.0, end_ms / 1000.0, samples[start_sample:end_sample]])
        chunks = sv_chunk(vad_audio)
        if len(chunks) < 2:
            return []
        speaker_result = self.model.inference(
            [chunk[2] for chunk in chunks],
            model=self.model.spk_model,
            kwargs=self.model.kwargs,
            disable_pbar=True,
        )
        embeddings = torch.cat([item["spk_embedding"] for item in speaker_result], dim=0)
        oracle_num = min(max(1, int(expected_speakers)), len(chunks))
        labels = self.model.cb_model(embeddings.cpu(), oracle_num=oracle_num)
        intervals = postprocess(chunks, None, labels, embeddings.detach().cpu().numpy())
        return [[int(start * 1000), int(end * 1000), int(speaker)] for start, end, speaker in intervals]

    @staticmethod
    def _segments_from_words(result: dict, speaker_intervals: list) -> list:
        words = result.get("words") or []
        timestamps = result.get("timestamp") or []
        if not words or not timestamps or len({item[2] for item in speaker_intervals}) < 2:
            return []
        tokens = []
        for word, timestamp in zip(words, timestamps):
            if not timestamp or len(timestamp) < 2:
                continue
            start_ms, end_ms = int(timestamp[0]), int(timestamp[1])
            midpoint = (start_ms + end_ms) / 2
            speaker = 0
            best_overlap = -1
            for interval_start, interval_end, interval_speaker in speaker_intervals:
                overlap = min(end_ms, interval_end) - max(start_ms, interval_start)
                if overlap > best_overlap or (overlap == best_overlap and interval_start <= midpoint <= interval_end):
                    best_overlap = overlap
                    speaker = interval_speaker
            tokens.append((str(word), start_ms, end_ms, speaker))
        if not tokens:
            return []
        grouped = []
        for word, start_ms, end_ms, speaker in tokens:
            if grouped and grouped[-1]["speaker_id"] == "speaker_{}".format(speaker + 1):
                grouped[-1]["text"] += word
                grouped[-1]["corrected_text"] += word
                grouped[-1]["end_ms"] = end_ms
                continue
            grouped.append({
                "id": str(uuid.uuid4()),
                "start_ms": start_ms,
                "end_ms": end_ms,
                "speaker_id": "speaker_{}".format(speaker + 1),
                "speaker_role": "",
                "text": word,
                "corrected_text": word,
                "overlap": False,
                "review_status": "unreviewed",
            })
        return grouped


engine = SenseVoiceEngine()
app = FastAPI(title="Preop Local ASR", version="1.0.0", docs_url=None, redoc_url=None)


@app.on_event("startup")
def startup() -> None:
    engine.load()


@app.get("/health")
def health() -> dict:
    return {
        "state": engine.state,
        "backend": "local-sensevoice-campp",
        "model": "SenseVoiceSmall",
        "vad_model": "FSMN-VAD",
        "speaker_model": "CAM++",
        "punctuation_model": "CT-Punc",
        "device": os.environ.get("PREOP_ASR_DEVICE", "cpu"),
        "loaded_seconds": engine.loaded_seconds,
        "weights_ready": all(Path(path).exists() for path in MODEL_PATHS.values()),
        "offline_only": os.environ.get("PREOP_ALLOW_MODEL_DOWNLOAD") != "1",
        "detail": engine.error,
    }


def convert_to_wav(source: str, target: str) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        try:
            import imageio_ffmpeg
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except (ImportError, RuntimeError) as exc:
            raise RuntimeError("未找到 FFmpeg，无法解码浏览器 WebM/Opus 录音") from exc
    completed = subprocess.run(
        [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", source,
         "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", target],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError("音频解码失败：{}".format(completed.stderr.strip()[:500]))


@app.post("/v1/transcribe")
async def transcribe(
    audio: UploadFile = File(...),
    expected_speakers: int = Form(2),
    hotwords: str = Form(""),
) -> dict:
    if engine.state != "ready":
        raise HTTPException(status_code=503, detail=engine.error or "ASR模型未就绪")
    data = await audio.read(MAX_AUDIO_BYTES + 1)
    if not data:
        raise HTTPException(status_code=400, detail="音频文件为空")
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="音频文件过大")
    suffix = Path(audio.filename or "audio.webm").suffix or ".webm"
    try:
        with tempfile.TemporaryDirectory(prefix="preop-asr-") as temp_dir:
            source = str(Path(temp_dir) / ("source" + suffix))
            normalized = str(Path(temp_dir) / "normalized.wav")
            Path(source).write_bytes(data)
            convert_to_wav(source, normalized)
            result = engine.transcribe(normalized, expected_speakers, hotwords)
            result.update({
                "backend": "local-sensevoice-campp",
                "expected_speakers": max(1, min(expected_speakers, 8)),
            })
            return result
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

#!/usr/bin/env python3
"""Load the pinned local FunASR pipeline and transcribe one audio file."""

import argparse
import json
import os
import time


def strip_tags(text):
    import re
    return re.sub(r"<\|[^|]+\|>", "", text or "").strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("audio")
    parser.add_argument("--device", default=os.environ.get("PREOP_ASR_DEVICE", "cpu"))
    parser.add_argument("--expected-speakers", type=int, default=2)
    args = parser.parse_args()

    from funasr import AutoModel

    models_root = os.path.abspath(os.environ.get("PREOP_MODELS_ROOT", "models"))
    os.makedirs(models_root, exist_ok=True)
    os.environ.setdefault("MODELSCOPE_CACHE", os.path.join(models_root, "modelscope"))
    os.environ.setdefault("HF_HOME", os.path.join(models_root, "huggingface"))

    started = time.perf_counter()
    model = AutoModel(
        model=os.environ.get("PREOP_ASR_MODEL", "iic/SenseVoiceSmall"),
        trust_remote_code=True,
        vad_model=os.environ.get("PREOP_VAD_MODEL", "fsmn-vad"),
        vad_kwargs={"max_single_segment_time": 30000},
        spk_model=os.environ.get("PREOP_SPK_MODEL", "cam++"),
        spk_mode="vad_segment",
        punc_model=os.environ.get("PREOP_PUNC_MODEL", "ct-punc"),
        device=args.device,
        disable_update=True,
    )
    loaded_seconds = time.perf_counter() - started

    inference_started = time.perf_counter()
    raw = model.generate(
        input=os.path.abspath(args.audio),
        cache={},
        language="auto",
        use_itn=True,
        batch_size_s=60,
        merge_vad=True,
        merge_length_s=15,
        sentence_timestamp=True,
        preset_spk_num=args.expected_speakers,
    )
    inference_seconds = time.perf_counter() - inference_started
    segments = []
    if raw:
        for index, item in enumerate(raw[0].get("sentence_info") or []):
            text = strip_tags(item.get("text", ""))
            if not text:
                continue
            speaker = item.get("spk")
            segments.append({
                "start_ms": int(item.get("start", 0)),
                "end_ms": int(item.get("end", item.get("start", 0))),
                "speaker_id": "speaker_{}".format(int(speaker) + 1) if speaker is not None else "speaker_unknown",
                "text": text,
            })
    if not segments and raw:
        segments.append({
            "start_ms": 0,
            "end_ms": 0,
            "speaker_id": "speaker_unknown",
            "text": strip_tags(raw[0].get("text", "")),
        })
    print(json.dumps({
        "audio": os.path.abspath(args.audio),
        "device": args.device,
        "model_load_seconds": round(loaded_seconds, 3),
        "inference_seconds": round(inference_seconds, 3),
        "segments": segments,
        "raw": raw,
    }, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()

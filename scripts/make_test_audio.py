#!/usr/bin/env python3
"""Combine two 16 kHz mono WAV fixtures with silence for diarization tests."""

import os
import wave


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(ROOT, "tests", "fixtures")
SOURCES = [
    os.path.join(FIXTURES, "speaker1.wav"),
    os.path.join(FIXTURES, "speaker2.wav"),
]
TARGET = os.path.join(FIXTURES, "two-speaker-preop.wav")


def main():
    chunks = []
    params = None
    for path in SOURCES:
        with wave.open(path, "rb") as source:
            current = source.getparams()
            if params is None:
                params = current
            elif (current.nchannels, current.sampwidth, current.framerate) != (
                params.nchannels, params.sampwidth, params.framerate
            ):
                raise RuntimeError("测试 WAV 格式不一致")
            chunks.append(source.readframes(source.getnframes()))
    silence = b"\x00" * params.sampwidth * params.nchannels * params.framerate
    with wave.open(TARGET, "wb") as output:
        output.setnchannels(params.nchannels)
        output.setsampwidth(params.sampwidth)
        output.setframerate(params.framerate)
        for index, chunk in enumerate(chunks):
            if index:
                output.writeframes(silence)
            output.writeframes(chunk)
    print(TARGET)


if __name__ == "__main__":
    main()

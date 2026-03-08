#!/usr/bin/env python3
"""
Минимальный учебный пример streaming speech-to-text для звонка из Asterisk через EAGI.

Почему так:
- В бою (через Asterisk EAGI) аудио читается из fd=3.
- Для локальной проверки без Asterisk есть режим --wav, чтобы скрипт не падал с "Bad file descriptor".
"""

import argparse
import json
import os
import sys
import wave
from typing import BinaryIO, Tuple

from vosk import KaldiRecognizer, Model

# ==========================
# Заглушки (подставьте свои)
# ==========================
ASTERISK_HOST = "YOUR_ASTERISK_IP"           # например: "192.168.1.10"
ASTERISK_PORT = 5060                          # например SIP порт
ASTERISK_AUDIO_SOURCE = "EAGI_FD3"           # для этого примера источник = fd 3
EXTENSION = "YOUR_EXTENSION"                 # например: "100"
CODEC = "slin"                               # для EAGI обычно signed linear (slin)

# Путь к распакованной модели Vosk.
MODEL_PATH = "./model"

# Частота дискретизации аудио в потоке из Asterisk.
# Для классической телефонии обычно 8000 Гц.
SAMPLE_RATE = 8000

# Размер блока данных для чтения из потока.
CHUNK_SIZE = 4000


def parse_args() -> argparse.Namespace:
    """Аргументы: по умолчанию EAGI (fd=3), опционально тест из WAV."""
    parser = argparse.ArgumentParser(
        description="Streaming STT from Asterisk EAGI (fd=3) with optional local WAV test mode",
    )
    parser.add_argument(
        "--wav",
        default="",
        help="Путь к WAV для локального теста (mono, PCM16). Если не указан, читаем EAGI fd=3.",
    )
    parser.add_argument(
        "--model",
        default=MODEL_PATH,
        help="Путь к папке модели Vosk (default: ./model)",
    )
    parser.add_argument(
        "--sample-rate",
        type=int,
        default=SAMPLE_RATE,
        help="Частота дискретизации потока (default: 8000)",
    )
    return parser.parse_args()


def open_audio_source(wav_path: str) -> Tuple[BinaryIO, wave.Wave_read | None]:
    """
    Открывает источник аудио:
    - EAGI fd=3, если --wav не передан;
    - WAV файл, если --wav передан.

    Возвращает (stream, wav_obj_or_none).
    wav_obj нужен, чтобы корректно закрыть wave reader.
    """
    if wav_path:
        wav_reader = wave.open(wav_path, "rb")
        # Учебное ограничение: ждем простой телефонный WAV (mono PCM16).
        if wav_reader.getnchannels() != 1:
            raise ValueError("WAV должен быть mono (1 channel)")
        if wav_reader.getsampwidth() != 2:
            raise ValueError("WAV должен быть PCM16 (sample width = 2 bytes)")
        return wav_reader, wav_reader

    # fd=3 — стандартный аудиопоток EAGI от Asterisk.
    # Если скрипт запущен вручную, fd=3 обычно не существует -> понятная ошибка.
    try:
        return os.fdopen(3, "rb", buffering=0), None
    except OSError as exc:
        raise RuntimeError(
            "Не удалось открыть fd=3. Скрипт должен быть запущен Asterisk через EAGI, "
            "или запустите локальный тест: --wav /path/to/file.wav"
        ) from exc


def recognize_stream(audio_stream: BinaryIO, recognizer: KaldiRecognizer, from_wav: bool) -> None:
    """Читает поток и выводит PARTIAL/FINAL в реальном времени."""
    last_partial = ""

    while True:
        data = audio_stream.readframes(CHUNK_SIZE // 2) if from_wav else audio_stream.read(CHUNK_SIZE)

        # Поток завершился (конец звонка / конец WAV).
        if not data:
            break

        if recognizer.AcceptWaveform(data):
            result = json.loads(recognizer.Result())
            text = result.get("text", "").strip()
            if text:
                print(f"[FINAL] {text}", flush=True)
        else:
            partial = json.loads(recognizer.PartialResult()).get("partial", "").strip()
            if partial and partial != last_partial:
                print(f"[PARTIAL] {partial}", flush=True)
                last_partial = partial

    # Финальный "хвост" после конца потока.
    final_tail = json.loads(recognizer.FinalResult()).get("text", "").strip()
    if final_tail:
        print(f"[FINAL_TAIL] {final_tail}", flush=True)


def main() -> int:
    """Точка входа."""
    args = parse_args()

    if not os.path.isdir(args.model):
        print(
            f"[ERROR] Vosk model not found: {args.model}\n"
            "Скачайте модель с https://alphacephei.com/vosk/models и распакуйте в указанную папку.",
            file=sys.stderr,
        )
        return 1

    print("[INFO] Loading Vosk model...", flush=True)
    model = Model(args.model)
    recognizer = KaldiRecognizer(model, args.sample_rate)

    from_wav = bool(args.wav)
    wav_obj = None

    try:
        audio_stream, wav_obj = open_audio_source(args.wav)
    except (RuntimeError, ValueError, wave.Error) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2

    source_label = args.wav if from_wav else "EAGI fd=3"
    print(f"[INFO] Streaming recognition started. Source: {source_label}", flush=True)

    try:
        recognize_stream(audio_stream, recognizer, from_wav=from_wav)
    except KeyboardInterrupt:
        print("\n[INFO] Interrupted by user.", flush=True)
    finally:
        # Для WAV нужно явно закрыть reader, для fdopen закрытие у stream.
        if wav_obj is not None:
            wav_obj.close()
        else:
            audio_stream.close()

    print("[INFO] Streaming recognition finished.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

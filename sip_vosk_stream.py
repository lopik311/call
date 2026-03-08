#!/usr/bin/env python3
"""
Минимальный учебный пример streaming speech-to-text для звонка из Asterisk через EAGI.

Идея:
1) Asterisk уже настроен так, что при звонке запускает этот скрипт как EAGI.
2) Аудио звонка приходит в скрипт через файловый дескриптор 3 (fd=3).
3) Скрипт в реальном времени передает аудио в Vosk и печатает распознанный текст в консоль.

Важно:
- Конфиг Asterisk здесь не меняем.
- Вы подставляете свои значения в переменные-заглушки ниже.
"""

import json
import os
import sys

from vosk import KaldiRecognizer, Model

# ==========================
# Заглушки (подставьте свои)
# ==========================
ASTERISK_HOST = "YOUR_ASTERISK_IP"           # например: "192.168.1.10"
ASTERISK_PORT = 5060                          # например SIP порт
ASTERISK_AUDIO_SOURCE = "EAGI_FD3"           # для этого примера источник = fd 3
EXTENSION = "YOUR_EXTENSION"                 # например: "100"
CODEC = "slin"                               # для EAGI обычно signed linear (slin)

# Путь к распаковнной модели Vosk (скачайте заранее).
MODEL_PATH = "./model"

# Частота дискретизации аудио в потоке из Asterisk.
# Для классической телефонии чаще 8000 Гц.
SAMPLE_RATE = 8000

# Размер куска данных для чтения из входящего аудио потока.
CHUNK_SIZE = 4000


def main() -> int:
    """Точка входа: читает аудио из fd=3 и печатает распознанный текст."""

    # Быстрая проверка наличия модели.
    if not os.path.isdir(MODEL_PATH):
        print(
            f"[ERROR] Vosk model not found: {MODEL_PATH}\n"
            "Скачайте модель с https://alphacephei.com/vosk/models и распакуйте в ./model",
            file=sys.stderr,
        )
        return 1

    print("[INFO] Loading Vosk model...", flush=True)
    model = Model(MODEL_PATH)
    recognizer = KaldiRecognizer(model, SAMPLE_RATE)

    # fd=3 — стандартный аудиопоток EAGI от Asterisk.
    # buffering=0: читаем максимально "живой" поток без лишней буферизации Python.
    audio_stream = os.fdopen(3, "rb", buffering=0)

    print("[INFO] Streaming recognition started...", flush=True)
    print("[INFO] Speak into SIP call. Press Ctrl+C to stop (if running manually).", flush=True)

    last_partial = ""

    try:
        while True:
            data = audio_stream.read(CHUNK_SIZE)

            # Если данных нет, звонок/поток завершился.
            if not data:
                break

            # AcceptWaveform=True -> Vosk получил законченный фрагмент фразы (final result).
            if recognizer.AcceptWaveform(data):
                result = json.loads(recognizer.Result())
                text = result.get("text", "").strip()
                if text:
                    print(f"[FINAL] {text}", flush=True)
            else:
                # Иначе печатаем промежуточную (partial) гипотезу в реальном времени.
                partial = json.loads(recognizer.PartialResult()).get("partial", "").strip()
                if partial and partial != last_partial:
                    print(f"[PARTIAL] {partial}", flush=True)
                    last_partial = partial

        # Финальный "хвост" при завершении потока.
        final_tail = json.loads(recognizer.FinalResult()).get("text", "").strip()
        if final_tail:
            print(f"[FINAL_TAIL] {final_tail}", flush=True)

    except KeyboardInterrupt:
        print("\n[INFO] Interrupted by user.", flush=True)

    print("[INFO] Streaming recognition finished.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

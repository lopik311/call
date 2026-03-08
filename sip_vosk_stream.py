#!/usr/bin/env python3
"""
Минимальный учебный пример streaming speech-to-text (Vosk) для Asterisk AudioSocket.

Сценарий:
1) Asterisk в dialplan вызывает AudioSocket(..., 127.0.0.1:9092)
2) Этот скрипт слушает TCP-порт 9092
3) Получает аудио-пакеты, отдает в Vosk, печатает PARTIAL/FINAL в консоль

Также есть режим локальной проверки из WAV: --wav /path/to/test.wav
"""

import argparse
import json
import os
import socket
import sys
import wave
from dataclasses import dataclass
from typing import Generator

# ==========================
# Заглушки (подставьте свои)
# ==========================
ASTERISK_HOST = "YOUR_ASTERISK_IP"
ASTERISK_PORT = 5060
ASTERISK_AUDIO_SOURCE = "AudioSocket"
EXTENSION = "YOUR_EXTENSION"
CODEC = "slin"

# AudioSocket endpoint (должен совпадать с dialplan)
AUDIOSOCKET_HOST = "127.0.0.1"
AUDIOSOCKET_PORT = 9092

# Путь к модели Vosk
MODEL_PATH = "./vosk-model-small-ru-0.22"

# Базовая частота для телефонии (если не задано иначе)
SAMPLE_RATE = 8000

# Размер куска для WAV-режима
CHUNK_SIZE = 4000

# Типы фреймов AudioSocket
FRAME_UUID = 0x01
FRAME_DTMF = 0x03
FRAME_HANGUP = 0x00
FRAME_ERROR = 0xFF

# Аудио-типы (обычно slin*). В учебном примере поддерживаем набор популярных значений.
AUDIO_FRAME_TYPES = {0x10, 0x11, 0x12, 0x13}


@dataclass
class AudioSocketFrame:
    frame_type: int
    payload: bytes


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Minimal AudioSocket/WAV -> Vosk streaming STT")
    parser.add_argument("--model", default=MODEL_PATH, help="Путь к папке модели Vosk")
    parser.add_argument("--sample-rate", type=int, default=SAMPLE_RATE, help="Частота для распознавания")
    parser.add_argument("--host", default=AUDIOSOCKET_HOST, help="Хост для AudioSocket сервера")
    parser.add_argument("--port", type=int, default=AUDIOSOCKET_PORT, help="Порт для AudioSocket сервера")
    parser.add_argument("--wav", default="", help="Локальный WAV тест (mono, PCM16)")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Обработать только одно соединение и завершиться (по умолчанию сервер принимает звонки в цикле)",
    )
    parser.add_argument("--verbose", action="store_true", help="Печатать служебные фреймы AudioSocket")
    return parser.parse_args()


def read_exact(sock: socket.socket, n: int) -> bytes:
    """Читает ровно n байт из сокета или возвращает b'' при закрытии."""
    chunks = []
    got = 0
    while got < n:
        part = sock.recv(n - got)
        if not part:
            return b""
        chunks.append(part)
        got += len(part)
    return b"".join(chunks)


def iter_audiosocket_frames(conn: socket.socket) -> Generator[AudioSocketFrame, None, None]:
    """
    Итерирует фреймы AudioSocket.

    Формат фрейма:
    - 1 байт: type
    - 2 байта: payload len (big-endian)
    - payload
    """
    while True:
        header = read_exact(conn, 3)
        if not header:
            return

        frame_type = header[0]
        payload_len = int.from_bytes(header[1:3], byteorder="big", signed=False)
        payload = read_exact(conn, payload_len)
        if payload_len and not payload:
            return

        yield AudioSocketFrame(frame_type=frame_type, payload=payload)


def recognize_stream_from_wav(wav_path: str, recognizer) -> None:
    """Streaming распознавание из WAV (локальный тест)."""
    with wave.open(wav_path, "rb") as wf:
        if wf.getnchannels() != 1:
            raise ValueError("WAV должен быть mono (1 channel)")
        if wf.getsampwidth() != 2:
            raise ValueError("WAV должен быть PCM16 (sample width = 2 bytes)")

        last_partial = ""
        while True:
            data = wf.readframes(CHUNK_SIZE // 2)
            if not data:
                break

            if recognizer.AcceptWaveform(data):
                text = json.loads(recognizer.Result()).get("text", "").strip()
                if text:
                    print(f"[FINAL] {text}", flush=True)
            else:
                partial = json.loads(recognizer.PartialResult()).get("partial", "").strip()
                if partial and partial != last_partial:
                    print(f"[PARTIAL] {partial}", flush=True)
                    last_partial = partial

        tail = json.loads(recognizer.FinalResult()).get("text", "").strip()
        if tail:
            print(f"[FINAL_TAIL] {tail}", flush=True)


def recognize_stream_from_audiosocket(conn: socket.socket, recognizer, verbose: bool = False) -> None:
    """Streaming распознавание из входящего AudioSocket TCP соединения."""
    last_partial = ""
    seen_uuid = False
    seen_audio = False

    for frame in iter_audiosocket_frames(conn):
        frame_type = frame.frame_type
        payload = frame.payload

        if frame_type == FRAME_UUID:
            seen_uuid = True
            uuid_hex = payload.hex()
            print(f"[INFO] AudioSocket UUID frame: {uuid_hex}", flush=True)
            continue

        if frame_type in AUDIO_FRAME_TYPES:
            seen_audio = True
            if recognizer.AcceptWaveform(payload):
                text = json.loads(recognizer.Result()).get("text", "").strip()
                if text:
                    print(f"[FINAL] {text}", flush=True)
            else:
                partial = json.loads(recognizer.PartialResult()).get("partial", "").strip()
                if partial and partial != last_partial:
                    print(f"[PARTIAL] {partial}", flush=True)
                    last_partial = partial
            continue

        if frame_type == FRAME_DTMF:
            try:
                symbol = payload.decode("utf-8", errors="replace")
            except Exception:
                symbol = payload.hex()
            print(f"[INFO] DTMF: {symbol}", flush=True)
            continue

        if frame_type == FRAME_ERROR:
            try:
                err = payload.decode("utf-8", errors="replace")
            except Exception:
                err = payload.hex()
            print(f"[ERROR] AudioSocket remote error: {err}", file=sys.stderr, flush=True)
            continue

        if frame_type == FRAME_HANGUP:
            if verbose:
                print("[INFO] HANGUP frame received", flush=True)
            break

        if verbose:
            print(f"[INFO] Ignored frame type=0x{frame_type:02x}, len={len(payload)}", flush=True)

    tail = json.loads(recognizer.FinalResult()).get("text", "").strip()
    if tail:
        print(f"[FINAL_TAIL] {tail}", flush=True)

    if not seen_uuid:
        print("[WARN] UUID frame не получен (проверьте AudioSocket поток)", flush=True)
    if not seen_audio:
        print("[WARN] Аудио-фреймы не получены. Проверьте codec/формат в Asterisk.", flush=True)


def handle_one_audiosocket_call(server: socket.socket, args: argparse.Namespace, model) -> None:
    """Обрабатывает одно входящее соединение AudioSocket."""
    from vosk import KaldiRecognizer

    recognizer = KaldiRecognizer(model, args.sample_rate)

    print(f"[INFO] Waiting AudioSocket connection on {args.host}:{args.port} ...", flush=True)
    conn, addr = server.accept()
    with conn:
        print(f"[INFO] AudioSocket connected: {addr}", flush=True)
        recognize_stream_from_audiosocket(conn, recognizer, verbose=args.verbose)
        print("[INFO] AudioSocket disconnected", flush=True)


def main() -> int:
    args = parse_args()

    if not os.path.isdir(args.model):
        print(f"[ERROR] Vosk model not found: {args.model}", file=sys.stderr)
        return 1

    try:
        from vosk import Model
    except ModuleNotFoundError:
        print("[ERROR] Пакет 'vosk' не установлен. Выполните: pip install -r requirements.txt", file=sys.stderr)
        return 2

    print("[INFO] Loading Vosk model...", flush=True)
    model = Model(args.model)

    if args.wav:
        try:
            from vosk import KaldiRecognizer
            recognizer = KaldiRecognizer(model, args.sample_rate)
            print(f"[INFO] Source: WAV ({args.wav}), sample_rate={args.sample_rate}", flush=True)
            recognize_stream_from_wav(args.wav, recognizer)
        except (wave.Error, ValueError, FileNotFoundError) as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 3
        print("[INFO] Finished.", flush=True)
        return 0

    # Режим AudioSocket-сервера. По умолчанию работает постоянно (удобно для прод/теста).
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((args.host, args.port))
        server.listen(5)

        try:
            while True:
                handle_one_audiosocket_call(server, args, model)
                if args.once:
                    break
        except KeyboardInterrupt:
            print("\n[INFO] Interrupted by user.", flush=True)

    print("[INFO] Finished.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

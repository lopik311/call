# Minimal Asterisk AudioSocket + Vosk streaming STT (Python)

Учебный MVP: распознавание речи в реальном времени из SIP-звонка через уже настроенный Asterisk.

## Почему AudioSocket

Вы уже используете в dialplan:

```asterisk
same => n,AudioSocket(${AI_UUID},127.0.0.1:9092)
```

Значит самый простой путь — запустить отдельный Python TCP-сервер на `127.0.0.1:9092` (или `0.0.0.0:9092`) и читать аудио прямо из AudioSocket.

## Структура проекта

```text
.
├── README.md
├── requirements.txt
└── sip_vosk_stream.py
```

## Установка

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Скачайте модель Vosk (например `vosk-model-small-ru-0.22`) и распакуйте.

## Запуск (отдельно от Asterisk)

```bash
python3 sip_vosk_stream.py \
  --host 0.0.0.0 \
  --port 9092 \
  --model /vosk-model-small-ru-0.22 \
  --sample-rate 8000
```

После запуска сделайте звонок, который попадет в ваш контекст `from-rostelecom` с `AudioSocket(...,127.0.0.1:9092)`.
Скрипт примет соединение и начнет выводить `[PARTIAL]` и `[FINAL]` в консоль.

## Локальный тест без Asterisk (WAV)

```bash
python3 sip_vosk_stream.py --wav /path/to/test.wav --model /vosk-model-small-ru-0.22 --sample-rate 8000
```

Требования к WAV: mono, PCM16.

## Что нужно подставить

В коде/запуске подставьте ваши значения:
- `ASTERISK_HOST`
- `ASTERISK_PORT`
- `ASTERISK_AUDIO_SOURCE`
- `EXTENSION`
- `CODEC`
- `--host`
- `--port`
- `--model`
- `--sample-rate`

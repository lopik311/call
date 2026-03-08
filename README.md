# Minimal Asterisk + Vosk streaming STT (Python)

Учебный MVP: распознавание речи в реальном времени из SIP-звонка через уже настроенный Asterisk.

## Почему выбран EAGI

Для минимального примера выбран **EAGI**, потому что это один из самых простых способов получить аудио из Asterisk во внешний Python-скрипт:
- Asterisk просто запускает скрипт;
- аудио приходит напрямую в `fd=3`;
- не нужны отдельные RTP-серверы, WebSocket-шлюзы или сложная ARI-архитектура.

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

Скачайте модель Vosk и распакуйте в папку `./model`.

## Запуск

```bash
python3 sip_vosk_stream.py
```

Обычно скрипт запускается самим Asterisk (EAGI), а не вручную.

## Что нужно подставить

В `sip_vosk_stream.py` замените заглушки:
- `ASTERISK_HOST`
- `ASTERISK_PORT`
- `ASTERISK_AUDIO_SOURCE`
- `EXTENSION`
- `CODEC`
- `MODEL_PATH`
- `SAMPLE_RATE`

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

Скачайте модель Vosk и распакуйте в папку `./model` (или укажите другую через `--model`).

## Запуск

### 1) Боевой режим через Asterisk EAGI

Скрипт запускает Asterisk. В этом режиме аудио читается из `fd=3` автоматически.

```bash
python3 sip_vosk_stream.py
```

> Если запустить эту команду вручную в обычном shell, `fd=3` чаще всего отсутствует,
> и вы получите понятную ошибку с подсказкой.
>
> Важно: теперь эта ошибка проверяется **до** загрузки модели Vosk,
> чтобы сразу показать причину (а не тратить время на инициализацию модели).

### 2) Локальный тест без Asterisk

```bash
python3 sip_vosk_stream.py --wav /path/to/test.wav --model ./model --sample-rate 8000
```

Требования к WAV для простого примера: mono, PCM16.

Если `--sample-rate` не указан явно, скрипт автоматически возьмет частоту из WAV файла.

## Что нужно подставить

В `sip_vosk_stream.py` замените заглушки:
- `ASTERISK_HOST`
- `ASTERISK_PORT`
- `ASTERISK_AUDIO_SOURCE`
- `EXTENSION`
- `CODEC`

Дополнительно задайте свои значения запуска:
- `--model` (или измените `MODEL_PATH`)
- `--sample-rate` (должен совпадать с реальным входным аудио)

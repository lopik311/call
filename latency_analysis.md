# Анализ задержки и идеи для ускорения ответа

Исходный пайплайн выглядит так:

1. Телефония передаёт PCM чанки.
2. Вы отправляете звук в Yandex STT streaming.
3. Ждёте только `final`-результат распознавания.
4. Только после `final` вызываете `ask_llm(...)`.

Главный вклад в задержку обычно даёт шаг **"ждём FINAL"** + время LLM.

## Узкие места в текущем коде

- Новый gRPC channel создаётся на каждую сессию звонка.
- Нет gRPC keepalive/оптимизаций канала.
- Используется неограниченная `queue.Queue()` (риск роста буфера и дополнительной задержки при пиках).
- Вы запускаете LLM только по `final`, то есть теряете время, когда уже есть стабилизировавшийся partial.
- Нет дедупликации/дебаунса final-ивентов (иногда приходит несколько финалов подряд, можно лишний раз дёргать LLM).
- В `recv_exact` используется конкатенация immutable bytes (`data += chunk`), что создаёт лишние копии.

## Что даст максимальный эффект

### 1) Ранний старт LLM по partial (speculative execution)

Самое сильное ускорение: не ждать `final`, а запускать черновой вызов LLM, когда partial стабилен (например, не меняется 300–500ms и длина > N символов). Когда придёт final:

- если текст близок к partial — используете уже почти готовый ответ;
- если различается сильно — делаете быстрый корректирующий запрос.

Обычно это даёт субъективно самое заметное уменьшение TTFB ответа.

### 2) Переиспользование gRPC каналов

Создайте один глобальный channel/stub на процесс и переиспользуйте их для сессий. Это убирает лишнюю стоимость TLS/HTTP2 setup на каждый звонок.

### 3) Агрессивные gRPC опции

Добавьте keepalive и pings, чтобы канал не "засыпал":

```python
GRPC_OPTIONS = [
    ("grpc.keepalive_time_ms", 20000),
    ("grpc.keepalive_timeout_ms", 10000),
    ("grpc.keepalive_permit_without_calls", 1),
    ("grpc.http2.max_pings_without_data", 0),
    ("grpc.max_receive_message_length", 16 * 1024 * 1024),
]
```

### 4) Ограниченная очередь + backpressure

`queue.Queue(maxsize=...)` с политикой drop-oldest/drop-newest при перегрузе (лучше потерять старый аудиочанк, чем накапливать секунды задержки).

### 5) Микрооптимизации ввода аудио

В `recv_exact` используйте `bytearray` + `recv_into`, чтобы избежать постоянных копий bytes.

### 6) Параллельная оркестрация

Обработку `responses` и вызов LLM разделить:

- поток A: читает STT events;
- поток B: работает с LLM задачами.

Так вы не блокируете чтение STT, пока LLM отвечает.

### 7) Логика endpointing

Если фраза короткая и есть тишина > X ms, не ждите долгой финализации — завершайте фразу сами и запускайте LLM.

---

## Пример улучшенной архитектуры (фрагмент)

```python
import socket
import struct
import threading
import queue
import time
import grpc
from concurrent.futures import ThreadPoolExecutor

import yandex.cloud.ai.stt.v3.stt_pb2 as stt_pb2
import yandex.cloud.ai.stt.v3.stt_service_pb2_grpc as stt_service_pb2_grpc

from config import HOST, PORT, YANDEX_KEY
from dialog_orchestrator import ask_llm


def now():
    return time.time()


# Глобальный channel/stub (переиспользование)
GRPC_OPTIONS = [
    ("grpc.keepalive_time_ms", 20000),
    ("grpc.keepalive_timeout_ms", 10000),
    ("grpc.keepalive_permit_without_calls", 1),
    ("grpc.http2.max_pings_without_data", 0),
]

_channel = grpc.secure_channel(
    "stt.api.cloud.yandex.net:443",
    grpc.ssl_channel_credentials(),
    options=GRPC_OPTIONS,
)
_stub = stt_service_pb2_grpc.RecognizerStub(_channel)

_llm_pool = ThreadPoolExecutor(max_workers=8)


def recv_exact(conn, n):
    buf = bytearray(n)
    view = memoryview(buf)
    got = 0
    while got < n:
        r = conn.recv_into(view[got:], n - got)
        if r == 0:
            return b""
        got += r
    return bytes(buf)


class YandexSession:
    def __init__(self, call_id, rate):
        self.call_id = call_id
        self.rate = rate
        self.q = queue.Queue(maxsize=64)
        self.stop = False

        self.call_started_at = now()
        self.first_audio_at = None
        self.last_partial = ""
        self.last_partial_at = 0.0
        self.last_llm_text = None

        threading.Thread(target=self.run, daemon=True).start()

    def audio(self, chunk):
        if self.first_audio_at is None:
            self.first_audio_at = now()

        # drop-oldest политика при перегрузе
        if self.q.full():
            try:
                self.q.get_nowait()
            except queue.Empty:
                pass
        self.q.put_nowait(chunk)

    def close(self):
        self.stop = True
        try:
            self.q.put_nowait(None)
        except queue.Full:
            pass

    def generator(self):
        options = stt_pb2.StreamingOptions(
            recognition_model=stt_pb2.RecognitionModelOptions(
                audio_format=stt_pb2.AudioFormatOptions(
                    raw_audio=stt_pb2.RawAudio(
                        audio_encoding=stt_pb2.RawAudio.LINEAR16_PCM,
                        sample_rate_hertz=self.rate,
                        audio_channel_count=1,
                    )
                ),
                language_restriction=stt_pb2.LanguageRestrictionOptions(
                    restriction_type=stt_pb2.LanguageRestrictionOptions.WHITELIST,
                    language_code=["ru-RU"],
                ),
            )
        )
        yield stt_pb2.StreamingRequest(session_options=options)

        while True:
            data = self.q.get()
            if data is None:
                break
            yield stt_pb2.StreamingRequest(chunk=stt_pb2.AudioChunk(data=data))

    def _ask_llm_async(self, text):
        if not text or text == self.last_llm_text:
            return
        self.last_llm_text = text

        started = now()

        def job():
            answer = ask_llm(self.call_id, text)
            print(
                f"[{self.call_id}] LLM done in {round(now() - started, 3)}s; "
                f"answer_len={len(answer) if answer else 0}"
            )

        _llm_pool.submit(job)

    def run(self):
        responses = _stub.RecognizeStreaming(
            self.generator(),
            metadata=(("authorization", f"Api-Key {YANDEX_KEY}"),),
        )

        for r in responses:
            event = r.WhichOneof("Event")

            if event == "partial":
                text = r.partial.alternatives[0].text.strip()
                ts = now()
                if text:
                    # speculative trigger: partial стабилен ~400ms
                    if text == self.last_partial and (ts - self.last_partial_at) > 0.4 and len(text) >= 20:
                        self._ask_llm_async(text)
                    self.last_partial = text
                    self.last_partial_at = ts

            elif event == "final":
                text = r.final.alternatives[0].text.strip()
                if text:
                    self._ask_llm_async(text)
```

---

## Приоритезация внедрения (быстро/эффективно)

1. **Сразу сделать**: reuse channel + bounded queue + async LLM worker.
2. **Затем**: запуск LLM по стабилизированному partial.
3. **Потом**: тонкая настройка VAD/endpointing и heuristics дедупликации.

Если нужно, могу во втором шаге дать готовый "drop-in" патч именно под ваш текущий файл с минимальным diff (без полной смены архитектуры).

# Доступ к каналу, очереди и задержки

MeshCore не имеет центрального планировщика эфира. Каждый узел самостоятельно решает, когда начать передачу. CAD, случайные задержки, очереди, приоритеты и duty-cycle budget уменьшают конфликты, но не дают детерминированной гарантии.

## Half-duplex scheduler

Основной цикл dispatcher:

```text
radio loop
→ завершение текущего TX
→ AGC/noise-floor обслуживание
→ delayed inbound queue
→ новые RX packets
→ outbound queue
```

Пока `outbound` передаётся, остальная radio activity ждёт завершения или timeout. После TX radio возвращается в receive mode.

## Channel Activity Detection

CAD ищет структуру LoRa chirp. В абстракции MeshCore radio сообщает `isReceiving()`. Если канал занят:

- фиксируется начало busy period;
- следующая проверка откладывается;
- после max duration выставляется `ERR_EVENT_CAD_TIMEOUT`;
- передача может быть принудительно начата, чтобы не зависнуть навсегда.

Base dispatcher default:

```text
CAD retry delay: 200 ms
CAD busy max:    4000 ms
```

Конкретная роль переопределяет delay случайным значением.

## Почему CAD не равен CCA Ethernet

LoRa CAD обычно обнаруживает preamble/symbol pattern, а не любую RF energy. Возможны:

- чужой LoRa profile не определяется;
- узкополосная помеха не выглядит как LoRa;
- hidden node не слышен отправителю;
- сильная соседняя частота перегружает receiver без валидного CAD;
- два узла завершают CAD одновременно.

CAD снижает риск, но packet collision остаётся нормальным событием радио mesh.

## Hidden node

```text
A ----> B <---- C
```

A и C оба слышны B, но не слышат друг друга. Каждый считает канал свободным и передаёт. В B packets перекрываются.

Random delay помогает только статистически. Решения:

- уменьшить синхронность traffic;
- добавить repeater, слышимый обеим сторонам;
- изменить размещение;
- разделить channels/scopes;
- уменьшить airtime;
- использовать retries с jitter.

## Capture effect и near-far

Если один packet намного сильнее другого, receiver иногда декодирует сильный. Это capture effect. Он не надёжен и создаёт несправедливость: близкий мощный node подавляет дальний.

Слишком высокая TX power в dense mesh может ухудшить общую доставку. Power control важен не только для батареи и закона.

## Outbound queue

`PacketManager` предоставляет:

- `queueOutbound(packet, priority, scheduled_for)`;
- `getNextOutbound(now)`;
- total/free counts;
- удаление элемента;
- inbound delayed queue.

Очередь хранит pointer на packet pool. Если pool пуст, `obtainNewPacket` выставляет `ERR_EVENT_FULL`. Входящий packet также может быть потерян, если нет свободного объекта.

## Приоритеты

В `DispatcherAction` priority кодируется в старших bits, delay — в младших 24. Текущая логика:

- direct forwarding получает высокий priority;
- flood priority ухудшается с увеличением path count;
- application может назначить отдельный priority;
- scheduled time должен наступить до выбора.

Приоритет определяет порядок среди ready packets. Он не перескакивает через текущий TX и не отменяет duty budget.

## `txdelay`

Flood delay factor `0..2`, default `0.5`. Окно масштабируется относительно estimated packet airtime. Чем длиннее packet, тем больше разумное окно, потому что collision дороже.

Настройка слишком мала:

- несколько repeaters начинают почти одновременно;
- duplicates растут;
- packet теряется на следующем hop.

Слишком велика:

- route discovery медленный;
- ACK timeout;
- queue накапливается;
- user повторяет сообщение вручную.

## `direct.txdelay`

Direct factor default `0.2`. Next hop обычно один, но delay нужен для turnaround и конкуренции с другими packets.

В сети с частыми hash collisions два узла могут считать себя next hop. Увеличение delay снижает collision, но не устраняет неправильную маршрутизацию; нужно увеличить path hash size.

## `rxdelay`

Experimental receive delay `0..20`, default `0`. Dispatcher получает packet score от radio wrapper. Delay вычисляется нелинейно и ограничивается 32 секундами.

Сильный packet обрабатывается сразу, слабый ждёт. Цель — позволить более качественной ветви flood победить и suppress слабую duplicate.

Проверять:

- median latency;
- P95/P99 latency;
- число forwarded flood;
- PDR edge nodes;
- ACK timeout;
- queue depth.

## Duty-cycle budget

Перед выбором packet dispatcher пополняет `tx_budget_ms`. Если бюджета меньше части estimated maximum packet airtime, TX откладывается.

После `TX_DONE` фактическое время вычитается. При малом остатке рассчитывается следующий момент передачи.

Следствия:

- burst быстро исчерпывает budget;
- высокий-priority ACK всё равно ждёт;
- длинный packet блокирует несколько коротких;
- queue length является ранним индикатором перегрузки;
- default 50% не означает, что radio всегда может занять половину общей сети без последствий.

## Inbound delayed queue

Flood packet с delay хранит объект pool. Большой поток слабых packets способен занять pool до обработки. Поэтому `rxdelay` и pool size связаны.

При exhaustion:

- новые RX bytes приняты radio, но packet object не выделен;
- устанавливается warning/error;
- packet теряется до routing/application.

## Radio stuck detection

Dispatcher отслеживает, находится ли radio вне RX более 8 секунд. Если да, ставится `ERR_EVENT_STARTRX_TIMEOUT`. Это сигнал:

- завис TX/IRQ;
- wrapper не вернул radio в RX;
- RF switch state неверен;
- hardware fault;
- слишком долгий blocking operation.

Error flag не всегда автоматически восстанавливает radio; требуется анализ logs и конкретной board implementation.

## Interference threshold и noise calibration

```text
get int.thresh
set int.thresh <value>
```

Значение передаётся в `triggerNoiseFloorCalibrate`. Семантика зависит от wrapper/chip. Default `0.0` обычно означает disabled/default behavior.

Нельзя переносить threshold между платами без измерения: RSSI offset и calibration различаются.

## AGC reset interval

```text
get agc.reset.interval
set agc.reset.interval <seconds>
```

Интервал округляется вниз до кратного 4, `0` отключает. Reset может помочь после сильной помехи, но создаёт момент, когда receiver не готов. Используется только при подтверждённой AGC deafness.

## Настройка по симптомам

| Симптом | Проверить |
|---|---|
| высокий flood duplicate | `txdelay`, density, hidden nodes |
| direct медленный | duty budget, queue, `direct.txdelay` |
| edge nodes пропали после `rxdelay` | слишком большой receive delay |
| `ERR_EVENT_FULL` | packet pool, queue, packet storm |
| `CAD_TIMEOUT` | постоянная активность, stuck RX, interference |
| `STARTRX_TIMEOUT` | wrapper, IRQ, RF switch, blocking code |
| ACK приходит после UI timeout | queue priority, airtime, multi-hop |

## Метод настройки

Изменять один параметр за раз:

1. сохранить baseline counters;
2. определить тестовый traffic;
3. измерить PDR, latency, duplicates, queue;
4. изменить `txdelay` или другой параметр;
5. повторить одинаковый тест;
6. проверить edge links и busy hour;
7. вернуть baseline при ухудшении.

Одновременное изменение SF, power, delay и regions не позволяет установить причину результата.

## Связанные статьи

- [LoRa-кадр и цикл радио](/wiki/lora-frame-and-radio-cycle)
- [Flood routing](/wiki/flood-routing)
- [Статистика и журналирование](/wiki/statistics-and-logging)
- [Помехи](/wiki/interference-and-radio-problems)

## Источники

- <https://github.com/meshcore-dev/MeshCore/blob/main/src/Dispatcher.cpp>
- <https://github.com/meshcore-dev/MeshCore/blob/main/src/Dispatcher.h>
- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/cli_commands.md>
- <https://www.semtech.com/products/wireless-rf/lora-connect/sx1262>

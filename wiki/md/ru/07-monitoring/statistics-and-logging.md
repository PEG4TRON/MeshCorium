# Статистика и журналирование

Диагностика MeshCore должна опираться на counters и raw events, а не на субъективное «раньше работало». Прошивка предоставляет core, radio и packet statistics, neighbor table и RX logging.

## Команды

```text
stats-core
stats-radio
stats-packets
clear stats
log start
log stop
log erase
log
neighbors
```

Часть команд serial-only. Remote request может вернуть структурированную статистику через MeshCore request/response, если роль и ACL поддерживают.

## Core stats

Обычно включают:

- battery millivolts;
- uptime;
- outbound queue length;
- free packet count;
- debug/error flags.

### Battery

Низкое напряжение влияет не только на shutdown:

- TX voltage sag снижает output/перезагружает MCU;
- PA создаёт brownout;
- ADC calibration ошибочна;
- solar node ночью меняет поведение.

Сопоставляйте battery с TX fail/reset reason.

### Uptime

Uptime показывает неожиданные reboot. Если contact «исчезает» периодически, сравните reset reason и boot voltage.

### Queue length

Растущая queue — ранний признак:

- congestion;
- duty budget exhaustion;
- CAD busy;
- packet storm;
- слишком медленного radio profile;
- зависшего TX.

Одно моментальное значение мало. Нужны maximum и time series.

### Free packets

Packet pool используется для RX, delayed inbound и outbound. Низкий free count повышает риск потерь даже при хорошем RF.

## Error flags

В current dispatcher:

| Flag | Причина |
|---|---|
| `ERR_EVENT_FULL` | packet pool allocation failed |
| `ERR_EVENT_CAD_TIMEOUT` | channel busy дольше max duration |
| `ERR_EVENT_STARTRX_TIMEOUT` | radio вне RX более 8 секунд |

`clear stats` сбрасывает counters/flags. Перед сбросом сохраните snapshot.

## Radio stats

CLI описывает:

- noise floor;
- last RSSI;
- last SNR;
- total airtime;
- receive errors.

В dispatcher отдельно учитывается TX airtime и receive airtime. Конкретный output зависит от role implementation.

### Last RSSI/SNR

Это последний packet, а не average. Нужно сопровождать timestamp и sample count.

### Total airtime

Счётчик с момента boot/clear. Для duty estimate:

```text
observed duty = total_tx_airtime / observation_time
```

Если counter в milliseconds, привести единицы. Сравнить с configured `dutycycle` и queue delays.

### RX errors

Определение зависит от wrapper: CRC/header errors, parse errors или hardware status. Документируйте version при сравнении.

## Packet stats

Опубликованный stats response может включать:

- received packets;
- sent packets;
- sent flood;
- sent direct;
- received flood;
- received direct;
- direct duplicates;
- flood duplicates;
- posted/post pushes для server roles.

Счётчики не всегда одинаково реализованы на каждой роли.

## Производные метрики

### Flood duplication factor

```text
dup_factor = flood_duplicates / unique_flood_received
```

Высокое значение нормально для dense coverage до некоторого уровня, но рост после установки repeater указывает на избыточное перекрытие или плохой `txdelay`.

### Forwarding ratio

```text
forward_ratio = sent_flood / received_flood
```

Интерпретация требует учитывать local destination, duplicates, limits и region deny.

### Direct success proxy

```text
ACK_received / direct_messages_sent
```

Нужно исключить payload, которые не ожидают ACK.

### Queue pressure

Записывать:

- average queue;
- maximum queue;
- duration above threshold;
- packet pool minimum free;
- drops/full flag.

### Airtime per useful message

```text
TX airtime / confirmed user messages
```

Рост показывает retries/flood/служебную нагрузку.

## RX logging

```text
log start
log stop
log
log erase
```

Лог на internal storage ограничен. Длинный capture может:

- заполнить flash;
- увеличить wear;
- изменить timing;
- содержать sensitive metadata;
- занять CPU/IO.

Используйте ограниченное окно и выгружайте по serial.

## Что писать в log

Минимальная строка packet:

- local timestamp;
- RX/TX;
- raw length;
- payload type;
- route F/D;
- path size/count;
- source/destination short hash, если есть;
- RSSI/SNR;
- packet hash;
- action: local/forward/drop;
- drop reason;
- scheduled delay;
- queue depth.

Raw ciphertext можно хранить для protocol debug, но он всё равно является sensitive traffic metadata.

## Синхронизация часов

Для correlation нескольких repeaters нужны часы. CLI:

```text
clock
clock sync
time <epoch_seconds>
```

Если clocks расходятся, нельзя точно определить sequence forwarding. Для millisecond analysis внешняя синхронизация и known offset важнее Unix timestamp seconds.

## Baseline

Перед изменениями сохраните:

- firmware version;
- board;
- radio profile;
- routing settings;
- region tree;
- uptime;
- counters;
- queue/free;
- noise floor;
- 10–30 минут log при обычной нагрузке.

После изменения повторите тот же период.

## Типовые картины

### Flood congestion

- `recv_flood`, `sent_flood`, duplicates быстро растут;
- queue увеличивается;
- direct ACK задерживается;
- airtime высокий;
- CAD timeout возможен.

### RF interference

- noise floor высокий;
- CRC/RX errors растут;
- sent normal, received падает;
- queue не обязательно заполнена.

### Broken direct path

- direct sent растёт;
- ACK нет;
- flood/zero-hop в целом normal;
- reset path исправляет.

### Packet pool exhaustion

- free count близок к 0;
- `ERR_EVENT_FULL`;
- bursts packets исчезают;
- delayed queue/large rxdelay или storm.

### Radio stuck

- `STARTRX_TIMEOUT`;
- RX counters перестают расти;
- reboot временно исправляет;
- проверить IRQ/RF switch/wrapper.

## Экспорт и анализ

Для long-term monitoring сохраняйте CSV/JSON вне node:

```text
timestamp,node,uptime,noise,rssi,snr,tx_airtime,rx_flood,tx_flood,dup_flood,queue,free,flags
```

Визуализировать отдельно:

- noise floor;
- queue;
- airtime rate;
- duplicate rate;
- ACK ratio;
- reboot events.

Не строить один composite score без сохранения raw metrics.

## Privacy

Logs могут раскрывать:

- public key prefixes;
- route topology;
- active times;
- message lengths;
- locations из adverts;
- admin operations.

Ограничьте доступ, срок хранения и публикацию.

## Связанные статьи

- [RSSI/SNR](/wiki/rssi-snr-and-link-quality)
- [Помехи](/wiki/interference-and-radio-problems)
- [Доступ к каналу](/wiki/channel-access-queues-and-delays)
- [Ёмкость](/wiki/capacity-and-scaling)

## Источники

- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/cli_commands.md>
- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/payloads.md>
- <https://github.com/meshcore-dev/MeshCore/blob/main/src/Dispatcher.cpp>
- <https://github.com/meshcore-dev/MeshCore/blob/main/src/Dispatcher.h>

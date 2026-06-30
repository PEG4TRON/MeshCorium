# Ёмкость и масштабирование MeshCore

Mesh-сеть не создаёт новый спектр. Каждый forwarding использует тот же airtime. При росте числа узлов flood traffic и коллизии могут расти быстрее полезной нагрузки.

![Рост радионагрузки](/attachments/ru/capacity-scaling.svg?v=2)

## Единица нагрузки

Удобно считать **radio transmissions**, а не только messages.

Direct message через `H` links:

```text
TXdata ≈ H
TXack  ≈ Hreverse
```

Flood:

```text
TXflood ≈ 1 + число repeaters, успевших переслать unique packet
```

Плюс retries, adverts, discovery, trace и responses.

## Collision domain

Capacity оценивается для группы узлов, чьи передачи взаимно мешают. Два дальних segments могут передавать одновременно, если не слышат и не перегружают общий receiver. Высокий backbone repeater объединяет их в один larger collision domain.

Поэтому network-wide sum airtime менее полезен, чем airtime на каждой критической площадке.

## Полезная загрузка

Для каждого traffic class:

```text
Load = rate · serialized_size_toa · forwarding_factor
```

Пример classes:

- personal text;
- group text;
- sensor datagram;
- flood advert;
- zero-hop advert;
- ACK;
- room sync;
- remote CLI;
- trace.

Serialized size включает path и encryption padding.

## Flood amplification

В плотной области один flood слышат `N` repeaters. Random delay и seen table уменьшают forwarding, но hidden nodes могут не услышать победителя и всё равно передать.

Amplification зависит от:

- geometry;
- `txdelay`;
- packet airtime;
- hidden nodes;
- `rxdelay`;
- duplicate cache;
- path/hash collisions;
- queue;
- `flood.max`;
- regions.

Нельзя принять forwarding factor равным одному.

## Direct efficiency

После discovery direct использует одну цепочку. Экономия особенно велика для:

- frequent peer messages;
- telemetry к одному server;
- remote management;
- room synchronization.

Но stale path создаёт failed TX и retries. Cache policy должна балансировать discovery cost и route freshness.

## Group channel

Group text обычно flood, потому что destinations множество. Popular public channel является основным capacity consumer.

Способы:

- scope region;
- ограничить flood max;
- разделить thematic channels по areas;
- не передавать media/large binary;
- rate-limit bots;
- suppress duplicate notifications;
- использовать Room Server для history вместо repeated rebroadcast, если модель подходит.

Private channel не автоматически direct. Shared key определяет шифрование, а route задаётся отдельно.

## Advert budget

Предположим 100 repeaters, каждый flood advert раз в 12 часов. Это 200 adverts/day исходно. Если каждый в среднем пересылают пять узлов, получаем около 1000 radio TX/day только для backbone adverts.

Если interval ошибочно установить 10 минут, исходный поток увеличится в 72 раза. Поэтому конфигурация одного массового fleet параметра критична.

## Sensor synchronization problem

100 sensors отправляют каждые 5 минут. Средняя rate кажется низкой, но если clocks synchronized и все TX на `:00`, возникает burst.

Решение:

```text
next_tx = nominal_period + random_jitter
```

Также полезны:

- report-on-change;
- aggregation;
- local buffering;
- no ACK для noncritical sample;
- random initial phase;
- smaller payload.

## Hop count

Если success каждого link `p`, end-to-end one-way:

```text
P = p^H
```

При `p=0.95`:

| Hop | One-way probability |
|---:|---:|
| 1 | 95% |
| 3 | 86% |
| 5 | 77% |
| 10 | 60% |

ACK round trip приблизительно умножает ещё reverse links. Поэтому route из множества marginal links имеет плохую confirmed delivery даже без congestion.

## Большой SF и capacity

Высокий SF улучшает weak-signal decoding, но пакет может занимать эфир секунды. Если весь segment перевести на «дальнобойный» profile:

- capacity падает;
- hidden-node window растёт;
- RX unavailable во время TX дольше;
- duty budget исчерпывается;
- queue/latency растут.

Лучше улучшить backbone antennas/sites и оставить умеренный profile, если topology позволяет.

## Regions как scaling boundary

Region scope уменьшает число repeaters, обрабатывающих local flood. Хорошая hierarchy соответствует реальной traffic locality:

```text
Country
├── Metro-A
│   ├── District-1
│   └── District-2
└── Metro-B
```

Большинство traffic — district/metro. Country scope используется редко.

Слишком мелкие regions увеличивают management complexity и broken paths. Слишком крупные не уменьшают load.

## Hash size и масштаб

1-byte path hash имеет высокий collision risk уже при десятках identities. 2/3-byte уменьшают route ambiguity, но увеличивают overhead.

Overhead нескольких bytes обычно дешевле duplicate branch и failed ACK. Backbone обновляют до multibyte support до роста сети.

## Room Server load

Room creates bidirectional sessions:

- login;
- sync since timestamp;
- multiple responses;
- posts;
- acknowledgements;
- keepalive.

Если 50 clients синхронизируются после outage одновременно, server и route получают burst. Нужны:

- randomized reconnect backoff;
- page/batch limits;
- maximum history;
- region-local rooms;
- queue monitoring;
- direct paths.

## Capacity targets

Не проектируйте channel на 100% theoretical airtime. Нужен reserve для:

- emergency traffic;
- retries;
- hidden nodes;
- route discovery;
- maintenance;
- variations packet size;
- external interference.

Практический target определяется test. Когда queue и latency растут нелинейно, network уже за безопасным operating point.

## Метрики saturation

- channel utilization;
- TX airtime rate;
- queue P95/max;
- packet pool minimum;
- CAD busy duration;
- duplicate ratio;
- ACK ratio;
- median/P95 latency;
- retries per confirmed message;
- flood/direct ratio.

### Ранние признаки

- сообщения иногда задерживаются, но доходят;
- ACK приходит после UI timeout;
- duplicates растут быстрее unique traffic;
- queue не возвращается к нулю;
- busy period ухудшается сильнее среднего.

### Congestion collapse

- retries доминируют;
- queue постоянно full;
- packet pool exhaustion;
- direct traffic теряется за flood;
- duty budget не восстанавливается;
- users повторяют вручную, усиливая нагрузку.

## План масштабирования

1. измерить current load;
2. классифицировать traffic;
3. перевести повторяющиеся peer flows на direct;
4. ограничить adverts;
5. ввести regions;
6. уменьшить sensor bursts;
7. обновить path hash mode;
8. отключить избыточные repeaters;
9. улучшить слабые links;
10. при необходимости разделить radio channels и создать controlled bridge.

## Controlled bridge

Разделение на два PHY channels повышает spatial/frequency capacity, но bridge должен:

- передавать только разрешённые application messages;
- сохранять message ID;
- не отражать packet обратно;
- rate-limit;
- преобразовывать scopes;
- логировать loops;
- иметь security boundary.

Простая ретрансляция raw packets между channels способна создать вечный loop.

## Capacity worksheet

Для каждого flow:

| Flow | Rate/h | Bytes | ToA | Avg forward TX | ACK TX | Airtime/h |
|---|---:|---:|---:|---:|---:|---:|
| Local text | | | | | | |
| Group | | | | | | |
| Sensor | | | | | | |
| Advert | | | | | | |
| Admin | | | | | | |

Добавьте 30–100% reserve в зависимости от uncertainty, затем подтвердите field test.

## Связанные статьи

- [Airtime и duty cycle](/wiki/airtime-duty-cycle-and-capacity)
- [Flood routing](/wiki/flood-routing)
- [Regions](/wiki/regions-and-transport-codes)
- [Статистика](/wiki/statistics-and-logging)

## Источники

- <https://github.com/meshcore-dev/MeshCore/blob/main/src/Dispatcher.cpp>
- <https://github.com/meshcore-dev/MeshCore/blob/main/src/Mesh.cpp>
- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/cli_commands.md>

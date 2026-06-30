# Служебные payload MeshCore

Служебные пакеты поддерживают существование mesh: объявляют identity, подтверждают доставку, возвращают путь, измеряют маршрут и выполняют локальное discovery. Они занимают тот же airtime, что пользовательские сообщения, поэтому их частота влияет на ёмкость сети.

## `PAYLOAD_TYPE_ADVERT`

Advert объявляет существование узла и его публичные свойства.

| Поле | Размер |
|---|---:|
| public key | 32 байта |
| timestamp | 4 байта |
| signature | 64 байта |
| appdata | оставшиеся байты |

Appdata:

| Поле | Размер | Условие |
|---|---:|---|
| flags | 1 | всегда при наличии appdata |
| latitude | 4 | `has location` |
| longitude | 4 | `has location` |
| feature 1 | 2 | reserved flag |
| feature 2 | 2 | reserved flag |
| name | остаток | `has name` |

Flags узла:

| Значение | Тип/поле |
|---:|---|
| `0x01` | chat node |
| `0x02` | repeater |
| `0x03` | room server |
| `0x04` | sensor |
| `0x10` | location присутствует |
| `0x20` | feature 1 |
| `0x40` | feature 2 |
| `0x80` | name присутствует |

Первые четыре значения представляют тип в младших bits, а не независимые bit flags. Код должен извлекать тип согласно реализации, а не проверять `flags & 0x03` как два одновременных признака.

Signature проверяет public key, timestamp и appdata. Подделанный advert отбрасывается. Старый, но корректно подписанный advert требует отдельной политики freshness.

## `PAYLOAD_TYPE_ACK`

Payload ACK:

```text
checksum: 4 bytes
```

Checksum — CRC от timestamp, текста и sender public key исходного сообщения. ACK связывает подтверждение с конкретным сообщением без повторения всего payload.

ACK может быть:

- отдельным packet;
- `extra` внутри returned path;
- частью multipart/Multi-ACK последовательности.

CLI command не вызывает обычный ACK по тем же правилам.

## `PAYLOAD_TYPE_PATH`

Внешне PATH использует address wrapper и шифрование peer secret. Plaintext:

| Поле | Размер |
|---|---:|
| path length | 1 байт |
| path | size × count |
| extra type | 1 байт |
| extra | остаток |

Returned path описывает маршрут от получателя к автору исходного сообщения. `extra type` может быть ACK или RESPONSE, чтобы не отправлять отдельный packet.

Если extra отсутствует, текущая реализация добавляет dummy type `0xFF` и случайные байты, чтобы packet hash был уникальным.

## `PAYLOAD_TYPE_TRACE`

Trace следует по заданному direct path и собирает SNR каждого hop. В текущем коде packet содержит:

- trace tag;
- auth code;
- flags, включая размер path identity;
- supplied path в payload;
- накопленные SNR в packet path area.

Каждый промежуточный узел проверяет, что его identity является следующей, затем добавляет `SNR × 4`. В конце получатель вызывает trace callback.

Trace показывает качество конкретных приёмов в момент теста. Он не измеряет постоянный link budget и не гарантирует симметрию обратного пути.

## `PAYLOAD_TYPE_MULTIPART`

Первый byte payload:

```text
upper 4 bits: remaining count
lower 4 bits: embedded payload type
```

Текущая общая реализация явно обрабатывает multipart ACK. Другие embedded types помечены как future/implementation-specific.

Нельзя считать multipart универсальной fragmentation layer для произвольного большого сообщения. Для этого нужны:

- sequence ID;
- ordering;
- timeout;
- deduplication;
- maximum total size;
- retransmission policy.

Текущий format этих свойств не определяет полностью.

## `PAYLOAD_TYPE_CONTROL`

Control data обычно не шифруется. Первый flags byte:

```text
upper 4 bits: subtype
lower bits: subtype-specific flags
```

Опубликованные discovery subtypes:

### `DISCOVER_REQ`

| Поле | Размер |
|---|---:|
| flags | 1 |
| type filter | 1 |
| tag | 4 |
| since | 4, опционально |

Subtype `0x8` находится в upper nibble. Lowest bit обозначает `prefix_only`. Random tag связывает ответы с запросом.

### `DISCOVER_RESP`

| Поле | Размер |
|---|---:|
| flags | 1 |
| SNR | 1, signed ×4 |
| tag | 4 |
| public key | 8 или 32 |

Subtype `0x9`; lower nibble содержит node type. Ответ отражает tag запроса.

В `Mesh.cpp` часть control packets допускается только zero-hop: если direct control имеет непустой path, он освобождается без дальнейшей обработки. Это ограничивает локальное discovery.

## Reserved `0x0C–0x0E`

Зарезервированные типы не имеют опубликованного формата. Правила:

- не использовать в общей сети;
- не строить зависимость от текущего drop behavior;
- не предполагать будущую семантику;
- для эксперимента использовать `RAW_CUSTOM` или отдельный test network.

## Служебный трафик и масштабирование

Advert размером более 100 байт при высоком SF может находиться в эфире заметно дольше короткого текста. Flood advert повторяется несколькими узлами. Discovery вызывает request и множество responses. Trace проходит по каждому hop и возвращает данные.

Поэтому служебные механизмы запускают по необходимости:

- редкие flood adverts для стационарных узлов;
- zero-hop discovery для локальной диагностики;
- trace во время troubleshooting, а не постоянно;
- Multi-ACK только при оправданной модели потерь;
- region scope для ограничения распространения.

## Сводка

| Тип | Публичный | Зашифрован | Обычно маршрутизируется |
|---|---|---|---|
| ADVERT | да | нет, но подписан | zero-hop или flood |
| ACK | checksum видим | сам ACK не содержит текста | direct/flood по контексту |
| PATH | wrapper видим | да | возвращается автору |
| TRACE | маршрутные данные | auth зависит от реализации | direct |
| MULTIPART | subtype видим | зависит от embedded type | чаще direct ACK |
| CONTROL | обычно да | обычно нет | часть только zero-hop |

## Связанные статьи

- [Advert, discovery и соседи](/wiki/adverts-discovery-and-neighbors)
- [ACK, повторы и multipart](/wiki/acknowledgements-retries-and-multipart)
- [Trace](/wiki/trace-and-route-diagnostics)
- [Airtime и ёмкость](/wiki/airtime-duty-cycle-and-capacity)

## Источники

- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/payloads.md>
- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/packet_format.md>
- <https://github.com/meshcore-dev/MeshCore/blob/main/src/Mesh.cpp>
- <https://github.com/meshcore-dev/MeshCore/blob/main/src/Packet.h>

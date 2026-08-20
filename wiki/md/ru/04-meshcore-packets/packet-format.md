# Формат MeshCore-пакета

Текущий опубликованный Packet Format v1 задаёт единый контейнер для маршрутизации и разных типов payload. Радиочип воспринимает весь контейнер как LoRa payload.

![Формат MeshCore-пакета](/attachments/ru/meshcore-packet.svg?v=2)

## Общая структура

```text
[header][transport_codes optional][path_length][path][payload]
```

| Поле | Размер | Назначение |
|---|---:|---|
| `header` | 1 байт | route type, payload type, payload version |
| `transport_codes` | 4 байта, опционально | два `uint16_t` для transport route |
| `path_length` | 1 байт | кодирует число path hash и их размер |
| `path` | 0–64 байта | последовательность промежуточных идентификаторов |
| `payload` | 0–184 байта | данные, формат зависит от payload type |

Константы текущей реализации:

```text
MAX_PACKET_PAYLOAD = 184
MAX_PATH_SIZE      = 64
MAX_TRANS_UNIT     = 255
```

Общая длина должна помещаться в `MAX_TRANS_UNIT`. Нельзя независимо заполнить path на 64 байта и payload на 184 байта вместе с transport codes: итог превысит 255.

## Header `VVPPPPRR`

Биты нумеруются от младшего:

```text
bit 7                           bit 0
+----+----+----+----+----+----+----+----+
| V  | V  | P  | P  | P  | P  | R  | R  |
+----+----+----+----+----+----+----+----+
```

- `RR`, bits 0–1 — route type;
- `PPPP`, bits 2–5 — payload type;
- `VV`, bits 6–7 — payload version.

Маски в `Packet.h`:

```text
PH_ROUTE_MASK = 0x03
PH_TYPE_MASK  = 0x0F
PH_VER_MASK   = 0x03
```

## Route type

| Значение | Константа | Смысл |
|---:|---|---|
| `0x00` | `ROUTE_TYPE_TRANSPORT_FLOOD` | flood с transport codes |
| `0x01` | `ROUTE_TYPE_FLOOD` | обычный flood |
| `0x02` | `ROUTE_TYPE_DIRECT` | direct path |
| `0x03` | `ROUTE_TYPE_TRANSPORT_DIRECT` | direct с transport codes |

Transport route добавляет четыре байта сразу после header. Парсер определяет их наличие только по route bits. Ошибка в route type сдвигает границы всех следующих полей.

## Payload type

| Значение | Константа | Назначение |
|---:|---|---|
| `0x0` | `PAYLOAD_TYPE_REQ` | адресный запрос |
| `0x1` | `PAYLOAD_TYPE_RESPONSE` | ответ |
| `0x2` | `PAYLOAD_TYPE_TXT_MSG` | личное текстовое сообщение |
| `0x3` | `PAYLOAD_TYPE_ACK` | подтверждение |
| `0x4` | `PAYLOAD_TYPE_ADVERT` | объявление identity |
| `0x5` | `PAYLOAD_TYPE_GRP_TXT` | групповой текст |
| `0x6` | `PAYLOAD_TYPE_GRP_DATA` | групповой datagram |
| `0x7` | `PAYLOAD_TYPE_ANON_REQ` | запрос неизвестного отправителя |
| `0x8` | `PAYLOAD_TYPE_PATH` | возвращённый путь |
| `0x9` | `PAYLOAD_TYPE_TRACE` | trace с SNR по hop |
| `0xA` | `PAYLOAD_TYPE_MULTIPART` | элемент последовательности |
| `0xB` | `PAYLOAD_TYPE_CONTROL` | control/discovery |
| `0xC–0xE` | reserved | не использовать как готовые функции |
| `0xF` | `PAYLOAD_TYPE_RAW_CUSTOM` | приложение определяет содержимое |

Payload type говорит, как интерпретировать оставшиеся байты. Он не определяет маршрут: один и тот же тип может быть flood или direct, если реализация это разрешает.

## Payload version

| Bits `VV` | Версия | Состояние |
|---:|---:|---|
| `00` | 1 | текущая опубликованная версия |
| `01` | 2 | зарезервировано для будущего |
| `10` | 3 | зарезервировано |
| `11` | 4 | зарезервировано |

Текущий `Dispatcher::tryParsePacket` отклоняет версию выше `PAYLOAD_VER_1`. Нельзя установить v2 ради эксперимента и ожидать, что существующие repeaters просто перешлют такой пакет.

## Transport codes

Поле состоит из:

```text
transport_code_1: uint16 little-endian
transport_code_2: uint16 little-endian
```

Первый код рассчитывается из region scope. Второй зарезервирован. Нулевое или неизвестное значение нельзя автоматически трактовать как глобальный доступ: решение принимает region policy узла.

Подробности: [Regions и transport codes](/wiki/regions-and-transport-codes).

## Кодирование `path_length`

Это не число байт. Поле объединяет два значения:

```text
bits 0..5: hash count, 0..63
bits 6..7: hash size - 1
```

| Верхние биты | Размер одной записи |
|---:|---:|
| `00` | 1 байт |
| `01` | 2 байта |
| `10` | 3 байта |
| `11` | reserved/invalid |

Фактическая длина:

```text
path_bytes = hash_count · hash_size
```

Примеры:

| `path_length` | Расшифровка | Path bytes |
|---:|---|---:|
| `0x00` | 0 записей по 1 байту | 0 |
| `0x05` | 5 записей по 1 байту | 5 |
| `0x45` | 5 записей по 2 байта | 10 |
| `0x8A` | 10 записей по 3 байта | 30 |

Предел `hash_count=63` не означает, что 63 записи всегда помещаются. При размере 2 байта максимум по `MAX_PATH_SIZE` равен 32, при 3 байтах — 21.

## Path в flood и direct

В flood каждый пересылающий узел добавляет свой hash в конец. Path растёт наружу от источника.

В direct path предоставляется отправителем. Следующий repeater сравнивает первую запись со своей identity, удаляет её и пересылает остаток.

Одинаковое поле используется по-разному, поэтому route type обязателен для интерпретации.

## Payload

Payload — остаток массива после path. Отдельного поля длины нет: она вычисляется из общей длины LoRa payload и уже разобранных полей.

Это означает:

- повреждённый `path_length` меняет границу payload;
- parser обязан проверять выход за буфер;
- неизвестный payload type нельзя безопасно трактовать как текст;
- padding encrypted payload может присутствовать до границы AES block.

## Little Endian

Публичная документация указывает, что 16- и 32-битные integer fields payload используют little endian. Transport codes также копируются как `uint16_t` в текущем коде. Реализация на другой архитектуре должна сериализовать явно, а не копировать native struct без проверки порядка байтов.

## Валидация входящего пакета

Текущий parser выполняет минимум:

1. читает header;
2. отклоняет unsupported payload version;
3. при transport route читает 4 байта codes;
4. читает `path_length`;
5. отклоняет path mode `3`;
6. вычисляет `path_byte_len`;
7. проверяет `MAX_PATH_SIZE` и фактическую длину raw buffer;
8. считает оставшиеся байты payload;
9. отклоняет payload больше 184 байт.

После этого payload-specific code обязан проверить собственные минимальные длины. Например, address wrapper должен содержать destination hash, source hash и MAC.

## Packet hash и дубли

`Packet::calculatePacketHash` формирует идентификатор для seen table. Точное содержимое важно для duplicate suppression: изменение route metadata или payload может привести к другому hash и повторной ретрансляции.

Packet hash не равен path hash:

- packet hash идентифицирует конкретную передачу/содержимое;
- path hash — короткий идентификатор узла внутри маршрута.

## Специальное значение `header = 0xFF`

Внутри объекта `Packet` значение `0xFF` используется как marker «не ретранслировать». Это внутреннее состояние после обработки пакета для локального узла. Не следует считать `0xFF` отдельным wire-format packet type.

## Разбор вручную

Допустим, raw начинается:

```text
09 03 A1 B2 C3 ...
```

`0x09 = 00001001b`:

- route bits `01` → flood;
- payload bits `0010` → TXT_MSG;
- version bits `00` → v1.

Следующий `0x03` — три 1-byte path hash. Байты `A1 B2 C3` — path. Остаток — address wrapper и encrypted text payload.

Реальный анализатор должен учитывать transport route: там после header сначала идут четыре байта codes.

## Совместимость

Firmware v1.12 и старее работала с legacy 1-byte path hash и могла отбрасывать multibyte path. Сеть с несколькими версиями должна сначала обновить forwarding backbone, затем включать новые hash modes на источниках advert/messages.

Зарезервированные version и payload type нельзя использовать для локального эксперимента в общей сети: старые repeaters могут drop, а будущая версия — назначить другое значение.

## Связанные статьи

- [Пользовательские payload](/wiki/user-payloads)
- [Служебные payload](/wiki/service-payloads)
- [Path hash, дубли и петли](/wiki/path-hashes-duplicates-and-loops)
- [Совместимость и миграция](/wiki/compatibility-and-migration)

## Источники

- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/packet_format.md>
- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/payloads.md>
- <https://github.com/meshcore-dev/MeshCore/blob/main/src/Packet.h>
- <https://github.com/meshcore-dev/MeshCore/blob/main/src/Dispatcher.cpp>
- <https://github.com/meshcore-dev/MeshCore/blob/main/src/MeshCore.h>

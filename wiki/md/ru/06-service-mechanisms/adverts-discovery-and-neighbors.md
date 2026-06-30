# Advert, discovery и соседи

MeshCore использует несколько механизмов обнаружения. Advert распространяет подписанную identity и свойства узла. Control discovery запрашивает локальные узлы. Таблица neighbors на repeater хранит недавние zero-hop объявления. Эти механизмы связаны, но не являются одной routing table.

## Advert как публичная карточка

`PAYLOAD_TYPE_ADVERT` содержит:

```text
public_key  32 bytes
timestamp    4 bytes
signature   64 bytes
appdata      variable
```

Signature Ed25519 вычисляется по `public_key + timestamp + appdata`. Получатель может проверить, что advert сформирован владельцем identity и не изменён в пути.

Advert не шифруется. Любой приёмник видит:

- public key;
- время;
- тип узла;
- имя;
- координаты, если опубликованы;
- path и region metadata packet.

Не следует помещать в имя или owner info данные, которые должны оставаться секретными.

## Appdata flags

Опубликованный формат:

| Значение | Смысл |
|---:|---|
| `0x01` | chat/companion |
| `0x02` | repeater |
| `0x03` | room server |
| `0x04` | sensor |
| `0x10` | есть latitude/longitude |
| `0x20` | feature 1 reserved |
| `0x40` | feature 2 reserved |
| `0x80` | есть name |

Тип `0x01–0x04` — код роли в младшей части flags. Остальные bits сообщают наличие полей.

Координаты хранятся как signed integer:

```text
stored = degrees · 1 000 000
```

Например, `52.520000` → `52520000`.

## Ограничение appdata

`MAX_ADVERT_DATA_SIZE = 32`. В эти 32 байта входят flags, координаты, features и имя.

По CLI максимальная длина name:

- до 32 bytes без location;
- до 24 bytes с location.

Это bytes, не Unicode characters. Кириллица в UTF-8 обычно занимает два байта на букву, emoji — больше. Клиент должен безопасно обрезать по границе UTF-8 sequence.

## Flood advert

Команда:

```text
advert
```

Создаёт flood advert. Repeaters добавляют path. Получатель может сохранить identity и путь, по которому advert пришёл.

Плюсы:

- обнаружение за несколько hop;
- обновление contact metadata;
- построение route к источнику;
- карта repeaters.

Цена:

- advert крупный из-за public key и signature;
- каждый forwarding повторяет его airtime;
- dense mesh получает много дублей;
- частый interval перегружает channel.

## Zero-hop advert

Команда:

```text
advert.zerohop
```

Пакет не должен распространяться дальше локальной радиозоны. Он полезен для:

- проверки radio profile;
- neighbor discovery;
- локальной настройки;
- обновления ближайших устройств без flood;
- диагностики антенны и SNR.

Zero-hop advert не подтверждает multi-hop connectivity.

## Интервалы

### Flood

```text
get flood.advert.interval
set flood.advert.interval <3..168 hours>
```

Документированные defaults:

- Repeater: 12 часов;
- Sensor: 0.

`0` обычно отключает периодическую функцию, но поведение проверяется по роли/версии.

### Zero-hop

```text
get advert.interval
set advert.interval <60..240 minutes>
```

Значение округляется вниз к кратному двум. Default `0`.

Периодический zero-hop advert полезен для neighbor table, но большое число локальных узлов всё равно занимает общий канал.

## Timestamp и freshness

Signature доказывает целостность timestamp, но не гарантирует правильные часы. Узел с неверным временем может публиковать advert «из будущего» или очень старый.

Клиенту нужна policy:

- не принимать старый metadata поверх нового;
- учитывать reboot/clock reset;
- не удалять contact только по возрасту advert;
- показывать last heard отдельно от advertised timestamp.

`last heard` — локальное время приёма. `advert timestamp` — время отправителя.

## Control discovery

`PAYLOAD_TYPE_CONTROL` subtypes `DISCOVER_REQ` и `DISCOVER_RESP` предназначены для локального поиска.

### Request

```text
flags       1 byte
type_filter 1 byte
tag         4 bytes
since       4 bytes optional
```

- upper nibble `0x8` — request subtype;
- lowest bit — `prefix_only`;
- `type_filter` выбирает роли;
- `tag` — случайный correlation ID;
- `since` ограничивает ответы по времени.

### Response

```text
flags  1 byte
snr    1 byte signed, SNR×4
tag    4 bytes
pubkey 8 or 32 bytes
```

- upper nibble `0x9`;
- lower nibble — node type;
- tag копируется из request;
- key может быть prefix или полный.

## Почему discovery zero-hop

В `Mesh.cpp` соответствующий subset control packets обрабатывается только при пустом path. Это предотвращает лавину responses через всю mesh и ограничивает утечку локального topology.

Для многохопового поиска используются adverts и path discovery, а не broadcast control query.

## Таблица neighbors

Команда repeater:

```text
neighbors
```

Вывод ограничен восемью наиболее свежими adverts. Каждая строка:

```text
{pubkey-prefix}:{timestamp}:{snr*4}
```

Таблица показывает недавних zero-hop соседей, а не:

- все reachable nodes;
- все сохранённые contacts;
- все hop direct path;
- гарантированно двусторонние links;
- текущих online users.

Advert мог быть принят один раз, после чего сосед исчез.

## Удаление и повторное discovery

```text
neighbor.remove <pubkey_prefix>
discover.neighbors
```

Prefix может совпасть с несколькими entries. Пустой prefix/space по документации удаляет все совпадающие entries. Удаление не блокирует узел: следующий advert добавит его снова.

`discover.neighbors` инициирует локальный запрос, после чего ответы обновляют таблицу.

## Auto-add contacts

Companion firmware имеет auto-add flags для типов advert и режим overwrite oldest. Это функция хранения контактов, не radio routing. Получение advert не обязано автоматически создавать contact: пользовательская политика может требовать ручного подтверждения.

Автоматическое добавление в публичной плотной сети опасно:

- contact table заполняется;
- oldest entry вытесняется;
- malicious adverts создают churn;
- hash collisions усложняют выбор.

## Advert path

Companion может запросить сохранённый advert path (`CMD_GET_ADVERT_PATH`). Это маршрут, по которому конкретный advert достиг устройства. Он полезен как кандидат direct path, но:

- может устареть;
- является first-wins;
- может содержать mobile repeater;
- обратная линия может быть хуже;
- размер hash должен сохраняться вместе с count.

## Диагностика

### Нет zero-hop advert

Проверить:

- frequency/BW/SF/CR;
- sync word и firmware family;
- antenna;
- RSSI/noise floor;
- RX state;
- packet parser/log.

### Zero-hop есть, flood нет

Проверить:

- `repeat` на соседнем repeater;
- `flood.max.advert`;
- region policy;
- seen/loop detection;
- path hash compatibility;
- duty budget и queue.

### Advert есть, сообщения не идут

Advert публичен и не требует peer secret. Проверить contact key, path, encryption/MAC и обратный ACK.

## Связанные статьи

- [Служебные payload](/wiki/service-payloads)
- [Flood routing](/wiki/flood-routing)
- [RSSI/SNR](/wiki/rssi-snr-and-link-quality)

## Источники

- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/payloads.md>
- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/cli_commands.md>
- <https://github.com/meshcore-dev/MeshCore/blob/main/src/Mesh.cpp>
- <https://github.com/meshcore-dev/MeshCore/blob/main/examples/companion_radio/MyMesh.cpp>

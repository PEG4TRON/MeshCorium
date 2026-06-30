# Path hash, дубли и петли

Для экономии airtime MeshCore помещает в path не полный 32-byte public key, а короткий prefix/hash. Чем короче запись, тем больше hop помещается в packet, но тем выше вероятность совпадения identities.

![Размеры path hash](/attachments/ru/path-hash.svg?v=2)

## Кодирование размера

В `path_length`:

- bits 0–5 — count;
- bits 6–7 — `hash_size - 1`.

| Mode | Entry | Возможных значений | Максимум по 64-byte path |
|---:|---:|---:|---:|
| 0 | 1 байт | 256 | 64 entries |
| 1 | 2 байта | 65 536 | 32 entries |
| 2 | 3 байта | 16 777 216 | 21 entries |
| 3 | 4 байта | reserved | unsupported |

CLI `path.hash.mode` на repeater задаёт размер hash, используемый в **его собственных adverts**. По документации firmware ≥1.14 должна forward packets всех поддерживаемых размеров независимо от локального mode.

## Коллизия hash

Коллизия означает, что два public keys имеют одинаковый короткий prefix. Вероятность быстро растёт из-за birthday effect.

При случайном распределении приблизительная вероятность хотя бы одной коллизии:

```text
P ≈ 1 - exp(-n(n-1)/(2N))
```

где `N` — число возможных hash.

Ориентиры:

| Узлов | Размер | Вероятность хотя бы одной коллизии |
|---:|---:|---:|
| 20 | 1 байт | около 52% |
| 50 | 1 байт | около 99% |
| 100 | 2 байта | около 7% |
| 500 | 2 байта | около 85% |
| 1000 | 3 байта | около 3% |

Это вероятность где-то во множестве, а не вероятность ошибки конкретного path. Но она показывает, почему 1-byte mode плохо масштабируется для уникальной идентификации большой сети.

## Что происходит при path collision

В direct packet первый entry может совпасть у двух соседей. Оба могут решить, что являются next hop, и переслать пакет. Последствия:

- разветвление direct route;
- лишние дубли;
- разные оставшиеся path;
- коллизии TX;
- неожиданный loop;
- рост duplicate counters.

Seen table может подавить часть копий, но не гарантирует правильный выбор, особенно если ветви не слышат друг друга.

В destination/source hash коллизия решается попыткой MAC/decrypt нескольких контактов. В path нет криптографической проверки next hop, поэтому больший hash снижает неоднозначность.

## Packet hash и path hash — разные вещи

**Path hash** идентифицирует узел внутри route.

**Packet hash** идентифицирует packet для duplicate suppression. Он вычисляется из packet type/payload согласно реализации и хранится в seen table.

Нельзя использовать path hash как message ID или packet hash как identity.

## Seen table

При первом packet узел записывает hash. Следующие копии отбрасываются. Seen table должна иметь:

- ограниченный размер;
- policy вытеснения;
- время жизни либо циклическую замену;
- защиту от заполнения мусорным трафиком.

Если таблица мала относительно потока, старый packet может быть вытеснен до прихода поздней копии и снова forwarded.

## First packet wins

Duplicate suppression превращает первую копию в победителя. Это экономит airtime, но скрывает альтернативы. Для диагностики полезно смотреть raw RX log до suppression или специальные path/trace данные.

## Routing loop

Loop — packet проходит через один и тот же repeater повторно. В корректном flood path собственный hash уже присутствует, но legacy 1-byte collision делает простую проверку неоднозначной. Поэтому MeshCore предоставляет уровни `loop.detect`.

### `off`

Путь не проверяется на повтор собственного hash. Обычный duplicate cache и max hop остаются единственной защитой.

### `minimal`

Drop, если собственный hash уже встречается:

- 4 раза для 1-byte;
- 2 раза для 2-byte;
- 1 раз для 3-byte.

Режим допускает случайные коллизии коротких hash.

### `moderate`

Пороги:

- 2 для 1-byte;
- 1 для 2-byte;
- 1 для 3-byte.

### `strict`

Drop при первом совпадении для всех размеров.

Strict лучше останавливает loop, но в 1-byte сети может принять hash другого узла за собственный и обрезать легитимный flood.

## Packet storm

Обычный loop должен быть остановлен seen table: тот же packet hash уже известен. Шторм становится опасным, если каждый forwarding меняет packet так, что hash становится новым.

Возможные причины:

- custom firmware модифицирует payload/path неправильно;
- bridge перепаковывает данные;
- поле timestamp обновляется на каждом hop;
- padding содержит нестабильные bytes;
- повреждение памяти;
- несовместимый packet format.

Тогда packet проходит до `flood.max` или заполнения path, создавая десятки передач.

## Выбор hash mode

### 1 byte

Плюсы:

- совместимость с legacy;
- минимальный overhead;
- до 64 path entries.

Минусы:

- частые коллизии в больших сетях;
- strict loop detection даёт false positive;
- сложнее анализировать topology.

### 2 bytes

Компромисс для средних сетей. 32 hop по storage обычно достаточно, а риск коллизии существенно ниже.

### 3 bytes

Подходит для больших identity spaces, но ограничивает path 21 hop и увеличивает airtime каждого packet. Большое число hop само по себе плохо для ёмкости, поэтому этот предел редко является главным недостатком.

## Совместимость

Согласно CLI:

- feature добавлена в районе firmware 1.13/1.14;
- v1.13 и старше могут drop multibyte paths;
- firmware ≥1.14 должна forward все размеры;
- менять mode следует после достижения достаточной доли обновлённых repeaters.

В mixed network можно временно оставить sources/adverts на 1 byte, даже если backbone уже умеет 2/3 bytes.

## Диагностика коллизии

Признаки:

- direct packet пересылают два узла;
- path details показывают одинаковые prefixes;
- strict loop detector отбрасывает packet в месте без реальной петли;
- удаление одного repeater внезапно исправляет маршрут;
- 2-byte mode решает проблему.

Подтверждение требует полных public keys соседей, а не только prefixes.

## Безопасность

Короткий path hash не предназначен для аутентификации. Злоумышленник может подобрать identity с нужным prefix и попытаться стать next hop. Payload encryption не раскрывает текст, но malicious forwarder может:

- drop;
- задержать;
- повторить;
- анализировать metadata;
- создать route instability.

Больший path hash повышает стоимость prefix matching, но не заменяет cryptographic routing authentication.

## Практическая политика

1. обновить все критические repeaters до версии с multibyte forwarding;
2. собрать число уникальных identities;
3. проверить максимальную реальную длину route;
4. включить 2-byte adverts на ограниченной группе;
5. проверить flood propagation и direct paths;
6. включить `loop.detect moderate` или `strict` там, где collision risk допустим;
7. мониторить duplicates и drops;
8. переходить на 3 bytes только при обоснованной необходимости.

## Связанные статьи

- [Формат пакета](/wiki/packet-format)
- [Flood routing](/wiki/flood-routing)
- [Совместимость и миграция](/wiki/compatibility-and-migration)
- [Угрозы](/wiki/security-threats)

## Источники

- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/packet_format.md>
- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/cli_commands.md>
- <https://github.com/meshcore-dev/MeshCore/blob/main/src/Packet.h>

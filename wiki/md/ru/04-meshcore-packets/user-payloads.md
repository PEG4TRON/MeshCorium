# Пользовательские payload MeshCore

Пользовательские payload переносят текст, запросы, ответы и прикладные datagram. Они используют общий packet container, но имеют разные wrappers и модели доверия.

## Личное адресное сообщение

Типы `REQ`, `RESPONSE`, `TXT_MSG` и `PATH` используют адресный encrypted wrapper:

| Поле | Размер | Значение |
|---|---:|---|
| destination hash | 1 байт | первый байт public key адресата для v1 |
| source hash | 1 байт | первый байт public key отправителя |
| cipher MAC | 2 байта | усечённый HMAC ciphertext |
| ciphertext | остаток | AES-encrypted application data |

Hash только выбирает кандидата. Окончательное совпадение определяется успешной MAC verification с secret конкретного контакта.

## `PAYLOAD_TYPE_TXT_MSG`

Plaintext:

| Поле | Размер |
|---|---:|
| timestamp | 4 байта |
| `txt_type + attempt` | 1 байт |
| message | остаток |

В flags byte:

- верхние 6 бит — `txt_type`;
- нижние 2 бита — attempt `0..3`.

Документированные `txt_type`:

| Значение | Смысл |
|---:|---|
| `0x00` | plain text |
| `0x01` | CLI command |
| `0x02` | signed plain text |

### Timestamp

Timestamp помогает уникализировать сообщение, синхронизировать историю и рассчитывать ACK checksum. Неверные часы могут создавать:

- странный порядок сообщений;
- конфликт duplicate logic;
- отказ server request с проверкой времени;
- невозможность корректной синхронизации.

MeshCore имеет команды `clock`, `clock sync` и `time` для управляемых узлов.

### Attempt

Два младших бита позволяют обозначить до четырёх попыток. Повтор должен сохранять семантику исходного сообщения, но отличаться там, где protocol ожидает новый packet hash/attempt.

Клиент не должен бесконечно повторять без ACK: это создаёт flood amplification.

### CLI command

CLI message несёт командный текст внутри зашифрованного адресного сообщения. Удалённый узел дополнительно проверяет login/ACL. CLI command не получает обычный discrete ACK по тем же правилам, что пользовательский текст; результат возвращается response/text согласно реализации.

### Signed text

Signed text начинается с четырёх байт sender public-key prefix, затем идёт текст и связанная подпись/прикладная структура конкретного клиента. Наличие типа не означает, что все интерфейсы отображают или проверяют его одинаково. Для interoperable реализации нужно сверять companion protocol и клиентский код.

## `PAYLOAD_TYPE_REQ`

После decrypt:

```text
timestamp: 4 bytes
request data: application-defined
```

В `BaseChatMesh` общие request types включают:

| Значение | Название | Смысл |
|---:|---|---|
| `0x01` | get stats | запрос статистики repeater/room |
| `0x02` | keepalive | поддержание логического соединения |

Другие запросы могут определяться Sensor, Room Server или custom firmware. Нельзя считать любое первое значение общим глобальным registry без проверки реализации.

## `PAYLOAD_TYPE_RESPONSE`

Response body является opaque application data. Универсального envelope поверх encrypted wrapper нет. Формат выбирается запросом и ролью сервера.

Разработчик должен знать:

- какой request инициировал response;
- ожидаемую длину;
- endianness полей;
- version прикладной schema;
- timeout и возможность нескольких ответов.

## `PAYLOAD_TYPE_GRP_TXT`

Wrapper:

| Поле | Размер |
|---|---:|
| channel hash | 1 байт |
| cipher MAC | 2 байта |
| ciphertext | остаток |

Plaintext совпадает с text message: timestamp, flags и строка. Обычный group text имеет вид:

```text
<sender name>: <message body>
```

Sender name является данными, которые может сформировать любой владелец channel secret. Group channel не подтверждает индивидуального автора.

### Channel hash

Channel hash — первый байт SHA-256 shared key. При коллизии клиент пробует известные каналы с тем же hash и проверяет MAC. Как и address hash, это индекс, а не криптографически уникальный ID.

## `PAYLOAD_TYPE_GRP_DATA`

Wrapper тот же, plaintext:

| Поле | Размер |
|---|---:|
| data type | 2 байта |
| data len | 1 байт |
| data | указанная длина |

`data type` выделяет namespace приложения. Официальный `number_allocations.md` содержит ranges:

| Range | Назначение |
|---|---|
| `0000–00FF` | internal/reserved |
| `0100` | MeshCore Open |
| `0110–011F` | Ripple |
| `FF00–FFFF` | development/POC |

Для разработки следует использовать dev range. Публикуемый проект запрашивает постоянный allocation, чтобы не конфликтовать с другими приложениями.

### Проверка `data len`

Получатель обязан проверить:

```text
data_len <= available_plaintext
```

AES padding может добавить trailing zeros. Чтение «до конца decrypted buffer» без `data len` приведёт к ложным данным.

## `PAYLOAD_TYPE_ANON_REQ`

Wrapper отличается:

| Поле | Размер |
|---|---:|
| destination hash | 1 байт |
| sender public key | 32 байта |
| cipher MAC | 2 байта |
| ciphertext | остаток |

Типовые plaintext:

### Room Server login

```text
timestamp: 4
sync timestamp: 4
password: remaining
```

`sync timestamp` говорит, с какого времени клиент хочет получить сообщения.

### Repeater/Sensor login

```text
timestamp: 4
password: remaining
```

### Repeater metadata requests

Опубликованы subtypes для regions, owner info, clock/status. Они содержат timestamp, request subtype, длину reply path и сам reply path.

Anonymous означает «отправитель ещё не найден в contact context», а не отсутствие public key. Полный ключ передаётся открыто внутри wrapper metadata.

## `PAYLOAD_TYPE_RAW_CUSTOM`

Payload не имеет стандартного внутреннего формата. Приложение само определяет:

- адресацию;
- шифрование;
- integrity;
- version;
- fragmentation;
- ACK;
- replay protection.

Текущий `Mesh.cpp` обрабатывает raw custom как direct и не flood-forward по умолчанию. Custom firmware может менять поведение, но тогда должна учитывать совместимость сети.

## Размеры и padding

AES работает блоками по 16 байт. Даже короткий plaintext создаёт минимум один cipher block плюс 2-byte MAC и wrapper. При планировании текста нужно считать bytes, не characters.

Пример личного plaintext 17 байт:

- padding до 32 bytes ciphertext;
- MAC 2 bytes;
- source/dest 2 bytes;
- всего MeshCore payload 36 bytes;
- дополнительно packet header, path и возможные transport codes.

## Выбор типа

| Задача | Payload |
|---|---|
| сообщение известному контакту | `TXT_MSG` |
| команда/получение структурированных данных | `REQ/RESPONSE` |
| сообщение всем участникам shared channel | `GRP_TXT` |
| binary telemetry shared channel | `GRP_DATA` |
| первый login неизвестного peer | `ANON_REQ` |
| полностью собственный protocol | `RAW_CUSTOM` |

Не следует кодировать binary в текст Base64 без необходимости: это увеличивает payload примерно на треть и airtime.

## Связанные статьи

- [Адресация и шифрование](/wiki/addressing-identity-and-encryption)
- [Служебные payload](/wiki/service-payloads)
- [ACK и повторы](/wiki/acknowledgements-retries-and-multipart)

## Источники

- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/payloads.md>
- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/number_allocations.md>
- <https://github.com/meshcore-dev/MeshCore/blob/main/src/Mesh.cpp>

# Адресация, identity и шифрование

MeshCore использует публичные ключи как устойчивую identity узла. Для экономии airtime в каждом адресном пакете передаётся не полный ключ, а короткий hash/prefix. Полный ключ хранится в контакте и используется для вычисления общего секрета и проверки advert signature.

## Размеры текущей реализации

| Объект | Размер |
|---|---:|
| Public key | 32 байта |
| Internal private key representation | 64 байта |
| Seed при генерации | 32 байта |
| Ed25519 signature | 64 байта |
| Shared secret | 32 байта |
| AES key | первые 16 байт shared secret |
| Cipher block | 16 байт |
| Packet v1 cipher MAC | 2 байта |
| Legacy source/destination hash | 1 байт |

Формат импорта/экспорта ключа в конкретном companion/CLI может отличаться от внутреннего `LocalIdentity`. Private key нельзя преобразовывать вручную без проверки официальной функции данной прошивки.

## Identity

При создании `LocalIdentity` прошивка получает случайный 32-byte seed и формирует Ed25519 keypair. Public key можно распространять через advert и QR/contact export. Private key должен оставаться на доверенном устройстве.

Identity определяет:

- контакт;
- sender/receiver shared secret;
- подпись advert;
- ACL для удалённого управления;
- короткие node/path hash;
- continuity после обновления устройства.

Имя узла не является identity. Два устройства могут иметь одинаковое имя, но разные ключи. Клонирование private key создаёт две физические копии одной identity и ломает ожидания маршрутизации и безопасности.

## Advert signature

Advert содержит:

```text
public key | timestamp | signature | appdata
```

Подписывается последовательность:

```text
public key + timestamp + appdata
```

Получатель проверяет Ed25519 signature полным public key из advert. Это позволяет принимать объявление неизвестного узла без заранее общего секрета и отклонять подделку appdata.

Signature не скрывает имя, координаты и тип узла: advert публичен.

## Shared secret

Для известных peer используется `ed25519_key_exchange` между private key локального узла и public key удалённого. Обе стороны получают одинаковые 32 байта shared secret.

Anonymous request также передаёт полный public key отправителя, чтобы адресат мог вычислить shared secret до создания контакта.

Криптографический shared secret не означает автоматически социальное доверие. Неизвестный отправитель всё ещё должен пройти login/password/ACL прикладного сервиса.

## Адресный wrapper

REQ, RESPONSE, TXT_MSG и PATH имеют общую внешнюю структуру:

```text
destination_hash: 1 byte
source_hash:      1 byte
cipher_mac:       2 bytes
ciphertext:       remaining bytes
```

Получатель сначала сравнивает destination hash с коротким hash собственной identity. Затем ищет контакты с совпавшим source hash. В текущей `BaseChatMesh` может быть несколько кандидатов; для каждого вычисляется secret и выполняется MAC/decrypt.

Успешная проверка MAC определяет правильный контакт. Это необходимо, потому что один байт даёт только 256 значений и коллизии неизбежны в большой сети.

## Path hash и address hash

Оба происходят от public key, но используются в разных местах:

- destination/source hash выбирает кандидатов для payload;
- path hash выбирает следующий repeater;
- размер path hash может быть 1–3 байта;
- payload version v1 всё ещё документирует 1-byte source/destination hash.

Увеличение `path.hash.mode` не увеличивает автоматически address hash или cipher MAC.

## Текущее шифрование

В `Utils.cpp` реализация:

1. берёт 16 байт shared secret как AES-128 key;
2. шифрует данные блоками по 16 байт;
3. последний неполный блок дополняет нулями;
4. вычисляет HMAC-SHA256 по ciphertext с 32-byte shared secret;
5. сохраняет первые 2 байта HMAC перед ciphertext;
6. при приёме сначала проверяет MAC, затем расшифровывает.

Схема называется в коде `encryptThenMAC`/`MACThenDecrypt`.

Важно: текущая реализация AES шифрует каждый блок напрямую и не передаёт IV/nonce в wrapper. Не следует приписывать ей режим GCM, CBC или ChaCha20. При разработке interoperable клиента нужно воспроизводить опубликованный код, а не выбирать современную схему по предположению.

## Padding

Plaintext дополняется нулями до 16-byte boundary. Функция decrypt возвращает размер, кратный 16. Конкретный payload должен понимать собственную фактическую длину:

- текст может завершаться нулём или определяться frame length клиентского протокола;
- PATH вычисляет длину вложенных полей;
- RESPONSE зависит от application schema.

Нельзя считать все trailing zeros частью сообщения.

## Короткий MAC

Packet v1 хранит только 2 байта HMAC. Это уменьшает overhead, но даёт 65 536 возможных значений. Для случайной ошибки этого достаточно как быстрый фильтр, однако криптографическая стойкость к активному перебору ограничена 16 битами на попытку.

Практические последствия:

- нельзя использовать факт «MAC совпал» как долгосрочную цифровую подпись;
- rate limiting и ограничение flood важны против injection;
- future payload versions могут увеличить MAC;
- приложение с более высокими требованиями может использовать `RAW_CUSTOM` и собственную AEAD-схему, но должно решить маршрутизацию и совместимость.

## Group channel

Group payload не имеет индивидуальных source/destination hash. Wrapper:

```text
channel_hash: 1 byte
cipher_mac:   2 bytes
ciphertext:   remaining
```

Все участники канала знают один secret. Любой из них может создать корректный group packet. Поэтому имя отправителя внутри группового текста **не аутентифицировано как индивидуальная identity**. Shared channel обеспечивает конфиденциальность от посторонних и целостность относительно незнающих ключ, но не доказывает, кто из членов отправил сообщение.

Signed text может добавить отдельное подтверждение identity, если формат и клиент это поддерживают.

## Anonymous request

Wrapper:

```text
destination_hash: 1 byte
sender_public_key: 32 bytes
cipher_mac: 2 bytes
ciphertext
```

Полный ключ увеличивает airtime, но позволяет адресату вычислить secret для неизвестного peer. Он применяется для login Room Server/Repeater/Sensor и discovery-подобных запросов верхнего уровня.

## Метаданные, остающиеся видимыми

Даже зашифрованный пакет раскрывает:

- время передачи;
- частоту и PHY-параметры;
- длину;
- route type;
- payload type;
- transport codes;
- path hash и hop count;
- короткие source/destination hash для ряда payload;
- повторяемость packet hash/паттернов.

Наблюдатель может строить traffic analysis без расшифровки текста.

## Управление private key

- не публиковать `get prv.key` output;
- не хранить экспорт в общедоступном облаке;
- создавать зашифрованную резервную копию;
- не использовать одну identity на двух активных radio;
- при компрометации создать новую identity и обновить контакты/ACL;
- перед factory reset проверить наличие backup;
- private key repeater защищать так же, как административный пароль.

## Что подтверждает каждый механизм

| Механизм | Подтверждает | Не подтверждает |
|---|---|---|
| LoRa CRC | отсутствие обнаруженной случайной ошибки PHY | отправителя |
| Cipher MAC | знание shared secret и целостность ciphertext | конкретного участника group channel |
| Advert signature | владение private key advertised identity | достоверность имени/координат в реальном мире |
| ACK checksum | связь ACK с сообщением | личность без контекста защищённого обмена |
| Password/ACL | прикладное разрешение | качество радиомаршрута |

## Связанные статьи

- [Формат пакета](/wiki/packet-format)
- [Пользовательские payload](/wiki/user-payloads)
- [Угрозы радиоуровня](/wiki/security-threats)

## Источники

- <https://github.com/meshcore-dev/MeshCore/blob/main/src/Identity.cpp>
- <https://github.com/meshcore-dev/MeshCore/blob/main/src/Utils.cpp>
- <https://github.com/meshcore-dev/MeshCore/blob/main/src/MeshCore.h>
- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/payloads.md>

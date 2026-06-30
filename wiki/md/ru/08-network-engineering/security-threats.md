# Угрозы радиоуровня MeshCore

Безопасность MeshCore состоит из нескольких механизмов: Ed25519 identity/signatures, shared secrets, AES-128 encryption, truncated HMAC, passwords/ACL и routing policy. Они защищают разные свойства. Радиоканал остаётся доступным для наблюдения, блокировки и передачи произвольных сигналов.

## Модель угроз

Рассматриваются противники:

1. пассивный слушатель с LoRa/SDR;
2. участник public/group channel;
3. владелец malicious repeater;
4. атакующий с физическим доступом к node;
5. transmitter, создающий interference/jamming;
6. compromised bridge/client;
7. случайно неисправная custom firmware.

## Что защищено

### Advert signature

Позволяет проверить, что advert appdata подписана private key advertised identity. Защищает от изменения имени/координат в пути и простой подделки чужого public key.

Не подтверждает реальную личность человека и не скрывает данные.

### Peer encryption

Shared secret между identities используется для AES-128 encryption и HMAC ciphertext. Защищает текст от узла, не знающего secret.

### Group secret

Защищает channel от посторонних, но каждый участник может создать packet от любого отображаемого имени. Индивидуальная non-repudiation отсутствует без дополнительной подписи.

### ACL/password

Ограничивает remote administration/application login. Не защищает radio availability.

## Пассивное наблюдение

Наблюдатель может собрать:

- частоту, BW, SF, CR;
- время и длительность TX;
- route/payload type;
- path hash/count;
- transport codes;
- source/destination short hashes;
- public adverts и location;
- размер ciphertext;
- pattern ACK и responses.

Даже без текста можно определить active nodes, backbone, рабочие часы и социальные связи.

### Снижение metadata leakage

Полностью скрыть её в текущем protocol нельзя. Можно:

- не публиковать coordinates;
- использовать нейтральные names;
- ограничивать scope;
- не отправлять лишние adverts;
- не выполнять постоянный trace;
- избегать predictable high-value traffic pattern;
- хранить logs закрыто.

Traffic padding увеличивает airtime и не входит в standard policy.

## Replay

Если attacker записывает packet и повторяет его, seen table может подавить copy, пока hash хранится. После reboot/expiry повтор может снова обрабатываться.

Timestamp снижает replay window, но требует корректных часов и application validation. Для критических commands нужны:

- operation ID;
- monotonic counter/nonce;
- freshness window;
- idempotent execution;
- storage последних IDs.

Generic text protocol не является transaction system.

## Packet injection

Packet v1 cipher MAC имеет 2 байта — 16-bit truncated HMAC. Случайная подделка имеет шанс около 1/65536 на попытку для конкретного secret context. Flood позволяет много попыток, поэтому rate limit и scope важны.

Это не означает, что attacker сразу расшифрует данные. Но high-rate forgery создаёт DoS и теоретический шанс accepted MAC.

Для high-security custom application следует рассмотреть `RAW_CUSTOM` с modern AEAD, большим tag и replay counter. Однако interoperability и routing остаются ответственностью приложения.

## Key compromise

### Private key узла

Атакующий может:

- подписывать adverts;
- вычислять peer shared secrets от имени узла;
- проходить ACL, привязанный к key;
- расшифровывать сохранённый/перехваченный traffic в пределах схемы.

Восстановление:

1. создать новую identity;
2. удалить старый contact/ACL;
3. распространить новый public key out-of-band;
4. сменить group secrets;
5. обновить server permissions;
6. считать старую identity отозванной.

MeshCore radio protocol не публикует глобальный certificate revocation list.

### Channel secret

Любой участник может читать future traffic и создавать valid group packets. Нужно создать новый channel secret и безопасно передать участникам.

## Malicious repeater

Repeater видит metadata и управляет forwarding. Он может:

- selective drop;
- delay;
- replay;
- route attraction через adverts;
- изменить unprotected routing fields;
- создавать duplicate branch;
- логировать topology;
- нарушать duty cycle.

End-to-end encryption скрывает payload, но не гарантирует delivery. Mesh routing не требует доверять repeater конфиденциальностью, но требует доверять availability.

### Route attraction

Высокий/быстрый malicious repeater может первым переслать flood, стать частью returned path, затем drop direct packets. First packet wins упрощает такую атаку.

Меры:

- compare alternative paths;
- manual path policy для critical links;
- monitor ACK/PDR per hop;
- blacklist/remove suspect node на application level;
- redundant routes.

## Hash collision attack

Атакующий может генерировать keypairs до совпадения короткого path prefix. Для 1-byte это дешёво. Он может стать ложным next hop.

2/3-byte path hash увеличивает cost, но не делает routing cryptographically authenticated. Critical network должна обновлять hash size и контролировать known backbone identities.

## Forged advert

Без private key attacker не может изменить signed advert. Но он может:

- replay старый valid advert;
- создать новую identity с похожим именем;
- скопировать display name;
- публиковать ложные coordinates под своей identity.

UI должен показывать key fingerprint, а не доверять только имени.

## Jamming и DoS

Любой достаточно мощный transmitter может блокировать нелицензируемый channel. Encryption не помогает.

Виды:

- continuous noise;
- LoRa packet flood;
- reactive jammer;
- valid MeshCore flood storm;
- malformed packets, заполняющие parser/queue;
- advert/contact table exhaustion.

Защита ограничена:

- frequency agility/manual migration;
- directional antennas;
- filtering;
- regions/flood limits;
- rate limiting;
- packet validation до expensive crypto;
- watchdog/recovery;
- резервный out-of-band channel.

Нельзя отвечать повышением мощности без проверки закона и escalation.

## Malformed packets

Parser проверяет version, path mode и lengths. Payload handler должен дополнительно проверять все offsets до чтения.

Custom clients должны:

- проверять minimum length;
- защищаться от integer overflow;
- считать signed fields правильно;
- ограничивать allocation;
- не доверять `data_len`;
- fuzz-test parser;
- отвергать reserved values.

## Bridge loops

Bridge между radio channels/IP может превратить один packet в новый, обойти seen table и создать storm.

Требования:

- globally stable message ID;
- ingress interface tag;
- no-return rule;
- TTL;
- rate limit;
- dedup storage;
- explicit payload allowlist;
- monitoring.

## Physical access

Устройство может раскрывать:

- private key;
- channel secrets;
- contacts;
- messages;
- admin password;
- logs.

Меры:

- locked enclosure;
- disable unauthenticated debug;
- encrypted backup;
- secure boot/flash encryption, если platform поддерживает;
- erase перед передачей устройства;
- tamper evidence;
- ограниченный serial access.

Не все MeshCore boards имеют hardware security, поэтому physical compromise часто означает key compromise.

## Remote administration

Default admin password `password` необходимо менять. Password может добавлять node в admin ACL согласно текущей реализации. Риски:

- brute force по radio;
- password reuse;
- interception metadata;
- случайная публикация CLI response, которая echoes новый password по документации.

Используйте длинный уникальный password, ограничивайте administrative paths и проверяйте ACL.

## Availability важнее secrecy для routing

В disaster network шифрование текста не гарантирует работоспособность. Нужны:

- несколько backbone paths;
- резервное питание;
- known-good firmware;
- flood storm controls;
- monitoring;
- manual fallback frequency/profile;
- documented recovery.

## Security checklist

- [ ] сменён default admin password;
- [ ] private keys backed up и защищены;
- [ ] group secrets уникальны;
- [ ] coordinates публикуются осознанно;
- [ ] firmware source/version известны;
- [ ] loop detection/flood limits настроены;
- [ ] multibyte path hash используется при масштабе;
- [ ] remote commands idempotent;
- [ ] logs имеют срок хранения;
- [ ] bridge защищён от loops;
- [ ] есть план key rotation;
- [ ] есть out-of-band recovery.

## Связанные статьи

- [Адресация и шифрование](/wiki/addressing-identity-and-encryption)
- [Path hash и петли](/wiki/path-hashes-duplicates-and-loops)
- [Совместимость](/wiki/compatibility-and-migration)

## Источники

- <https://github.com/meshcore-dev/MeshCore/blob/main/src/Identity.cpp>
- <https://github.com/meshcore-dev/MeshCore/blob/main/src/Utils.cpp>
- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/payloads.md>
- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/cli_commands.md>

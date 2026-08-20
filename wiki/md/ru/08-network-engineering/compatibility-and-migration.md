# Совместимость и миграция сети

MeshCore развивается на нескольких платформах. Совместимость имеет четыре независимых измерения:

1. radio PHY;
2. packet format;
3. payload/application format;
4. локальные настройки и сохранённое состояние.

Совпадение firmware version не гарантирует одинаковую сборку, а одинаковый radio profile не гарантирует protocol compatibility.

## Уровни совместимости

### PHY

Должны совпасть:

- frequency;
- bandwidth;
- spreading factor;
- coding rate;
- sync word;
- header/CRC mode;
- совместимый frequency range hardware.

При несовпадении packet не достигает MeshCore parser.

### Packet format

Header version, route type, path encoding, transport codes и limits должны пониматься forwarding nodes.

Current parser принимает payload version 1 и drop future versions.

### Payload format

Даже если repeater forward unknown encrypted bytes, destination должен знать schema. Group data type выделяет application namespace, но внутренний format задаёт приложение.

### Companion/client protocol

BLE/USB frame version, commands, response codes и storage limits относятся к app ↔ companion, а не radio wire. Старый app может не уметь новую radio feature, хотя companion её поддерживает.

## Версия firmware и commit

Строка `ver` должна сохраняться в inventory. Release tag недостаточен для custom build; полезен commit hash и build flags.

Для каждого node:

```text
identity
role
board
firmware version/commit
radio profile
path hash mode
routing settings
region tree
storage migration state
```

## Multibyte path migration

Публичная документация предупреждает:

- legacy firmware поддерживает только 1-byte path;
- firmware v1.13 и старше может drop multibyte;
- firmware ≥1.14 должна forward 1–3-byte paths;
- `path.hash.mode` влияет на создаваемые adverts, а не на forwarding support новой firmware.

Порядок:

1. обновить backbone repeaters;
2. проверить forwarding test packets каждого size;
3. обновить companions/rooms/sensors;
4. оставить source mode 1 byte на переходный период;
5. включить 2-byte на pilot nodes;
6. очистить/обновить stale paths;
7. мониторить duplicates и drops;
8. затем менять default fleet.

Нельзя начинать с удалённого edge client, если единственный путь проходит через old repeater.

## Packet version migration

Bits version имеют только четыре значения, а current parser drop > v1. Будущая миграция потребует:

- обновления all forwarding nodes либо compatibility envelope;
- отдельного feature detection;
- запрета преждевременного использования reserved version;
- rollback plan.

Repeater не является transparent byte forwarder: он парсит version/path и может drop unknown format.

## Radio profile migration

Изменение frequency/BW/SF/CR разрывает radio control. Безопасные варианты:

### Физический доступ

Самый надёжный: обновить site по очереди через serial.

### Временный профиль

`tempradio` позволяет перейти на другой набор на ограниченное время. Нужно учитывать, что node не слышит основной channel в этот период.

### Два радио

Bridge с двумя независимыми transceivers может временно соединить profiles на application level. Raw bridge требует loop protection.

### Rolling cutover

1. подготовить configs;
2. перевести резервный backbone;
3. проверить новый segment;
4. перевести edges;
5. перевести основной backbone;
6. сохранить fallback node на старом profile до окончания.

## Runtime preferences и erase

Build flags задают defaults, но сохранённые preferences могут пережить update. Поэтому после flashing:

- `get radio`;
- `get tx`;
- `get path.hash.mode`;
- `get loop.detect`;
- regions;
- identity;
- role.

Full erase применяет defaults, но уничтожает keys/config/logs. Backup private key и settings обязателен.

## Identity continuity

Сохранение private key сохраняет contact identity. Но клонировать один key на два active nodes нельзя.

При переносе hardware:

1. выключить старое устройство;
2. экспортировать key безопасно;
3. импортировать в новое;
4. проверить derived public key;
5. проверить advert signature;
6. только затем включить новое;
7. erase старое storage.

Если два copies одновременно send adverts, paths и ACK становятся непредсказуемыми.

## Role migration

Переход Companion → Repeater или Repeater → Room Server меняет application behavior. Если key сохраняется, contacts увидят прежнюю identity с новым type flag.

Проверить:

- ACL/password;
- storage schema;
- advert appdata;
- forwarding default;
- periodic intervals;
- power mode;
- client assumptions.

## Mixed hardware

Разные chips могут поддерживать один profile, но иметь:

- разную TX power calibration;
- RSSI offset;
- RX boosted gain;
- preamble/LDRO quirks;
- TCXO accuracy;
- CAD behavior;
- max BW/SF combinations.

Compatibility test должен включать matrix каждой пары transmitter/receiver, а не только две одинаковые платы.

## Protocol feature matrix

Создайте таблицу:

| Feature | Min firmware | Repeater | Companion | Room | Sensor | Notes |
|---|---|---|---|---|---|---|
| multibyte forward | ≥1.14 | test | — | test | test | legacy drops |
| `dutycycle` | ≥1.15 | yes | build-dependent | yes | yes | `af` deprecated |
| loop detection | ≥1.14 | yes | n/a | build | build | default off |
| RX boosted gain | ≥1.14.1 | hardware | hardware | hardware | hardware | upgrade state |
| regions | ≥1.10 | yes | client support | yes | build | transport route |

Версии примерные по текущей документации; release notes конкретной build имеют приоритет.

## Test network

Перед fleet rollout:

- минимум по одному экземпляру каждой board/role;
- mixed old/new repeaters;
- 1/2/3-byte paths;
- scoped/unscoped flood;
- direct ACK;
- maximum packet;
- group data;
- remote CLI;
- reboot/power loss;
- rollback.

Test должен моделировать реальные hop, а не только zero-hop на столе.

## Canary rollout

1. один noncritical repeater;
2. наблюдение 24–72 часа;
3. небольшой region;
4. backbone subset с alternative path;
5. остальная fleet.

Критерии stop:

- рост duplicates;
- unexplained resets;
- drop legacy packets;
- queue saturation;
- broken remote admin;
- identity/storage loss.

## Rollback

Rollback plan включает:

- предыдущие binaries;
- serial/DFU access;
- backup preferences/keys;
- old radio profile;
- list of nodes and order;
- fallback communication channel;
- запрет automatic mass update без health check.

Downgrade может не понимать новую storage schema. Иногда требуется export → erase → flash → import, а не простая замена binary.

## Reserved values

Не использовать:

- payload version 2–4;
- path mode 3;
- payload types `0x0C–0x0E`;
- internal group data ranges;
- undocumented CLI commands из fork.

Reserved сегодня может получить официальное значение завтра. Custom use создаёт конфликт при upgrade.

## Third-party firmware

Fork может:

- изменить packet hash;
- изменить delay;
- повторять unknown payload;
- отключить limits;
- использовать другой crypto;
- создавать storm.

До подключения к public mesh проверить diff, radio profile, packet format и forwarding behavior. «Основано на MeshCore» не равно interoperable.

## Проверка после обновления

- version/board/role;
- public key unchanged;
- radio settings;
- TX power;
- zero-hop advert;
- flood advert propagation;
- direct text + ACK;
- group text/data;
- regions;
- path hash size;
- stats/error flags;
- reboot persistence;
- remote recovery.

## Связанные статьи

- [Радиопрофиль и оборудование](/wiki/radio-profile-and-hardware)
- [Path hash и петли](/wiki/path-hashes-duplicates-and-loops)
- [Угрозы](/wiki/security-threats)
- [Статистика](/wiki/statistics-and-logging)

## Источники

- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/faq.md>
- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/cli_commands.md>
- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/packet_format.md>
- <https://github.com/meshcore-dev/MeshCore/releases>

# Regions и transport codes

Regions ограничивают область распространения transport flood/direct packets. Они решают задачу масштабирования и административного зонирования: локальный traffic не обязан проходить через всю физически связанную mesh.

![Regions](/attachments/ru/regions.svg?v=2)

## Что region делает

Region policy отвечает на вопрос:

> Разрешено ли этому узлу forward packet с данным transport code?

Она не:

- шифрует payload;
- скрывает название области;
- вычисляет лучший route;
- гарантирует доставку внутри области;
- заменяет `flood.max`;
- меняет LoRa frequency.

Regions работают поверх общего radio profile. Запрещённый packet сначала физически принимается и занимает airtime, но не распространяется дальше.

## Transport route

Route types:

- `ROUTE_TYPE_TRANSPORT_FLOOD`;
- `ROUTE_TYPE_TRANSPORT_DIRECT`.

После header идут:

```text
transport_code_1: 2 bytes
transport_code_2: 2 bytes
```

Первый код вычисляется из scope/region. Второй зарезервирован. Код является компактным идентификатором, а не полным именем и не MAC.

## Иерархия

Regions образуют дерево с wildcard root `*`. Пример:

```text
*
└── Europe
    └── Germany
        ├── Berlin
        └── Hamburg
```

Иерархия позволяет описать вложенные области. Конкретная forwarding policy зависит от списка region и flood flag на узле.

Maximum depth в CLI bulk-load — 8 уровней.

## Home region

```text
region home
region home <name>
```

Home region описывает принадлежность узла. Она может использоваться для выбора scope и представления topology. Наличие home region не означает автоматического запрета всех остальных packets.

## Default scope

```text
region default
region default <name>
region default <null>
```

Default region применяется к исходящему flood, если приложение не выбрало scope явно. Сброс возвращает unscoped behavior.

Неправильный default может сделать сообщения невидимыми части сети, где transport code запрещён.

## Wildcard и unscoped

Region `*` используется как root и policy для packets без scope.

```text
region allowf *
region denyf *
```

- `allowf *` разрешает unscoped flood;
- `denyf *` отбрасывает его.

Более мягкая альтернатива:

```text
set flood.max.unscoped 3
```

Тогда legacy/unscoped traffic остаётся локальным на несколько hop.

## Управление списком

### Bulk load

```text
region load
region load <name> [F]
```

Interactive input с отступами создаёт parent-child. `F` разрешает flood.

После изменений:

```text
region save
```

Без save изменения могут исчезнуть после reboot.

### Создание

```text
region put <name> [parent]
```

Создаёт region; default parent — wildcard.

### Однострочная иерархия

```text
region def <token> [<token> ...]
```

Cursor начинает с `*`. Token `name` создаёт child и перемещает cursor. Формы `name|jump` или `name,jump` создают node и возвращают cursor к уже существующему region.

Операция может быть частичной: nodes до ошибки остаются в памяти. Перед `region save` нужно вывести дерево и проверить результат.

### Политика flood

```text
region allowf <name>
region denyf <name>
region get <name>
```

`get` показывает сведения и помогает проверить code/flags.

## Пример проектирования

Есть общая сеть страны и плотные городские сегменты:

```text
Country
├── City-A
│   ├── North
│   └── South
└── City-B
```

Рекомендуемая логика:

- локальные group messages получают scope City-A;
- emergency message может получить scope Country;
- repeaters на границе разрешают Country и свой city;
- внутренние edge repeaters deny соседний city;
- unscoped ограничивается малым hop count;
- advert scope выбирается отдельно от пользовательского traffic.

Так traffic City-A не заполняет очереди City-B, хотя несколько высоких repeaters физически слышат обе области.

## Collision transport codes

16-bit code имеет конечное пространство. Если code является hash имени/scope, теоретически возможна коллизия. Поэтому regions — механизм маршрутизационной политики, а не security boundary.

Злоумышленник, знающий code, может создать packet с тем же значением. Payload security должна обеспечиваться peer/channel keys и signatures.

## Transport Direct

Direct path и так ограничивает пересылку конкретными hop. Transport code добавляет policy boundary: repeater может отказаться пересылать direct packet, даже если его hash стоит следующим.

Это полезно для административного разделения, но создаёт failure mode:

- path был построен до изменения region policy;
- один hop теперь deny scope;
- direct packet останавливается;
- новый flood в том же scope тоже не найдёт путь через этот узел.

После изменения regions нужно пересоздать paths и выполнить end-to-end tests.

## Regions и частоты

Region scope не заменяет frequency planning. Две области с одинаковым radio profile продолжают мешать друг другу даже при deny. Если плотность очень высока, можно использовать разные разрешённые каналы/частоты, но тогда для связи потребуется multi-radio bridge и защита от loops.

## Миграция legacy сети

1. обновить repeaters с transport support;
2. создать region tree без deny;
3. назначить home regions;
4. включить default scope на тестовых sources;
5. проверить transport flood/direct;
6. ограничить unscoped hop count;
7. только затем применять `denyf`;
8. сохранить config и резервные копии.

Ранний `denyf *` может отрезать старые clients и remote administration.

## Диагностика

Если scoped packet не проходит:

- сравнить route type: transport или обычный;
- вывести region tree на каждом border repeater;
- проверить `allowf/denyf`;
- проверить default/home;
- сравнить transport code packet с region code;
- проверить `flood.max` и path size;
- сбросить старый direct path;
- временно разрешить scope и повторить;
- проверить mixed firmware.

## Безопасная эксплуатация

- имена regions не считать секретом;
- документировать code и hierarchy;
- избегать частых remote bulk changes;
- проверять partial `region def` errors;
- сохранять только после review;
- иметь serial recovery для border repeater;
- не использовать transport code как ACL.

## Связанные статьи

- [Flood routing](/wiki/flood-routing)
- [Direct routing](/wiki/direct-routing-and-path-discovery)
- [Ёмкость и масштабирование](/wiki/capacity-and-scaling)
- [Совместимость](/wiki/compatibility-and-migration)

## Источники

- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/cli_commands.md>
- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/packet_format.md>

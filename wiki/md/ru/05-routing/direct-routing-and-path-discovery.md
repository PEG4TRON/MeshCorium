# Direct routing и поиск пути

Direct routing пересылает packet по заранее указанной последовательности path hash. Термин `direct` означает **направленную маршрутизацию**, а не один radio hop. Путь из десяти repeaters остаётся direct.

![Flood и Direct](/attachments/ru/flood-vs-direct.svg?v=2)

## Route types

- `ROUTE_TYPE_DIRECT`;
- `ROUTE_TYPE_TRANSPORT_DIRECT`.

Transport Direct дополнительно несёт region transport codes. Path semantics остаётся source-routed: packet содержит список следующих переходов.

## Как repeater пересылает direct packet

В текущем `Mesh::onRecvPacket`:

1. проверяется, что path hash count больше нуля;
2. для ACK может выполняться ранняя локальная обработка;
3. первый path entry сравнивается с identity узла;
4. проверяется `allowPacketForward`;
5. seen table исключает повтор;
6. собственная запись удаляется из path;
7. packet ставится в очередь с высоким приоритетом и `direct.txdelay`.

Узел, не являющийся следующим hop, освобождает packet. Поэтому в отличие от flood множество соседей не ретранслирует одну копию.

## Последний hop

Когда path становится пустым, packet рассматривается как достигший области назначения. Для адресных payload узел сравнивает destination hash и пытается расшифровать данные известными peer secrets.

Короткий destination hash может совпасть у нескольких identities. Только успешный MAC/decrypt определяет адресата.

## Получение пути через flood

Типичный path discovery:

1. sender не имеет сохранённого path;
2. отправляет address packet как flood;
3. repeaters добавляют свои hash;
4. destination получает победившую копию;
5. создаёт `PAYLOAD_TYPE_PATH` с накопленным маршрутом;
6. возвращает PATH автору;
7. sender сохраняет `out_path` контакта;
8. последующие packets отправляются direct.

Returned path может включать extra ACK или RESPONSE, чтобы подтвердить первый пакет без отдельной передачи.

## Reciprocal path

Предполагается, что цепочка узлов применима обратно. Но радиолиния может быть асимметричной. Причины:

- разные TX power;
- разные антенны;
- локальные помехи только у одного узла;
- hidden-node collisions;
- очередь и duty budget;
- мобильность;
- direction-dependent antenna pattern.

Поэтому path может быть найден flood в одну сторону, но ACK обратно не пройти. Наличие advert от узла также не гарантирует двустороннюю direct связь.

## First path, shortest path и best path

Текущий алгоритм не вычисляет глобальную метрику. Побеждает первая успешно обработанная flood-копия. Она может быть:

- самой быстрой в текущий момент;
- с наименьшим числом hop;
- с наилучшим SNR;
- или просто с удачной случайной задержкой.

Это **first path**, а не гарантированный shortest/best path. `rxdelay` пытается дать приоритет более сильным копиям, но не превращает сеть в link-state routing.

## Хранение path

Companion contact обычно содержит:

- `out_path_len`;
- до `MAX_PATH_SIZE` bytes path;
- timestamp последнего advert;
- identity и type.

Path должен рассматриваться как cache. Он не подтверждает текущую доступность каждого repeater.

Полезные политики клиента:

- сбрасывать path после нескольких failed attempts;
- обновлять path при новом advert/path response;
- показывать hop count и время последнего обновления;
- не считать старый path «онлайн-статусом»;
- разрешать manual reset.

## `CMD_RESET_PATH`

Companion protocol содержит команду reset path. Она удаляет сохранённый маршрут к контакту, заставляя следующую передачу использовать discovery/flood.

Сброс нужен, если:

- один hop выключен;
- мобильный repeater уехал;
- сеть изменила path hash mode;
- direct ACK систематически не приходит;
- более новый advert показывает другой path;
- контакт был импортирован со старым маршрутом.

## Stale path

Типичный симптом:

- контакт виден в списке;
- отправка direct не подтверждается;
- другие узлы работают;
- после reset/flood сообщение доставляется.

Это не проблема ключа. Пакет не достигает destination, поэтому decrypt даже не выполняется.

## Direct retransmit delay

CLI:

```text
get direct.txdelay
set direct.txdelay <0..2>
```

Default `0.2`, меньше flood default `0.5`. Обоснование: только конкретный next hop должен пересылать direct packet, поэтому конкурентов меньше.

Нулевая задержка минимизирует latency, но может столкнуть direct response с ещё продолжающимся flood или локальным TX соседнего узла. Небольшой jitter полезен.

## Приоритет

В `Mesh.cpp` обычный direct forwarding ставится с приоритетом `0`, который комментируется как highest priority. Flood получает приоритет, зависящий от path count. Это помогает:

- не задерживать ACK за дальним flood;
- быстрее освобождать direct route;
- снизить вероятность application timeout;
- уменьшить рост очереди.

Но duty-cycle budget всё равно может отложить TX. Приоритет не отменяет юридический или программный лимит.

## Direct ACK

ACK идёт обратно по path, содержащемуся в packet/context. Промежуточный узел может обработать ACK локально для статистики, удалить себя из path и переслать дальше.

Если ACK потерян, sender не знает, потеряно ли сообщение или только подтверждение. Без idempotency повтор может создать duplicate пользовательского действия.

## Multipart ACK

Multi-ACK представлен `PAYLOAD_TYPE_MULTIPART`. Промежуточный узел может сформировать дополнительные ACK copies с задержкой. Это увеличивает вероятность подтверждения на плохой линии, но умножает airtime. Использовать следует только после измерения.

## Direct path и mobile repeater

Мобильный repeater создаёт быстрый путь, пока находится между сегментами. После его ухода:

- packet доходит до предыдущего hop;
- следующий hash больше не слышен;
- direct forwarding прекращается;
- sender ждёт timeout;
- path остаётся сохранённым до policy reset.

Нужен fallback: после ограниченного числа неудач сбросить path и выполнить flood discovery. Слишком быстрый fallback создаёт flood при единичной потере.

## Изменение path hash size

Direct packet несёт encoded hash size. Все repeaters firmware ≥1.14 должны пересылать 1–3-byte entries. Старые версии могут drop multibyte packet.

При миграции:

- backbone обновляется первым;
- source начинает создавать multibyte path после проверки;
- старые cached 1-byte paths остаются валидными, пока сеть их forwarding поддерживает;
- imported contact path должен сохранять encoded `path_len`, а не только raw bytes.

## Route repair

MeshCore не выполняет полноценный local repair на каждом broken hop. Основной ремонт — новый flood discovery от sender.

Возможная прикладная стратегия:

```text
1-я ошибка: повтор direct
2-я ошибка: повтор direct с увеличенным timeout
3-я ошибка: reset path
4-я попытка: flood discovery
```

Порог зависит от airtime и критичности. В emergency network агрессивный flood может быть оправдан, в sensor network — нет.

## Диагностика direct route

1. проверить возраст path;
2. вывести hop count/path details;
3. выполнить trace;
4. проверить, видны ли соседние repeaters zero-hop;
5. сравнить `n_recv_direct` и `n_sent_direct` на hop;
6. проверить duplicate counters;
7. проверить TX queue/duty budget;
8. reset path и повторить;
9. сравнить новый путь со старым.

## Связанные статьи

- [Flood routing](/wiki/flood-routing)
- [Trace](/wiki/trace-and-route-diagnostics)
- [ACK и повторы](/wiki/acknowledgements-retries-and-multipart)
- [Path hash, дубли и петли](/wiki/path-hashes-duplicates-and-loops)

## Источники

- <https://github.com/meshcore-dev/MeshCore/blob/main/src/Mesh.cpp>
- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/faq.md>
- <https://github.com/meshcore-dev/MeshCore/blob/main/examples/companion_radio/MyMesh.cpp>

# Flood routing

Flood routing доставляет пакет без заранее известного пути. Каждый подходящий repeater, впервые увидевший packet, может добавить свой идентификатор в path и поставить пакет на отложенную ретрансляцию. Механизм прост и устойчив к неизвестной топологии, но создаёт больше передач, чем direct routing.

![Flood и Direct](/attachments/ru/flood-vs-direct.svg?v=2)

## Route types

Flood представлен двумя значениями:

- `ROUTE_TYPE_FLOOD` — обычный flood;
- `ROUTE_TYPE_TRANSPORT_FLOOD` — flood с transport codes для region scope.

В обоих случаях path строится по мере распространения. Различие состоит в четырёх дополнительных байтах transport codes и фильтрации regions.

## Прохождение пакета

Упрощённый алгоритм repeater:

1. принять и разобрать LoRa payload;
2. проверить packet version и размеры;
3. применить transport/region filter;
4. проверить payload-specific validity;
5. проверить seen table;
6. при необходимости обработать пакет локально;
7. проверить `allowPacketForward` и flood limits;
8. убедиться, что новая path entry помещается;
9. добавить собственный path hash;
10. вычислить retransmit delay;
11. поставить packet в outbound queue.

В `Mesh::routeRecvPacket` приоритет ретрансляции связан с текущим числом path entries: пакеты от более близких источников имеют более высокий приоритет, а дальние уступают очередь.

## Почему используется случайная задержка

Если три repeater одновременно услышали один пакет и сразу начали TX, их копии столкнутся. Поэтому каждый выбирает задержку из случайного окна.

Пока repeater ждёт, он может услышать копию того же packet от другого узла. Seen table показывает, что packet уже распространяется, и отложенную лишнюю передачу можно подавить или она теряет смысл.

Параметр:

```text
get txdelay
set txdelay <0..2>
```

Default в CLI — `0.5`. Более высокое значение расширяет окно:

- меньше риск одновременного TX;
- выше end-to-end latency;
- больше шанс, что direct/ACK обгонит flood в очереди;
- слабый или загруженный узел может не успеть до timeout приложения.

`txdelay=0` убирает окно и подходит только для контролируемого теста с малым числом узлов.

## First packet wins

Когда один packet приходит несколькими путями, текущая реализация обрабатывает первую допустимую копию. Более поздние считаются duplicate.

Это даёт быстрый и простой выбор, но не гарантирует оптимальность:

- первый путь может иметь больше hop;
- сильный короткий путь может проиграть по случайной задержке;
- маршрут может пройти через мобильный repeater;
- высокая загрузка очереди искажает время прихода;
- лучший путь в одном направлении не обязательно лучший обратно.

Returned path отражает фактически победившую копию, а не результат глобального алгоритма shortest path.

## Накопление path

Перед forwarding repeater добавляет hash своей identity. Размер entry определяется encoded path mode пакета: 1, 2 или 3 байта.

Path выполняет несколько функций:

- показывает фактическую цепочку flood;
- позволяет получателю вернуть reciprocal route;
- ограничивает длину пакета;
- помогает loop detection;
- даёт hop count для диагностики.

Если `(count + 1) × hash_size > MAX_PATH_SIZE`, дальнейший forwarding прекращается независимо от `flood.max`.

## Ограничение hop count

CLI:

```text
get flood.max
set flood.max <0..64>
```

Default документирован как `64`. Это верхний предел forwarding для обычного flood, но фактический path может закончиться раньше из-за 64-byte storage.

Отдельные пределы:

```text
flood.max.unscoped
flood.max.advert
```

- `flood.max.unscoped` ограничивает packet без region scope;
- `flood.max.advert` ограничивает advert, default `8`.

Значение `0` нужно трактовать по коду конкретной версии: оно может означать запрет распространения, а не «без ограничения».

## Unscoped flood

Packet без transport codes распространяется по обычным правилам. В большой сети это позволяет чужому или старому client отправить flood через все regions.

Вместо полного `region denyf *` можно задать малый `flood.max.unscoped`, например несколько hop. Тогда локальное взаимодействие сохраняется, а глобальное распространение ограничивается.

## Flood advert

Advert велик: содержит 32-byte public key, 64-byte signature, timestamp и appdata. Его flood дороже короткого ACK.

Параметры:

```text
flood.advert.interval <3..168 hours>
advert.interval <60..240 minutes>  # zero-hop, если включён
flood.max.advert <0..64>
```

Default flood interval в CLI: 12 часов для Repeater и 0 для Sensor. Конкретные роли могут отличаться.

Частый advert в dense mesh расходует airtime и seen-table capacity. Для стационарного repeater интервал выбирают исходя из необходимости обнаружения, а не желания постоянно «пинговать» сеть.

## Duplicate suppression

Seen table хранит hash уже обработанных packets. Копия от другого соседа отбрасывается. Это основной механизм остановки обычного flood.

Он не абсолютен:

- изменённый payload создаёт другой packet hash;
- слишком короткое время хранения позволяет поздний повтор;
- hash collision может ошибочно подавить другой packet;
- reboot очищает volatile state;
- несовместимый custom repeater может пересобрать пакет иначе.

Поэтому дополнительно используются hop limit, path size и loop detection.

## `rxdelay`: приоритет сильной копии

Экспериментальная настройка:

```text
get rxdelay
set rxdelay <0..20>
```

При включении dispatcher рассчитывает score по SNR и длине. Сильная копия обрабатывается сразу, слабая попадает в delayed inbound queue. Идея: дать более качественному пути распространиться первым, чтобы слабые ветви позже увидели duplicate.

Риски:

- повышается latency слабых, но единственных links;
- score не равен долгосрочной надёжности;
- разные версии могут считать его по-разному;
- слишком большой delay влияет на ACK timeout.

Параметр следует тестировать на статистике, а не включать глобально без сравнения.

## Regions

Transport flood содержит region-derived code. Repeater может:

- разрешить scope;
- запретить scope;
- разрешить parent/child policy;
- отдельно обработать wildcard/unscoped.

Regions уменьшают область flood и являются основным способом масштабирования нескольких локальных mesh внутри общей радиосвязности. Они не являются шифрованием: code видим и служит фильтром forwarding.

## Packet storm

Шторм возникает, если packet перестаёт распознаваться как duplicate и циркулирует до максимального path/hop. Причины:

- bad/custom firmware изменяет payload при forwarding;
- bridge импортирует packet как новый;
- loop через несовместимые протоколы;
- packet hash нестабилен;
- loop detection отключён.

Признаки:

- быстро растёт `n_recv_flood` и `n_sent_flood`;
- одинаковые сообщения появляются многократно;
- TX queue заполнена;
- duty budget исчерпан;
- direct ACK задерживаются;
- path содержит повторяющиеся hash.

Меры: временно `set repeat off`, включить loop detection, уменьшить `flood.max`, изолировать suspect repeater и исследовать raw logs.

## Пример распространения

```text
A → R1 → R3 → B
 \→ R2 -/
```

1. A отправляет flood с пустым path.
2. R1 и R2 слышат A, добавляют свои hash и ждут random delay.
3. R1 передаёт раньше.
4. R3 принимает путь `[R1]`, добавляет себя и отправляет `[R1,R3]`.
5. R2 может услышать копию и подавить свою передачу.
6. B расшифровывает payload и возвращает `[R1,R3]` как direct path в обратном порядке, соответствующем реализации returned path.

Если R1 позже исчезнет, сохранённый direct path не заработает, пока не будет выполнен новый flood discovery.

## Когда flood оправдан

- неизвестен path;
- destination mobile и старый path устарел;
- group channel рассчитан на широкое распространение;
- advert должен обновить topology;
- аварийное сообщение должно попробовать несколько ветвей;
- local discovery не подходит.

## Когда flood следует избегать

- path уже известен и стабилен;
- telemetry отправляется часто;
- payload большой;
- сеть плотная;
- destination расположен в другом ограниченном scope;
- пользователь повторяет сообщение только из-за задержанного UI.

## Связанные статьи

- [Direct routing и поиск пути](/wiki/direct-routing-and-path-discovery)
- [Path hash, дубли и петли](/wiki/path-hashes-duplicates-and-loops)
- [Regions](/wiki/regions-and-transport-codes)
- [Airtime и ёмкость](/wiki/airtime-duty-cycle-and-capacity)

## Источники

- <https://github.com/meshcore-dev/MeshCore/blob/main/src/Mesh.cpp>
- <https://github.com/meshcore-dev/MeshCore/blob/main/src/Dispatcher.cpp>
- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/cli_commands.md>
- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/faq.md>

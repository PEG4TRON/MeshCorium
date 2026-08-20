# ACK, повторные попытки и multipart

Надёжность MeshCore строится поверх ненадёжной радиосреды. LoRa CRC обнаруживает повреждённый кадр, но не сообщает отправителю о доставке. Для end-to-end подтверждения destination создаёт ACK, который должен пройти отдельный обратный маршрут.

![Прохождение сообщения и ACK](/attachments/ru/ack-flow.svg?v=2)

## Уровни успешности

Важно различать:

1. packet создан и поставлен в queue;
2. radio начал TX;
3. radio сообщил `TX_DONE`;
4. хотя бы один сосед принял packet;
5. repeaters переслали его;
6. destination расшифровал payload;
7. приложение обработало сообщение;
8. ACK создан;
9. ACK вернулся к sender.

`TX_DONE` подтверждает только третий пункт. Пользовательский интерфейс не должен показывать «доставлено» до end-to-end ACK, если protocol его ожидает.

## Формат ACK

`PAYLOAD_TYPE_ACK` payload:

```text
checksum: uint32 little-endian
```

Checksum вычисляется из timestamp, message text и sender public key. Он позволяет sender сопоставить ACK с исходным сообщением.

ACK не повторяет ciphertext и экономит airtime. Но 32-bit checksum не является цифровой подписью; доверие происходит из контекста маршрута и защищённого обмена.

## Discrete и bundled ACK

### Discrete ACK

Отдельный packet типа ACK проходит по обратному path.

Плюсы:

- простой;
- можно отправить после обработки;
- отдельная статистика.

Минусы:

- дополнительный packet;
- дополнительная preamble/overhead;
- отдельная вероятность коллизии.

### Bundled ACK

Returned path имеет `extra type` и `extra`. ACK вкладывается в PATH, который destination и так должен вернуть после flood discovery.

Это экономит один TX sequence, особенно для первого сообщения неизвестному path.

CLI commands по документации не вызывают ни discrete, ни extra ACK. Ответ команды является отдельным application response.

## Retry и attempt

Text flags хранят attempt в двух bits `0..3`. Клиент может выполнить до четырёх помеченных попыток в рамках формата.

Retry нужен, если ACK не пришёл, но причина неизвестна:

- data packet потерян;
- destination получил packet, но ACK потерян;
- direct path устарел;
- queue задержала ACK;
- duty budget истощён;
- UI timeout слишком короткий;
- destination обработал сообщение медленно.

Поэтому повтор должен быть **идемпотентным** на application level. Для текста duplicate можно скрыть по checksum/timestamp. Для команды «открыть клапан» повтор без operation ID может быть опасен.

## Timeout

Timeout должен учитывать:

```text
data airtime × hop
+ retransmit delays
+ queue delays
+ destination processing
+ ACK airtime × reverse hop
+ duty-cycle wait
```

Фиксированные 2 секунды не подходят для SF11 packet через 10 hop. Слишком короткий timeout создаёт ненужные retries; слишком длинный делает интерфейс неотзывчивым.

Companion example использует base timeout и per-hop factors. Interoperable client должен читать path length и radio settings, а не использовать одно значение для всех сетей.

## ACK по direct path

На обратном пути каждый repeater:

- может локально уведомить logic об ACK;
- проверяет seen table;
- удаляет свою path entry;
- ставит ACK в high-priority queue.

Если один hop исчез, ACK не возвращается, даже если data packet уже доставлен. Sender повторит сообщение. Destination должен suppress duplicate application delivery.

## Early received ACK

Код проверяет ACK даже у direct packet с непустым path до forwarding. Это позволяет промежуточному узлу обновить локальное состояние/наблюдение, затем продолжить route.

Не следует трактовать observation ACK промежуточным repeater как подтверждение sender: ACK ещё должен пройти остаток пути.

## Multi-ACK

CLI:

```text
get multi.acks
set multi.acks 0|1
```

Default `0`. При включении implementation может отправить дополнительные ACK copies.

`createMultiAck` формирует `PAYLOAD_TYPE_MULTIPART`:

```text
byte 0:
  upper nibble = remaining ACK count
  lower nibble = PAYLOAD_TYPE_ACK
bytes 1..:
  ACK payload
```

Copies разнесены по времени. Цель — увеличить вероятность хотя бы одного успешного ACK на плохом reverse path.

Цена:

- airtime растёт;
- congestion повышается;
- duplicate ACK занимают queue;
- в плотной сети ухудшаются другие сообщения.

Multi-ACK не исправляет broken path: все copies пойдут по той же цепочке.

## Multipart не равен полной fragmentation

Текущий общий код обрабатывает multipart ACK. Поле remaining count само по себе недостаточно для универсальной сборки большого payload:

- нет глобального sequence ID;
- нет offset;
- нет total length;
- нет стандартного selective repeat;
- нет общей reassembly schema.

Custom application не должно дробить произвольные данные, предполагая, что любой MeshCore client соберёт их автоматически.

## Duplicate suppression у destination

Destination должен помнить message checksum/timestamp хотя бы дольше retry window. Иначе потерянный ACK приводит к повторному отображению сообщения.

Для команд/transactions лучше добавить application ID в encrypted body:

```text
operation_id | command | parameters
```

Сервер хранит выполненные IDs и возвращает тот же result без повторного side effect.

## ACK и group messages

Group text имеет множество получателей. Универсальный ACK от каждого участника создал бы ACK implosion. Поэтому group delivery обычно best-effort или использует ограниченный прикладной механизм.

«Сообщение отправлено в channel» не означает, что его получил каждый член. Для критической команды следует использовать адресный request/response к конкретным nodes.

## ACK и Room Server

Room/remote command может подтверждаться application response, а не generic ACK. Полезно разделять:

- radio delivery;
- server accepted request;
- server committed message;
- client synchronized result.

Generic ACK подтверждает packet, но не обязательно успешное выполнение операции.

## Алгоритм повторов

Практический вариант:

```text
attempt 0: direct по cached path
attempt 1: direct после небольшого jitter
attempt 2: reset stale path и flood discovery
attempt 3: повтор по новому path
```

Не всегда нужно использовать все четыре. Sensor может отказаться после одной попытки, emergency client — использовать более устойчивую policy.

Backoff должен рандомизироваться, иначе два узла повторят collision синхронно.

## Диагностика отсутствия ACK

1. подтвердить, что data достиг destination по его log;
2. проверить, сформирован ли ACK;
3. проверить reverse path;
4. сравнить TX/receive direct counters на каждом hop;
5. проверить duty budget и queue;
6. проверить hash collision;
7. выполнить trace обоих направлений;
8. увеличить application timeout;
9. временно включить Multi-ACK для сравнительного теста;
10. не оставлять его включённым без анализа airtime.

## Связанные статьи

- [Direct routing](/wiki/direct-routing-and-path-discovery)
- [Airtime](/wiki/airtime-duty-cycle-and-capacity)
- [Trace](/wiki/trace-and-route-diagnostics)
- [Пользовательские payload](/wiki/user-payloads)

## Источники

- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/payloads.md>
- <https://github.com/meshcore-dev/MeshCore/blob/main/src/Mesh.cpp>
- <https://github.com/meshcore-dev/MeshCore/blob/main/examples/companion_radio/MyMesh.cpp>
- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/cli_commands.md>

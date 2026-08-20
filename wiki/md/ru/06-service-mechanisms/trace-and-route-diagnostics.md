# Trace и диагностика маршрута

MeshCore trace проходит по заданному direct path и собирает SNR, измеренный каждым промежуточным узлом при приёме packet. Это инструмент анализа конкретной цепочки, а не аналог IP traceroute с TTL probes.

## Формат и обработка

`PAYLOAD_TYPE_TRACE` в текущем `Mesh.cpp` используется только с direct route. Payload начинается с:

```text
trace_tag: 4 bytes
auth_code: 4 bytes
flags: 1 byte
supplied path: variable
```

Lower 2 bits flags задают path identity size как степень двойки для supplied path matching в trace logic. Packet path area при прохождении используется для накопления `SNR × 4`, а не node hash.

Это особый случай: поле `packet->path` в trace содержит measurements, пока route для следующих hop находится внутри payload.

## Прохождение hop

Промежуточный узел:

1. вычисляет offset следующей identity в supplied path;
2. сравнивает её со своей identity;
3. проверяет forwarding permission и seen table;
4. добавляет signed SNR, умноженный на 4;
5. ставит packet на direct retransmission.

Когда supplied path закончен, destination вызывает `onTraceRecv` с accumulated measurements.

## Что измеряет SNR hop

Каждое значение относится к приёму предыдущей передачи:

```text
Source --SNR1--> R1 --SNR2--> R2 --SNR3--> Destination
```

- `SNR1` измерен R1 при packet от Source;
- `SNR2` — R2 при packet от R1;
- `SNR3` — Destination при packet от R2.

Значение не характеризует обратное направление.

## Масштаб ×4

SNR хранится как signed byte в четвертях dB:

```text
wire_value = round(SNR_dB · 4)
SNR_dB = wire_value / 4
```

Примеры:

| Byte signed | SNR |
|---:|---:|
| `40` | +10 dB |
| `4` | +1 dB |
| `0` | 0 dB |
| `-20` | −5 dB |
| `-48` | −12 dB |

При декодировании нельзя трактовать byte как unsigned: `0xEC` — это `-20`, а не 236.

## Trace tag

Tag связывает response/event с запросом и различает одновременные traces. Он не является долгосрочной identity.

Client должен:

- выбирать непредсказуемое/уникальное значение;
- хранить pending request до timeout;
- отвергать старые responses с другим tag;
- не использовать tag как authentication.

## Auth code

Auth code защищает trace workflow согласно implementation. Публичная packet документация не описывает его как универсальную криптографическую схему. Interoperable реализация должна повторять код конкретной firmware, а не предполагать CRC/password.

## Отличие от IP traceroute

IP traceroute:

- отправляет series packets с растущим TTL;
- каждый router возвращает ICMP Time Exceeded;
- выявляет route без заранее полного списка.

MeshCore trace:

- использует уже заданный path;
- один packet проходит через перечисленные hops;
- каждый hop добавляет SNR;
- не открывает неизвестный route;
- не измеряет IP latency каждого router.

Для неизвестного destination сначала нужен path discovery.

## Что trace может показать

- слабый hop внутри длинной цепочки;
- место, где packet перестаёт проходить;
- изменение SNR после замены антенны;
- различие двух cached paths;
- нестабильный mobile repeater;
- влияние времени суток/помех;
- path hash mismatch.

## Чего trace не показывает

- точный RSSI каждого hop, если format несёт только SNR;
- noise floor отдельно;
- packet loss probability по одному sample;
- обратный SNR;
- queue delay каждого hop;
- причину отсутствия response;
- скрытые alternative paths;
- nodes, которые слышали packet, но не были next hop.

## Partial trace

Если packet дошёл не до конца, client может получить неполные данные только если implementation возвращает/логирует их. Простое исчезновение trace не говорит, какой hop был последним: packet мог потеряться при TX, RX, forwarding policy или response.

Для локализации:

1. выполнить trace до полного destination;
2. при failure укоротить path до промежуточного node;
3. проверить zero-hop neighbors вокруг suspect segment;
4. сравнить counters;
5. повторить несколько раз.

## Измерение во времени

Один trace — снимок. Для статистики:

- повторить 20–100 раз;
- добавить jitter между probes;
- считать median и percentiles;
- записывать loss/no response;
- сравнивать часы busy/quiet;
- не создавать постоянный high-rate monitoring по radio mesh.

Trace сам создаёт traffic и может изменить состояние channel.

## SNR и margin

Высокий SNR не всегда означает хороший route:

- hop может иметь высокий SNR, но частые collisions;
- receiver может быть перегружен внеполосным сигналом;
- next hop queue переполнена;
- reverse path broken;
- identity collision вызывает forwarding двумя узлами.

Низкий, но стабильный отрицательный SNR может давать хороший PDR на LoRa. Оценка строится по series traces и packet counters.

## Сравнение после изменения

При замене antenna или TX power сохраняют одинаковыми:

- radio profile;
- path;
- packet length;
- время/условия;
- orientation;
- number of samples.

Если path discovery выбрал другой route, сравнение SNR не показывает эффект только оборудования.

## Команда companion

Example companion protocol содержит `CMD_SEND_TRACE_PATH` и push `PUSH_CODE_TRACE_DATA`. Точный frame между app и companion относится к Companion Protocol, но radio packet остаётся `PAYLOAD_TYPE_TRACE`.

Client должен отображать:

- path entry order;
- SNR signed quarter-dB;
- missing hops;
- timestamp;
- tag;
- firmware/path hash mode.

## Диагностический сценарий

Проблема: direct message A → D не получает ACK, path `[R1,R2,R3]`.

1. trace A → D десять раз;
2. если все обрываются после R2, проверить R2→R3;
3. запросить neighbors R2/R3;
4. проверить, не изменился ли hash R3 после reflash;
5. выполнить reverse trace D → A;
6. сравнить SNR и loss;
7. проверить region policy R3;
8. reset path и выполнить new discovery;
9. сравнить новый path.

## Безопасность

Trace раскрывает topology и quality metadata. В hostile environment частые traces помогают наблюдателю:

- связать identities;
- определить backbone repeaters;
- найти слабый hop;
- оценить период активности.

Доступ к remote diagnostics следует ограничивать ACL, а результаты не публиковать без необходимости.

## Связанные статьи

- [Direct routing](/wiki/direct-routing-and-path-discovery)
- [RSSI и SNR](/wiki/rssi-snr-and-link-quality)
- [Статистика и logging](/wiki/statistics-and-logging)

## Источники

- <https://github.com/meshcore-dev/MeshCore/blob/main/src/Mesh.cpp>
- <https://github.com/meshcore-dev/MeshCore/blob/main/src/Packet.h>
- <https://github.com/meshcore-dev/MeshCore/blob/main/examples/companion_radio/MyMesh.cpp>

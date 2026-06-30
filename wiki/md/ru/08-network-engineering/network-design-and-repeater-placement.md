# Проектирование сети и размещение ретрансляторов

Repeater должен создавать новые надёжные связи, а не просто увеличивать число узлов в одной точке. Высота, зона Френеля, noise floor и двусторонний link budget обычно важнее максимальной мощности.

![Размещение ретранслятора](/attachments/ru/repeater-placement.svg?v=2)

## Начать с требований

До выбора крыши определяют:

- территорию покрытия;
- число пользователей и sensors;
- критические направления;
- допустимую задержку;
- требуемую вероятность доставки;
- автономность;
- наличие emergency traffic;
- допустимые frequency/EIRP/duty cycle;
- способ физического обслуживания.

Сеть для десяти туристов и сеть для сотни стационарных датчиков имеют разные ограничения, даже если используют один radio profile.

## Типы topology

### Sparse mesh

Узлы далеко, каждый repeater критичен. Плюсы — мало duplicate traffic. Минусы — single points of failure и длинные paths.

Нужны:

- большой fade margin;
- резервное питание;
- минимум два независимых направления для backbone;
- monitoring каждого hop.

### Dense mesh

Много перекрывающихся links. Плюсы — alternative paths. Минусы — flood amplification, collisions и hash collisions.

Нужны:

- direct routing;
- regions;
- адекватный `txdelay`;
- редкие adverts;
- отключение бесполезных repeaters.

### Linear chain

Типична для долины, дороги или туннеля. Один failure разрывает сеть. Добавляйте bypass links или два разнонаправленных узла в критических точках.

### Star-like

Высокий central repeater слышит многие edges. Это удобно, но создаёт bottleneck и single RF point of failure. Второй независимый hub должен находиться в другой позиции, а не на той же мачте с тем же питанием.

### Mesh islands

Группы связаны редким bridge hop. Traffic между islands нужно ограничивать scope, иначе один flood проходит через все локальные области.

## Выбор площадки

Хорошая площадка:

- имеет radio visibility в нужные направления;
- находится выше локальных препятствий;
- имеет низкий noise floor;
- допускает короткий RF cable;
- имеет безопасное питание и grounding;
- доступна для обслуживания;
- не находится рядом с мощным transmitter без фильтрации;
- защищена от воды и температуры.

Плохая высокая площадка рядом с broadcast equipment может уступать более низкой тихой точке.

## Высота и зона Френеля

Поднять antenna на 5–10 м часто эффективнее `+3 dB` TX. Высота:

- открывает LOS;
- очищает Fresnel;
- уменьшает building/vegetation loss;
- расширяет collision domain.

Последний пункт важен: слишком высокий repeater может слышать несколько dense regions и участвовать в каждом flood. Coverage и capacity оптимизируют вместе.

## Antenna pattern

Omnidirectional high-gain antenna не излучает одинаково во все направления. Вертикальный beam становится узким. Если repeater на горе, clients внизу могут попасть в null.

Для трассы между двумя точками directional antenna:

- увеличивает link budget;
- снижает noise из других направлений;
- уменьшает collision domain;
- требует точного наведения;
- не подходит как общий local repeater без второй radio/antenna.

## Кабель или radio у antenna

Длинный coax съедает gain и принимает помехи. Предпочтительно разместить radio в weatherproof enclosure рядом с antenna и вести вниз power/data, если:

- enclosure выдерживает температуру;
- питание защищено от surge;
- нет конденсата;
- доступно remote recovery;
- MCU/radio не перегреваются на солнце.

## Питание

### Сеть

Нужны UPS, surge protection и safe shutdown. Проверить brownout при максимальном TX/PA.

### Solar

Energy budget:

```text
Eday = RX_current · 24h + TX_current · TX_hours + MCU/peripherals
```

RX repeater потребляет постоянно. Нельзя считать только редкий TX. Solar design учитывает:

- худший зимний месяц;
- несколько пасмурных дней;
- battery derating на холоде;
- self-discharge;
- charger efficiency;
- aging.

Power-saving sleep уменьшает availability и требует отдельного protocol design.

## Weatherproofing

- enclosure с правильным IP rating;
- cable glands вниз;
- drip loop;
- vent membrane против condensation;
- UV-resistant cable;
- герметизация RF connectors;
- corrosion-compatible metals;
- lightning protection;
- strain relief.

Герметичный box без вентиляции может накопить конденсат из воздуха, закрытого при сборке.

## Redundancy

Резервный route должен быть независимым:

- другая площадка;
- другое питание;
- другой RF path;
- другой кабель/antenna;
- по возможности другой оператор доступа.

Два repeaters на одной мачте и одном UPS не защищают от lightning, site outage и общего interference.

## Backbone и edge

Разделяйте:

- **backbone repeaters** — стабильные высокие узлы между areas;
- **edge repeaters** — локальное покрытие users;
- **mobile repeaters** — временное расширение.

Direct paths через backbone должны быть устойчивы. Mobile node не следует делать единственным bridge между areas.

## Frequency и profile planning

Один MeshCore segment требует общего profile. Для большой территории возможны несколько profiles с application bridge, но это усложняет:

- identity mapping;
- loop prevention;
- duplicate suppression;
- channel secrets;
- monitoring;
- legal compliance.

Сначала используйте regions и direct routing. Разделение frequencies оправдано при реальной airtime congestion или сильной interference.

## Предпроектное обследование

1. выбрать candidate sites по terrain profile;
2. измерить spectrum/noise на каждой площадке;
3. установить temporary nodes на планируемой высоте;
4. провести bidirectional packet tests;
5. собрать RSSI/SNR/PDR минимум несколько часов;
6. проверить busy period;
7. построить candidate graph links;
8. выбрать topology с резервом;
9. оценить flood load;
10. провести пилот до постоянного монтажа.

## Link matrix

Создайте таблицу:

| From \ To | R1 | R2 | R3 | Edge A |
|---|---:|---:|---:|---:|
| R1 | — | PDR/SNR | ... | ... |
| R2 | ... | — | ... | ... |

Измерять оба направления отдельно. На основе matrix строят graph и ищут:

- articulation points;
- links с низким margin;
- слишком длинные routes;
- бесполезные дублирующие sites.

## Acceptance test

После постоянной установки:

- проверить antenna VSWR;
- измерить TX power/EIRP;
- записать noise floor;
- выполнить zero-hop tests;
- выполнить flood discovery;
- получить direct path;
- выполнить traces в обе стороны;
- передать packets разных размеров;
- проверить ACK ratio;
- проверить queue/airtime в busy period;
- симулировать failure одного repeater;
- проверить recovery и path reset.

## Документация узла

Для каждого repeater:

- public key и name;
- role/firmware/board;
- coordinates и altitude;
- radio profile;
- TX setting и measured EIRP;
- antenna/cable/filter;
- power system;
- region policy;
- routing settings;
- neighbor baseline;
- serial recovery procedure;
- дата обслуживания.

Private key и passwords хранятся отдельно, не в публичной карте.

## Когда repeater лишний

Признаки:

- не создаёт новых reachable nodes;
- имеет те же neighbors, что nearby repeater;
- sent flood высокий, но paths через него почти не используются;
- duplicates выросли после установки;
- site шумный и ухудшает маршруты first-wins;
- antenna плохо установлена;
- mobile и часто ломает cached paths.

Отключение лишнего repeater иногда улучшает latency и PDR.

## Связанные статьи

- [Распространение и покрытие](/wiki/propagation-and-coverage)
- [Link budget](/wiki/frequency-power-and-link-budget)
- [Ёмкость и масштабирование](/wiki/capacity-and-scaling)
- [Статистика](/wiki/statistics-and-logging)

## Источники

- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/faq.md>
- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/cli_commands.md>
- <https://www.etsi.org/technologies/short-range-devices>

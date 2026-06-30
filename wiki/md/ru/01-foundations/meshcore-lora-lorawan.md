# MeshCore, LoRa и LoRaWAN

LoRa, LoRaWAN и MeshCore относятся к разным уровням. Ошибка в терминологии приводит к неправильным ожиданиям: поиску gateway там, где нужен repeater, попытке применить OTAA к MeshCore или предположению, что два устройства совместимы только потому, что оба имеют маркировку LoRa.

![MeshCore и LoRaWAN](/attachments/ru/meshcore-vs-lorawan.svg?v=2)

## LoRa — физическая модуляция

LoRa — радиомодуляция на основе Chirp Spread Spectrum. Она определяет, как биты превращаются в изменение радиосигнала и как приёмник восстанавливает их. К LoRa PHY относятся:

- несущая частота;
- bandwidth;
- spreading factor;
- coding rate;
- preamble и sync word;
- PHY header и CRC;
- мощность передатчика и режимы приёмника.

LoRa сама по себе не определяет контакты, чаты, маршруты, серверы, адреса приложений или правила подключения к сети. Поверх LoRa можно передавать LoRaWAN, MeshCore, Meshtastic, собственный бинарный протокол или тестовые данные.

## LoRaWAN — стандартизованная LPWAN-архитектура

LoRaWAN задаёт MAC и сетевую архитектуру. End devices передают LoRaWAN uplink, один или несколько gateways принимают его и пересылают по IP на Network Server. Сервер удаляет дубликаты, проверяет frame counters и MIC, управляет маршрутизацией downlink и рядом MAC-функций.

Типовые понятия LoRaWAN:

- Gateway и concentrator;
- Network Server, Application Server и Join Server;
- DevEUI, JoinEUI, AppKey/NwkKey;
- OTAA и ABP;
- uplink/downlink;
- confirmed/unconfirmed frames;
- ADR;
- RX1/RX2;
- классы A, B и C.

Обычный LoRaWAN end device не ретранслирует кадры другого end device. Топология называется star-of-stars: несколько gateways образуют точки доступа к централизованной сетевой части.

## MeshCore — самостоятельный mesh-протокол

MeshCore задаёт собственный формат пакета и собственные правила маршрутизации. Узлы принимают LoRa-кадр, разбирают MeshCore header и могут переслать пакет по flood или direct path.

Ключевые понятия MeshCore:

- Ed25519 identity;
- advert;
- contact и group channel;
- route type;
- path hash;
- flood/direct routing;
- returned path;
- ACK и multipart;
- regions и transport codes.

Network Server не требуется. Repeater работает на том же LoRa-канале и повторно излучает MeshCore-пакеты, а не пересылает их на центральный сервер по Ethernet.

## Сравнение по уровням

| Свойство | MeshCore | LoRaWAN |
|---|---|---|
| Физический радионоситель | LoRa PHY | LoRa PHY |
| Основная топология | многохоповая mesh | star-of-stars |
| Промежуточный узел | Repeater принимает и повторно передаёт пакет | Gateway принимает кадр и передаёт его серверу по backhaul |
| Центр управления | не обязателен | Network Server является частью архитектуры |
| Идентичность | публичный ключ MeshCore | DevEUI/JoinEUI и session context |
| Ввод в сеть | обмен advert/contact/channel secrets | OTAA или ABP |
| Маршрутизация | flood/direct path внутри радио mesh | end device → gateway → server; downlink через выбранный gateway |
| Подтверждение | MeshCore ACK по обратному радио-пути | confirmed frame и LoRaWAN downlink |
| Группы | shared channel secret и group payload | multicast context LoRaWAN |
| Региональные области | MeshCore regions/transport codes | regional parameters и channel plan LoRaWAN |

## Почему одинаковая частота не даёт совместимость

Для успешного приёма сначала должны совпасть PHY-параметры. Но после демодуляции получатель увидит байты другого протокола. LoRaWAN header не соответствует MeshCore `VVPPPPRR`, а MeshCore packet не содержит LoRaWAN MHDR, FHDR и MIC в ожидаемом виде.

Возможны три ситуации:

1. **PHY отличается.** Приёмник вообще не декодирует кадр.
2. **PHY совпадает, протокол отличается.** Радиочип выдаёт байты, но прошивка отвергает их как неизвестные или повреждённые.
3. **PHY и протокол совпадают, ключи отличаются.** Пакет разбирается, однако payload не проходит аутентификацию или не относится к известному контакту/каналу.

## Repeater не является Gateway

LoRaWAN gateway обычно содержит многоканальный concentrator и может одновременно принимать несколько частот/SF. MeshCore repeater чаще построен на обычном single-channel LoRa transceiver и в каждый момент работает с одним radio profile.

Gateway не строит многохоповый LoRaWAN-маршрут через соседний gateway. MeshCore repeater именно добавляет радиопереход. Поэтому требования различаются:

- gateway требует надёжного IP backhaul;
- repeater требует хорошей радиовидимости до соседних MeshCore-узлов;
- gateway может принимать множество LoRaWAN-каналов;
- MeshCore repeater должен совпадать с сетью по конкретному профилю;
- отказ gateway влияет на доступ к серверу;
- исчезновение repeater ломает direct path, проходившие через него.

## ADR и ручной radio profile

LoRaWAN ADR позволяет серверу управлять data rate и мощностью end device в рамках регионального плана. В MeshCore все участники общего канала должны иметь совместимые настройки. Самовольная смена SF или BW одним узлом фактически выводит его в другую радиосеть.

Поэтому изменение профиля MeshCore — операция миграции:

- определить новый набор параметров;
- проверить аппаратную поддержку всех узлов;
- выбрать порядок обновления;
- предусмотреть временный доступ через `tempradio` или физическую консоль;
- обновить критические repeaters;
- только затем переводить клиентов.

## LoRaWAN regional parameters и законы

LoRaWAN regional parameters — часть стандарта LoRaWAN, но юридические ограничения исходят из национального регулирования спектра. MeshCore не освобождается от этих правил. Частота, EIRP, duty cycle, channel access и допустимая полоса зависят от страны и поддиапазона.

Нельзя переносить на MeshCore конкретную LoRaWAN channel mask без проверки. Также нельзя считать документированный default MeshCore универсально законным во всех странах.

## Совместное использование диапазона

MeshCore и LoRaWAN могут работать в одном нелицензируемом диапазоне и создавать взаимные помехи. Даже если sync word или параметры различаются, мощный соседний сигнал способен:

- занять канал для CAD;
- повысить noise floor;
- перегрузить вход приёмника;
- испортить слабый пакет;
- увеличить задержки и число повторов.

Координация частоты, BW, мощности и времени передачи важна не только внутри MeshCore, но и относительно других пользователей диапазона.

## Когда нужен LoRaWAN, а когда MeshCore

LoRaWAN логичен, когда много маломощных датчиков должны отправлять небольшие данные в серверную инфраструктуру, а gateways имеют backhaul.

MeshCore логичен, когда нужна локальная автономная связь между людьми или устройствами, нет гарантированного интернета и полезна многохоповая ретрансляция.

Эти системы можно интегрировать через bridge, но bridge должен преобразовывать прикладные данные. Непосредственная маршрутизация одного wire format как другого невозможна.

## Связанные статьи

- [Радиомодель MeshCore](/wiki/meshcore-radio-model)
- [Модуляция и параметры LoRa](/wiki/lora-modulation-and-parameters)
- [Радиопрофиль и оборудование](/wiki/radio-profile-and-hardware)
- [Совместимость и миграция](/wiki/compatibility-and-migration)

## Источники

- <https://www.semtech.com/lora/what-is-lora>
- <https://lora-alliance.org/resource_hub/what-is-lorawan/>
- <https://lora-alliance.org/lorawan-for-developers/>
- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/packet_format.md>
- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/faq.md>

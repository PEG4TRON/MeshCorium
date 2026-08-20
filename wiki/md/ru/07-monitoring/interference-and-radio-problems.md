# Помехи и проблемы радиоприёма

Плохой приём не всегда вызван слабым MeshCore-сигналом. Receiver может быть перегружен мощной соседней системой, собственным DC/DC, USB или дисплеем. При этом RSSI бывает высоким, а полезные packets исчезают.

## Co-channel interference

Передатчик использует тот же frequency/BW и перекрывает MeshCore packet. Источники:

- другая MeshCore сеть;
- LoRaWAN;
- Meshtastic/custom LoRa;
- не-LoRa digital transmitter;
- намеренный jammer.

Если packets перекрываются во времени, receiver может:

- декодировать более сильный через capture effect;
- получить CRC error;
- не обнаружить ни один;
- зависеть от SF и power difference.

## Adjacent-channel interference

Сигнал находится рядом по частоте, но его спектральные хвосты или receiver selectivity влияют на канал. Особенно опасны:

- высокий power close transmitter;
- широкий bandwidth;
- плохой output filter;
- слабый desired signal;
- дешёвый front-end без band filter.

Изменение MeshCore frequency на несколько десятков кГц может не помочь, если interferer перегружает весь LNA/mixer.

## Blocking и desensitization

**Blocking** — сильный внеполосный сигнал снижает способность принимать слабый desired signal. Receiver может не показывать его как in-channel RSSI, но gain stages уже насыщены.

Пример: repeater на мачте рядом с мощным VHF/UHF transmitter. Антенна высокого gain принимает много энергии; LoRa node становится «глухим», хотя desktop test работал.

Меры:

- band-pass filter;
- физическое расстояние;
- antenna placement/null;
- отдельная мачта;
- снижение boosted gain;
- улучшение grounding/shielding;
- проверка intermodulation products.

## Intermodulation

Нелинейный элемент смешивает два сильных signals и создаёт продукты:

```text
2f1 - f2
2f2 - f1
f1 + f2
```

Один продукт может попасть точно в MeshCore channel, хотя исходные transmitters находятся далеко. Источником нелинейности бывает receiver front-end, rusty connector, PA или плохой active device.

Диагностика требует spectrum analyzer и временной корреляции с работой transmitters.

## Wideband noise

Импульсный DC/DC, USB 3, HDMI, display ribbon, дешёвый charger или solar controller может поднять floor на широкой полосе.

Тест:

1. записать noise floor на рабочем питании;
2. отключить USB;
3. питать от аккумулятора;
4. выключить display/GPS/Wi-Fi;
5. отключить charger/solar;
6. сравнить spectrum и PDR.

Если unplug USB даёт +10 dB SNR, проблема внутри установки, а не в route.

## Self-interference

Узел может мешать себе:

- MCU clock harmonic;
- OLED/TFT refresh;
- GPS LNA/oscillator;
- BLE/Wi-Fi bursts;
- switching regulator;
- long unshielded wires;
- external PA feedback.

Board firmware может выключать noisy peripheral на время RX/TX. Но это влияет на latency и требует конкретной hardware integration.

## Receiver overload от собственного TX

Несколько radios на одной площадке создают near-field coupling. Даже разные frequencies могут перегрузить LNA. Требуются:

- antenna separation;
- vertical/horizontal separation по расчёту;
- cavity/band filters;
- coordinated TX;
- shielding;
- проверка isolation в dB.

Простой разнос на метр не всегда достаточен при watt-level transmitter.

## AGC deafness

После сильного signal AGC может оставаться в невыгодном состоянии. CLI:

```text
get agc.reset.interval
set agc.reset.interval <seconds>
```

`0` отключает. Интервал округляется к кратному четырём.

Использование:

- сначала подтвердить, что failure появляется после strong burst;
- сравнить packet reception с manual/reboot reset;
- подобрать минимально редкий interval;
- проверить, не теряются packets во время reset.

Это workaround, не замена RF filter.

## RX boosted gain

`radio.rxgain on` повышает sensitivity, но может уменьшить headroom. В тихой rural точке это полезно. На telecom site `off` иногда даёт лучший PDR при более низком apparent RSSI.

Сравнивать нужно по test sequence, а не одному packet.

## `int.thresh`

Local interference threshold передаётся в noise-floor calibration wrapper:

```text
get int.thresh
set int.thresh <value>
```

Поскольку единицы/semantics зависят от implementation, параметр нельзя настраивать по чужому рецепту. Неверный threshold способен считать channel постоянно busy или игнорировать реальную активность.

## Частотная ошибка

Причины:

- плохой crystal;
- неверная TCXO configuration;
- температура;
- неверный reference frequency;
- повреждение board.

Признаки:

- один node не слышит сеть при узкой BW;
- warm-up меняет связь;
- проблема зависит от температуры;
- spectrum peak смещён;
- широкая BW временно исправляет.

Измеряют frequency counter/spectrum analyzer или сравнивают с reference radio.

## Antenna/RF switch failure

Признаки неправильного RF switch:

- TX виден только рядом;
- RX видит только сильные packets;
- power meter показывает низкий output;
- после TX receiver не возвращается;
- проблема появилась после смены board variant.

Проверить pins, timing, DIO, PA path и фактическую ревизию.

## Коллизии или RF noise?

### Коллизии

- ухудшение в busy hours;
- duplicate counters растут;
- короткие packets лучше длинных;
- randomizing traffic помогает;
- spectrum показывает отдельные LoRa bursts.

### Постоянный noise

- noise floor стабильно высокий;
- disconnect local electronics помогает;
- смена frequency помогает;
- packets плохи даже при одном sender;
- spectrum показывает continuous/periodic emissions.

### Broken route

- zero-hop links хорошие;
- только один direct contact не работает;
- path reset исправляет;
- trace обрывается на одном hop.

## Инструменты

- MeshCore raw RX log;
- `stats-radio`;
- sequence packet generator;
- SDR waterfall;
- spectrum analyzer;
- attenuator и signal generator;
- VNA для antenna/filter;
- power meter;
- near-field probes;
- reference receiver.

SDR waterfall показывает активность, но его own overload/dynamic range тоже нужно учитывать.

## План диагностики

1. проверить radio profile и firmware;
2. провести zero-hop test на короткой дистанции с attenuation;
3. сравнить known-good antenna/cable;
4. измерить noise floor;
5. отключить local electronics;
6. проверить RSSI/SNR/PDR series;
7. проверить другой channel, если законно;
8. проверить boosted gain;
9. выполнить trace;
10. измерить spectrum и filtering;
11. только после этого менять network routing parameters.

## Снижение помех

- фильтр перед receiver;
- короткий coax;
- правильное grounding;
- shield digital electronics;
- ferrite/common-mode suppression;
- frequency planning;
- lower TX power близких nodes;
- separate antennas;
- randomize sensor bursts;
- reduce airtime;
- relocate repeater.

## Связанные статьи

- [Антенны и RF-тракт](/wiki/antennas-and-rf-chain)
- [RSSI/SNR](/wiki/rssi-snr-and-link-quality)
- [Доступ к каналу](/wiki/channel-access-queues-and-delays)
- [Статистика](/wiki/statistics-and-logging)

## Источники

- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/faq.md>
- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/cli_commands.md>
- <https://github.com/meshcore-dev/MeshCore/blob/main/src/Dispatcher.cpp>
- <https://www.semtech.com/products/wireless-rf/lora-connect/sx1262>

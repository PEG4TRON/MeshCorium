# RSSI, SNR и качество радиолинии

RSSI, noise floor и SNR измеряют разные свойства принятого сигнала. Ни одно значение само по себе не описывает надёжность MeshCore route. Для инженерного вывода нужны серии packets, Packet Delivery Ratio, ACK и поведение в разное время.

![RSSI, noise floor и SNR](/attachments/ru/signal-metrics.svg?v=2)

## RSSI

**Received Signal Strength Indicator** — оценка мощности принятого сигнала на входе receiver. Обычно выражается в dBm и имеет отрицательное значение.

Пример относительной шкалы:

```text
-60 dBm сильнее -90 dBm
-90 dBm сильнее -120 dBm
```

Разница 30 dB соответствует тысяче раз по мощности.

RSSI конкретного packet зависит от:

- TX power;
- antenna gain и polarization;
- path loss;
- fading;
- bandwidth и receiver implementation;
- calibration offset чипа;
- сильной помехи в полосе;
- времени измерения.

Нельзя напрямую переводить RSSI в расстояние без модели среды.

## Packet RSSI и channel RSSI

**Packet RSSI** оценивается во время принятого кадра. **Channel RSSI** измеряет текущую энергию канала без обязательного валидного packet.

Высокий channel RSSI при отсутствии valid packets часто указывает на:

- широкополосный шум;
- чужой transmitter;
- receiver overload;
- собственную цифровую помеху платы;
- неверную calibration.

MeshCore `stats-radio` показывает noise floor и last RSSI/SNR, а raw logging может сохранить значения каждого packet.

## Noise floor

Noise floor — фон, относительно которого выделяется сигнал. Он складывается из:

- теплового шума;
- noise figure receiver;
- локальной электроники;
- внешних RF emitters;
- bandwidth;
- gain state.

Теоретическая thermal noise density около `−174 dBm/Hz` при комнатной температуре. В полосе BW она увеличивается:

```text
Noise ≈ -174 + 10·log10(BW_Hz) + NoiseFigure
```

Это ориентир. Реальный urban noise может быть значительно выше.

Удвоение BW увеличивает интегрированную шумовую мощность примерно на 3 dB.

## SNR

**Signal-to-Noise Ratio**:

```text
SNR(dB) = Signal(dBm) - Noise(dBm)
```

LoRa может декодировать packets при отрицательном SNR благодаря processing gain. Допустимый минимум зависит от SF, BW, CR и чипа.

Пример:

```text
signal = -120 dBm
noise  = -110 dBm
SNR    = -10 dB
```

Signal слабее noise power, но LoRa packet всё ещё может декодироваться.

## SNR ×4 в MeshCore

В `Packet` SNR хранится как signed `int8` в четвертях dB:

```text
stored = SNR · 4
SNR = stored / 4
```

Companion frames и neighbor output используют тот же принцип. Парсер должен преобразовать byte `0..255` в signed `−128..127` перед делением.

## Почему высокий RSSI может быть плохим

Пример:

```text
RSSI = -70 dBm
SNR  = -12 dB
```

Сильная общая энергия состоит в основном из помехи. Packet находится в шумном окружении.

Другой случай:

```text
RSSI = -120 dBm
SNR  = +5 dB
```

Сигнал слабый, но channel очень тихий. Такая линия может быть стабильнее первой, пока сохраняется fade margin.

## Sensitivity и required SNR

Receiver sensitivity можно оценить:

```text
Sensitivity ≈ thermal noise + 10log10(BW) + NF + required SNR
```

Высокий SF допускает более низкий required SNR. Поэтому threshold RSSI меняется с radio profile. Нельзя применять таблицу «−120 dBm хорошо/плохо» без SF/BW.

## Packet Delivery Ratio

```text
PDR = received_unique / sent
```

Это основной практический показатель. Считать нужно unique packets, исключая retries и duplicates, либо явно указывать методику.

Пример:

- отправлено 100 test messages;
- destination получил 92 unique;
- PDR = 92%;
- sender получил 85 ACK;
- end-to-end confirmed ratio = 85%.

Разница показывает проблемы reverse path/ACK.

## Packet Error Rate

PER измеряет долю пакетов с ошибкой/неприёмом. Radio часто не может посчитать все потерянные packets, потому что не знает, сколько было отправлено. Нужен sequence counter в test payload.

CRC error counter отражает только frames, где receiver обнаружил candidate и CRC mismatch. Полностью не обнаруженная preamble в него не входит.

## Link margin по SNR

Если radio profile требует условно `SNRmin`, запас:

```text
SNR margin = measured SNR - SNRmin
```

Но required SNR берётся из datasheet для конкретных условий. Запас должен покрывать fading и interference. Median margin недостаточен: важны minimum и low percentile.

## Метрики route

Route состоит из hop. End-to-end PDR приблизительно перемножает success probabilities links:

```text
Proute ≈ P1 · P2 · ... · Ph
```

Если каждый из пяти hop имеет 95% success:

```text
0.95^5 ≈ 77%
```

ACK должен пройти обратно, поэтому confirmed success может быть ещё ниже. Это объясняет, почему много «вроде хороших» hop создают заметно плохую связь.

## Series вместо одного packet

Минимальный тест:

- 50–100 packets;
- sequence number;
- одинаковый size;
- random interval;
- RSSI/SNR per receive;
- duplicates;
- latency;
- ACK status;
- время и radio profile.

Статистика:

- median RSSI/SNR;
- 10th percentile;
- PDR;
- confirmed ratio;
- duplicate ratio;
- maximum outage duration.

## Влияние packet length

Длинный packet имеет больше airtime и больше шанс overlap. При одинаковом RSSI PDR длинных payload может быть хуже.

Тест коротким advert не гарантирует доставку максимального text или group datagram. Нужно проверять реальные размеры.

## Показания разных чипов

SX127x, SX126x, LR1110 и wrappers могут иметь разные offsets/алгоритмы RSSI. Сравнивать абсолютные значения разных плат нужно осторожно.

Для relative теста используйте один receiver и меняйте один фактор. Для fleet monitoring сначала калибруйте модели на общем signal source.

## Признаки проблем

| Наблюдение | Возможная причина |
|---|---|
| RSSI и SNR постепенно падают | кабель, вода, foliage, перемещение |
| RSSI высокий, SNR низкий | interference/overload |
| RSSI/SNR хорошие, PDR плохой | collisions, queue, firmware, hash collision |
| direct плохой, flood хороший | stale path/один плохой hop |
| data доходит, ACK нет | reverse asymmetry |
| значение скачет при касании | antenna/ground plane |

## Представление в UI

Не следует сводить качество к одной «полоске». Полезно отображать:

- last RSSI/SNR с timestamp;
- число samples;
- PDR window;
- route hop count;
- ACK ratio;
- profile;
- warning, если sample старый.

## Связанные статьи

- [Trace](/wiki/trace-and-route-diagnostics)
- [Помехи](/wiki/interference-and-radio-problems)
- [Link budget](/wiki/frequency-power-and-link-budget)
- [Статистика](/wiki/statistics-and-logging)

## Источники

- <https://github.com/meshcore-dev/MeshCore/blob/main/src/Packet.h>
- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/cli_commands.md>
- <https://github.com/meshcore-dev/MeshCore/blob/main/docs/payloads.md>
- <https://www.semtech.com/products/wireless-rf/lora-connect/sx1262>

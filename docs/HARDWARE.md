# Hardware plan

## Bill of materials

| Qty | Part | Product |
|---:|---|---|
| 1 | ESP32-S3 Feather, 4 MB Flash / 2 MB PSRAM | [Adafruit PID 5477](https://www.adafruit.com/product/5477) |
| 1 | STEMMA Soil Sensor, I2C capacitive | [Adafruit PID 4026](https://www.adafruit.com/product/4026) |
| 1 | BME280 temperature/humidity/pressure sensor | [Adafruit PID 2652](https://www.adafruit.com/product/2652) |
| 1 | LTC4316 I2C address translator | [Adafruit PID 5914](https://www.adafruit.com/product/5914) |
| 2 | STEMMA QT/Qwiic JST-SH cable, 100 mm | [Adafruit PID 4210](https://www.adafruit.com/product/4210) |
| 1 | JST-PH to JST-SH STEMMA adapter cable, 200 mm | [Adafruit PID 4424](https://www.adafruit.com/product/4424) |
| 1 | 3.7 V 2500 mAh LiPo battery | [Adafruit PID 328](https://www.adafruit.com/product/328) |

A data-capable USB-C cable and 5 V USB power adapter are also needed, but do not
need to be purchased if already available.

## Wiring

```text
Feather -> BME280 -> LTC4316 input -> LTC4316 output -> soil sensor
```

Leave both LTC4316 switches on. The soil sensor's native `0x36` I2C address is
translated to `0x76`, avoiding the Feather's onboard MAX17048 battery monitor at
`0x36`. The BME280 normally remains at `0x77`.

## Battery telemetry

The Feather's MAX17048 can report battery voltage and estimated state of charge.
The planned payload includes both. Initial alerts are `battery_low` at 30% and
`battery_critical` at 15%; these thresholds should be tuned after observing the
real battery.

## Enclosure candidate

The leading off-the-shelf option is the
[Polycase ML-46F](https://www.polycase.com/ml-46f), with cable cutouts, adhesive
PCB mounts, and a vent near the BME280. Openings and vents can change the final
water-resistance rating.

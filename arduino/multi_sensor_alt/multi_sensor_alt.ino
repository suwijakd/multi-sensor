// ===========================================================================
// Wearable multi-sensor logger  —  ESP32-C3 Super Mini  —  ALTERNATIVE build
//
//   PPG  : GY-MAX30102        (I2C)  — IR channel used as the PPG signal
//   IMU  : GY-521 / MPU-6050  (I2C)  — accel + gyro (no magnetometer)
//   GSR  : Grove GSR v1.2      (analog)
//   TEMP : MLX90614 (GY-906)   (I2C)
//
// Drop-in alternative to ../multi_sensor/: it emits the IDENTICAL 15-column
// CSV stream, so pc/record.py needs no changes. To swap back, re-wire the
// original sensors and flash ../multi_sensor/. See README.md in this folder.
// ===========================================================================
#include <Arduino.h>
#include <Wire.h>
#include <math.h>
#include <MAX30105.h>            // SparkFun MAX3010x library (covers MAX30102)
#include <Adafruit_MPU6050.h>
#include <Adafruit_MLX90614.h>
#include "config.h"

#ifdef STREAM_WIFI
#include <WiFi.h>
static WiFiServer server(STREAM_PORT);
static WiFiClient wifiClient;
#endif

MAX30105 ppgSensor;
Adafruit_MPU6050 mpu;
Adafruit_MLX90614 mlx;

static bool ppg_ok = false;
static bool mpu_ok = false;
static bool mlx_ok = false;

static const uint32_t PERIOD_US  = 1000000UL / SAMPLE_RATE_HZ;
static const uint32_t TEMP_DECIM = SAMPLE_RATE_HZ / TEMP_RATE_HZ;

static uint32_t seq        = 0;
static uint32_t next_us    = 0;
static uint32_t overruns   = 0;
static uint32_t tx_dropped = 0;

static uint32_t ppg_ir   = 0;   // most recent MAX30102 IR sample (held)
static float    temp_obj = NAN;
static float    temp_amb = NAN;

static uint32_t stats_last_ms  = 0;
static uint32_t stats_last_seq = 0;

static char line[256];

// Same column layout as the default sketch (note the differing PPG units and
// the absent magnetometer, called out for whoever reads the stream live).
void emitMetaTo(Print &out) {
  out.println(F("# multi-sensor wearable logger (ALT: MAX30102 + MPU-6050)"));
  out.printf("# variant=max30102_mpu6050 sample_rate_hz=%d temp_rate_hz=%d\n",
             SAMPLE_RATE_HZ, TEMP_RATE_HZ);
  out.printf("# max30102=%s mpu6050=%s mlx90614=%s\n",
             ppg_ok ? "ok" : "MISSING", mpu_ok ? "ok" : "MISSING",
             mlx_ok ? "ok" : "MISSING");
#ifdef STREAM_WIFI
  out.printf("# wifi=AP ssid=%s ip=%s port=%d\n", WIFI_AP_SSID,
             WiFi.softAPIP().toString().c_str(), STREAM_PORT);
#endif
  out.println(F("# units: ppg_raw=MAX30102 IR counts  gsr=adc_counts(0-4095)  "
                "accel=m/s^2 gyro=rad/s  mag=nan(no magnetometer)  temp=degC  "
                "t_us=micros"));
  out.println(F("# columns: t_us,seq,ppg_raw,gsr_raw,ax,ay,az,gx,gy,gz,mx,my,mz,"
                "temp_obj_c,temp_amb_c"));
}

void setup() {
  // Match the default sketch: large USB TX buffer + non-blocking writes so the
  // sample clock never stalls on USB.
  Serial.setTxBufferSize(8192);
  Serial.begin(115200);
  Serial.setTxTimeoutMs(0);
  uint32_t t0 = millis();
  while (!Serial && (millis() - t0) < 2000) { delay(10); }

  pinMode(PIN_LED, OUTPUT);
  digitalWrite(PIN_LED, HIGH);  // off (active low)

  analogReadResolution(ADC_BITS);
  analogSetAttenuation(ADC_11db);

  // I2C up first on our pins; the library begin() calls reuse these pins.
  Wire.begin(PIN_SDA, PIN_SCL, I2C_FREQ_HZ);

  ppg_ok = ppgSensor.begin(Wire, I2C_SPEED_STANDARD);  // MAX30102 @ 0x57
  if (ppg_ok) {
    // powerLevel, sampleAverage, ledMode(2=Red+IR), sampleRate, pulseWidth, adcRange
    ppgSensor.setup(0x1F, 4, 2, 400, 411, 4096);
  }

  mpu_ok = mpu.begin(MPU_ADDR, &Wire);
  if (mpu_ok) {
    mpu.setAccelerometerRange(MPU6050_RANGE_4_G);
    mpu.setGyroRange(MPU6050_RANGE_500_DEG);
  }

  mlx_ok = mlx.begin(MLX_ADDR, &Wire);

  Wire.setClock(I2C_FREQ_HZ);  // re-assert 100 kHz for the MLX90614

#ifdef STREAM_WIFI
  WiFi.mode(WIFI_AP);
  WiFi.softAP(WIFI_AP_SSID, WIFI_AP_PASS);
  WiFi.setTxPower(WIFI_TX_POWER);   // C3 Super Mini: full TX power leaves the AP invisible (see config.h)
  server.begin();
#endif

  emitMetaTo(Serial);

  next_us       = micros();
  stats_last_ms = millis();
}

void loop() {
  uint32_t now = micros();
  if ((int32_t)(now - next_us) < 0) return;

  next_us += PERIOD_US;
  if ((int32_t)(micros() - next_us) > (int32_t)PERIOD_US) {
    overruns++;
    next_us = micros() + PERIOD_US;
  }

  uint32_t t_us = now;

#ifdef STREAM_WIFI
  // Accept a (re)connecting Wi-Fi client and greet it with the metadata block.
  if (!wifiClient || !wifiClient.connected()) {
    WiFiClient c = server.available();
    if (c) { wifiClient = c; wifiClient.setNoDelay(true); emitMetaTo(wifiClient); }
  }
#endif

  // --- PPG: drain the MAX30102 FIFO non-blocking, keep the most recent IR ---
  if (ppg_ok) {
    ppgSensor.check();                      // pull any new FIFO samples
    while (ppgSensor.available()) {
      ppg_ir = ppgSensor.getFIFOIR();
      ppgSensor.nextSample();
    }
  }

  int gsr = analogRead(PIN_GSR);

  float ax = NAN, ay = NAN, az = NAN;
  float gx = NAN, gy = NAN, gz = NAN;
  const float mx = NAN, my = NAN, mz = NAN; // MPU-6050 has no magnetometer
  if (mpu_ok) {
    sensors_event_t a, g, t;
    mpu.getEvent(&a, &g, &t);               // accel m/s^2, gyro rad/s
    ax = a.acceleration.x; ay = a.acceleration.y; az = a.acceleration.z;
    gx = g.gyro.x;         gy = g.gyro.y;         gz = g.gyro.z;
  }

  if (mlx_ok && (seq % TEMP_DECIM == 0)) {
    float o  = mlx.readObjectTempC();
    float am = mlx.readAmbientTempC();
    if (!isnan(o))  temp_obj = o;
    if (!isnan(am)) temp_amb = am;
  }

  int n = snprintf(line, sizeof(line) - 2,
    "%lu,%lu,%lu,%d,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f,%.2f,%.2f,%.2f,%.2f,%.2f",
    (unsigned long)t_us, (unsigned long)seq, (unsigned long)ppg_ir, gsr,
    ax, ay, az, gx, gy, gz, mx, my, mz, temp_obj, temp_amb);
  if (n < 0) n = 0;
  if (n > (int)sizeof(line) - 2) n = sizeof(line) - 2;
  line[n++] = '\n';
  if (Serial.availableForWrite() >= n) {
    Serial.write((const uint8_t *)line, n);
  } else {
    tx_dropped++;
  }
#ifdef STREAM_WIFI
  // WiFiClient::availableForWrite() always returns 0 on ESP32, so we must NOT
  // gate on it (that skipped every row). Write directly when connected.
  if (wifiClient && wifiClient.connected()) {
    wifiClient.write((const uint8_t *)line, n);
  }
#endif

  seq++;

  uint32_t ms = millis();
  if (ms - stats_last_ms >= STATS_PERIOD_MS) {
    float dt   = (ms - stats_last_ms) / 1000.0f;
    float rate = (seq - stats_last_seq) / dt;
    Serial.printf("# stats t_ms=%lu rate_hz=%.1f overruns=%lu txdrop=%lu seq=%lu\n",
                  (unsigned long)ms, rate, (unsigned long)overruns,
                  (unsigned long)tx_dropped, (unsigned long)seq);
    stats_last_ms  = ms;
    stats_last_seq = seq;
    digitalWrite(PIN_LED, !digitalRead(PIN_LED));
  }
}

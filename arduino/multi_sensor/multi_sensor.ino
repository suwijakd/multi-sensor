// ===========================================================================
// Wearable multi-sensor logger  —  ESP32-C3 Super Mini
//
//   PPG  : DFRobot SEN0203          (analog  -> ADC1)
//   GSR  : Grove GSR v1.2           (analog  -> ADC1)
//   IMU  : TDK InvenSense ICM-20948 (I2C, 9-DoF)
//   TEMP : Melexis MLX90614 (GY-906)(I2C, IR thermometer)
//
// All four are read against a single MCU timebase so the rows line up in time.
// Each tick we sample PPG + GSR + IMU; the slow temperature sensor is read on a
// decimated schedule and its last value is held. One CSV line is emitted per
// tick over native USB CDC; the PC-side script timestamps and stores it.
//
// This single sketch builds with Arduino IDE, arduino-cli, OR PlatformIO
// (platformio.ini points src_dir at this folder). See README.md.
// ===========================================================================
#include <Arduino.h>
#include <Wire.h>
#include <math.h>
#include <Adafruit_ICM20948.h>
#include <Adafruit_MLX90614.h>
#include "config.h"

Adafruit_ICM20948 icm;
Adafruit_MLX90614 mlx;

static bool icm_ok = false;
static bool mlx_ok = false;

static const uint32_t PERIOD_US  = 1000000UL / SAMPLE_RATE_HZ;
static const uint32_t TEMP_DECIM = SAMPLE_RATE_HZ / TEMP_RATE_HZ;  // ticks between temp reads

static uint32_t seq      = 0;   // monotonic sample counter (used for drop detection on PC)
static uint32_t next_us  = 0;   // next scheduled sample time
static uint32_t overruns = 0;   // count of ticks we couldn't keep up with

// Last temperature reading, held between the (slow) decimated samples.
static float temp_obj = NAN;
static float temp_amb = NAN;

// Diagnostics bookkeeping.
static uint32_t stats_last_ms  = 0;
static uint32_t stats_last_seq = 0;

static char line[256];

// Emit a metadata block. Lines starting with '#' are comments the PC ignores
// for data purposes (but prints to the console).
void emitMeta() {
  Serial.println(F("# multi-sensor wearable logger"));
  Serial.printf("# sample_rate_hz=%d temp_rate_hz=%d\n", SAMPLE_RATE_HZ, TEMP_RATE_HZ);
  Serial.printf("# icm20948=%s mlx90614=%s\n",
                icm_ok ? "ok" : "MISSING", mlx_ok ? "ok" : "MISSING");
  Serial.println(F("# units: ppg,gsr=adc_counts(0-4095) accel=m/s^2 gyro=rad/s "
                   "mag=uT temp=degC t_us=micros"));
  Serial.println(F("# columns: t_us,seq,ppg_raw,gsr_raw,ax,ay,az,gx,gy,gz,mx,my,mz,"
                   "temp_obj_c,temp_amb_c"));
}

void setup() {
  Serial.begin(115200);
  uint32_t t0 = millis();
  while (!Serial && (millis() - t0) < 2000) { delay(10); }  // wait briefly for USB host

  pinMode(PIN_LED, OUTPUT);
  digitalWrite(PIN_LED, HIGH);  // LED off (active low)

  analogReadResolution(ADC_BITS);
  analogSetAttenuation(ADC_11db);  // ~0..3.3V input range across the ADC

  // Bring up the shared I2C bus on our chosen pins FIRST. The Adafruit
  // begin_I2C() calls below re-call Wire.begin() with no args, which reuses
  // these pins once they've been set here.
  Wire.begin(PIN_SDA, PIN_SCL, I2C_FREQ_HZ);

  icm_ok = icm.begin_I2C(ICM_ADDR, &Wire);
  if (icm_ok) {
    icm.setAccelRange(ICM20948_ACCEL_RANGE_4_G);
    icm.setGyroRange(ICM20948_GYRO_RANGE_500_DPS);
  }
  mlx_ok = mlx.begin(MLX_ADDR, &Wire);

  // Re-assert 100 kHz: some library init paths bump the bus speed, which the
  // MLX90614 can't tolerate.
  Wire.setClock(I2C_FREQ_HZ);

  emitMeta();

  next_us       = micros();
  stats_last_ms = millis();
}

void loop() {
  // Fixed-rate scheduler. The signed difference handles micros() wraparound.
  uint32_t now = micros();
  if ((int32_t)(now - next_us) < 0) return;  // not time yet

  next_us += PERIOD_US;
  // If we've already blown past the *next* deadline, we fell behind: count it
  // and resync so we don't spin trying to "catch up".
  if ((int32_t)(micros() - next_us) > (int32_t)PERIOD_US) {
    overruns++;
    next_us = micros() + PERIOD_US;
  }

  uint32_t t_us = now;

  // --- fast sensors: every tick ---
  int ppg = analogRead(PIN_PPG);
  int gsr = analogRead(PIN_GSR);

  float ax = NAN, ay = NAN, az = NAN;
  float gx = NAN, gy = NAN, gz = NAN;
  float mx = NAN, my = NAN, mz = NAN;
  if (icm_ok) {
    sensors_event_t a, g, tmp, m;
    icm.getEvent(&a, &g, &tmp, &m);          // (accel, gyro, temp, mag)
    ax = a.acceleration.x; ay = a.acceleration.y; az = a.acceleration.z;
    gx = g.gyro.x;         gy = g.gyro.y;         gz = g.gyro.z;
    mx = m.magnetic.x;     my = m.magnetic.y;     mz = m.magnetic.z;
  }

  // --- slow sensor: decimated, value held in between ---
  if (mlx_ok && (seq % TEMP_DECIM == 0)) {
    float o  = mlx.readObjectTempC();
    float am = mlx.readAmbientTempC();
    if (!isnan(o))  temp_obj = o;
    if (!isnan(am)) temp_amb = am;
  }

  // One rectangular CSV row per tick.
  snprintf(line, sizeof(line),
    "%lu,%lu,%d,%d,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f,%.2f,%.2f,%.2f,%.2f,%.2f",
    (unsigned long)t_us, (unsigned long)seq, ppg, gsr,
    ax, ay, az, gx, gy, gz, mx, my, mz, temp_obj, temp_amb);
  Serial.println(line);

  seq++;

  // Periodic diagnostics + heartbeat blink.
  uint32_t ms = millis();
  if (ms - stats_last_ms >= STATS_PERIOD_MS) {
    float dt   = (ms - stats_last_ms) / 1000.0f;
    float rate = (seq - stats_last_seq) / dt;
    Serial.printf("# stats t_ms=%lu rate_hz=%.1f overruns=%lu seq=%lu\n",
                  (unsigned long)ms, rate, (unsigned long)overruns, (unsigned long)seq);
    stats_last_ms  = ms;
    stats_last_seq = seq;
    digitalWrite(PIN_LED, !digitalRead(PIN_LED));
  }
}

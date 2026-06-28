#pragma once
// ---------------------------------------------------------------------------
// ALTERNATIVE sensor set (temporary swap). Self-contained — the default
// sketch in ../multi_sensor/ is untouched.
//
//   PPG  : GY-MAX30102        (I2C 0x57)  replaces analog SEN0203
//   IMU  : GY-521 / MPU-6050  (I2C 0x68)  replaces ICM-20948 (6-DoF, no mag)
//   GSR  : Grove GSR v1.2      (analog)   unchanged
//   TEMP : MLX90614 / GY-906   (I2C 0x5A) unchanged
//
// It emits the SAME 15-column CSV as the default sketch, so pc/record.py works
// with no changes. Mapping into the existing columns:
//   * ppg_raw   <- MAX30102 IR channel (raw counts, NOT 0-4095)
//   * ax..gz    <- MPU-6050 accel (m/s^2) + gyro (rad/s)
//   * mx,my,mz  <- NaN (the MPU-6050 has no magnetometer)
// ---------------------------------------------------------------------------

// ---- Pin map (ESP32-C3 Super Mini) ----------------------------------------
// PPG is now on I2C, so the old analog PPG pin (GPIO0) is unused here.
#define PIN_GSR   1        // ADC1_CH1  <- Grove GSR analog "SIG" output

#define PIN_SDA   5        // shared I2C: MAX30102 + MPU-6050 + MLX90614
#define PIN_SCL   6
#define PIN_LED   8        // onboard LED (active LOW on most Super Minis)

// ---- I2C ------------------------------------------------------------------
// Still capped at 100 kHz for the MLX90614 (SMBus). MAX30102 + MPU-6050 are
// fine at 100 kHz. Addresses: MAX30102 0x57, MPU-6050 0x68, MLX90614 0x5A.
#define I2C_FREQ_HZ   100000UL
#define MPU_ADDR      0x68 // GY-521 default (0x69 if its AD0 pin is tied high)
#define MLX_ADDR      0x5A
// (MAX30102 address 0x57 is fixed inside the SparkFun library.)

// ---- Sampling -------------------------------------------------------------
#define SAMPLE_RATE_HZ   100   // base tick: PPG + GSR + IMU every tick
#define TEMP_RATE_HZ     2     // MLX90614 decimated read, value held
#define STATS_PERIOD_MS  5000

// ---- ADC ------------------------------------------------------------------
#define ADC_BITS   12          // ESP32-C3 ADC is 12-bit -> 0..4095

// ---- Wireless (optional) --------------------------------------------------
// Uncomment STREAM_WIFI to ALSO stream over Wi-Fi (USB keeps working too). The
// device makes its own Wi-Fi network (SoftAP); join it on the PC, then run:
//     python record.py --tcp 192.168.4.1:3333
// Power from a USB battery bank to go fully untethered. GSR stays on ADC1, which
// is unaffected by the radio. Leave commented for default USB-only behavior.
//#define STREAM_WIFI
#define WIFI_AP_SSID  "multisensor"
#define WIFI_AP_PASS  "squat12345"   // >= 8 chars; the PC uses this to join the AP
#define STREAM_PORT   3333

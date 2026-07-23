#pragma once
// ---------------------------------------------------------------------------
// Hardware + sampling configuration for the ESP32-C3 Super Mini.
// Change pins/rates here; the sketch reads everything from this file.
// ---------------------------------------------------------------------------

// ---- Pin map (ESP32-C3 Super Mini) ----------------------------------------
// PPG and GSR are ANALOG. On the C3 you must use ADC1 pins (GPIO0..GPIO4),
// because ADC2 stops working once the radio (Wi-Fi/BLE) is active.
#define PIN_PPG   0        // ADC1_CH0  <- SEN0203 PPG analog "S" output
#define PIN_GSR   1        // ADC1_CH1  <- Grove GSR analog "SIG" output

// Shared I2C bus for the two digital sensors. Avoid GPIO8/GPIO9 on the
// Super Mini (onboard LED + BOOT button, both strapping pins).
#define PIN_SDA   5
#define PIN_SCL   6

#define PIN_LED   8        // onboard LED (active LOW on most Super Minis)

// ---- I2C ------------------------------------------------------------------
// Capped at 100 kHz: the MLX90614 is SMBus and will NACK/lock up faster than
// that. The ICM-20948 is perfectly happy at 100 kHz too.
#define I2C_FREQ_HZ   100000UL
#define ICM_ADDR      0x69 // Adafruit ICM-20948 default (use 0x68 if ADR is tied low)
#define MLX_ADDR      0x5A // MLX90614 default

// ---- Sampling -------------------------------------------------------------
#define SAMPLE_RATE_HZ   100   // base tick: PPG + GSR + IMU read every tick
#define TEMP_RATE_HZ     2     // MLX90614 is slow; read it this often, hold last value
#define STATS_PERIOD_MS  5000  // cadence of the "# stats ..." diagnostics line

// ---- ADC ------------------------------------------------------------------
#define ADC_BITS   12          // ESP32-C3 ADC is 12-bit -> 0..4095

// ---- Wireless (optional) --------------------------------------------------
// Uncomment STREAM_WIFI to ALSO stream over Wi-Fi (USB keeps working too). The
// device makes its own Wi-Fi network (SoftAP); join it on the PC, then run:
//     python record.py --tcp 192.168.4.1:3333
// Power the board from a USB battery bank to go fully untethered. PPG/GSR stay
// on ADC1, which is unaffected by the radio (only ADC2 is). Leave commented for
// the default USB-only behavior.
//#define STREAM_WIFI
#define WIFI_AP_SSID  "multisensor"
#define WIFI_AP_PASS  "squat12345"   // >= 8 chars; the PC uses this to join the AP
#define STREAM_PORT   3333
// The ESP32-C3 Super Mini's weak power design can't drive the radio at full TX
// power, so the AP starts but is invisible. Lowering TX power is what actually
// makes Wi-Fi work on this board. Try WIFI_POWER_2dBm if the SSID still doesn't
// appear, or WIFI_POWER_19_5dBm on a board with a proper antenna.
#define WIFI_TX_POWER WIFI_POWER_8_5dBm

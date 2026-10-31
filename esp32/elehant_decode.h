/* Элехант: разбор BLE manufacturer data 0xFFFF (17 байт после company ID). */
#ifndef ELEHANT_DECODE_H
#define ELEHANT_DECODE_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    uint8_t kind;          /* 1 = вода, 2 = газ, 0 = неизвестно */
    uint8_t channel;       /* 01, 03, 04... */
    uint32_t serial;       /* u24 */
    uint32_t volume_0_1l;  /* сырое, 0.1 литра */
    float volume_m3;       /* volume_0_1l / 10000 */
    float temperature_c;   /* 0.01 °C */
    uint8_t battery_raw;   /* гипотеза: 0..127 */
    uint8_t flags;         /* не выяснено */
    uint8_t packet_counter;
} elehant_data_t;

/* payload — manufacturer data без company ID; len >= 17. */
int elehant_decode(const uint8_t *payload, size_t len, elehant_data_t *out);

#ifdef __cplusplus
}
#endif

#endif

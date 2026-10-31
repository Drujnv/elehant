#include "elehant_decode.h"

static int is_water(const uint8_t *d) {
    return d[2] == 0x96 && d[3] == 0x01 && d[4] == 0x02;
}
static int is_gas(const uint8_t *d) {
    return d[2] == 0x96 && d[3] == 0x01 && d[4] == 0x01;
}

int elehant_decode(const uint8_t *payload, size_t len, elehant_data_t *out) {
    if (!payload || !out || len < 17 || payload[0] != 0x80) return 0;

    out->kind = is_water(payload) ? 1 : (is_gas(payload) ? 2 : 0);
    out->channel = payload[5];
    out->serial = (uint32_t)payload[6] | ((uint32_t)payload[7] << 8) | ((uint32_t)payload[8] << 16);
    out->volume_0_1l = (uint32_t)payload[9] | ((uint32_t)payload[10] << 8) |
                       ((uint32_t)payload[11] << 16) | ((uint32_t)payload[12] << 24);
    out->volume_m3 = out->volume_0_1l / 10000.0f;
    out->temperature_c = ((uint16_t)payload[14] | ((uint16_t)payload[15] << 8)) / 100.0f;
    out->battery_raw = payload[13];
    out->flags = payload[16];
    out->packet_counter = payload[1];
    return 1;
}

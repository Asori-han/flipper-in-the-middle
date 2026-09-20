#include "checksum.h"
uint16_t ethlab_checksum(const uint8_t* data, uint16_t length) {
    uint32_t sum = 0;
    while(length > 1) {
        sum += ((uint16_t)data[0] << 8) | data[1];
        data += 2;
        length -= 2;
    }
    if(length) sum += (uint16_t)data[0] << 8;
    while(sum >> 16)
        sum = (sum & 0xFFFFU) + (sum >> 16);
    return (uint16_t)~sum;
}

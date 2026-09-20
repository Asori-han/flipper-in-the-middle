#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "../script/script_parser.h"

#define ETHLAB_SOCKET_MACRAW 0
#define ETHLAB_SOCKET_PING   1
#define ETHLAB_SOCKET_HTTP   2
#define ETHLAB_SOCKET_DHCP   3

bool w5500_hal_init(void);
void w5500_hal_deinit(void);
bool w5500_hal_chip_init(void);
bool w5500_hal_set_phy(EthLabPhyMode mode);
void w5500_hal_set_network(
    const uint8_t mac[6],
    const uint8_t ip[4],
    const uint8_t mask[4],
    const uint8_t gateway[4],
    const uint8_t dns[4]);
bool w5500_hal_link(bool* speed_100, bool* full_duplex);
bool w5500_hal_open_macraw(void);
uint16_t w5500_hal_raw_send(const uint8_t* frame, uint16_t length);
uint16_t w5500_hal_raw_receive(uint8_t* frame, uint16_t capacity);

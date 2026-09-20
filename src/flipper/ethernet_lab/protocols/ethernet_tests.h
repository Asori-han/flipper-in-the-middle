#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "../script/script_parser.h"

typedef struct {
    bool success;
    uint32_t elapsed_ms;
    uint8_t mac[6];
} EthLabArpResult;

typedef struct {
    bool success;
    uint32_t elapsed_ms;
} EthLabPingResult;

typedef struct {
    bool success;
    uint16_t status_code;
    uint32_t bytes_received;
} EthLabHttpResult;

typedef struct {
    bool success;
    uint32_t elapsed_ms;
    uint8_t ip[4];
    uint8_t mask[4];
    uint8_t gateway[4];
    uint8_t dns[4];
} EthLabDhcpResult;

bool ethlab_dhcp(
    uint32_t timeout_ms,
    volatile bool* running,
    EthLabDhcpResult* result);

bool ethlab_arp(
    const uint8_t own_mac[6],
    const uint8_t own_ip[4],
    const uint8_t target_ip[4],
    uint32_t timeout_ms,
    volatile bool* running,
    EthLabArpResult* result);
bool ethlab_ping(
    const uint8_t target_ip[4],
    uint16_t sequence,
    uint32_t timeout_ms,
    EthLabPattern pattern,
    volatile bool* running,
    EthLabPingResult* result);
bool ethlab_http_get(
    const uint8_t target_ip[4],
    uint16_t port,
    const char* path,
    uint32_t timeout_ms,
    volatile bool* running,
    EthLabHttpResult* result);

#include "ethernet_tests.h"

#include "../hal/w5500_hal.h"
#include "../utils/checksum.h"

#include <furi.h>
#include <dhcp.h>
#include <socket.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <w5500.h>

#define ETHERTYPE_ARP 0x0806U
#define ICMP_SIZE     40U

static void dhcp_timer_callback(void* context) {
    UNUSED(context);
    DHCP_time_handler();
}

bool ethlab_dhcp(
    uint32_t timeout_ms,
    volatile bool* running,
    EthLabDhcpResult* result) {
    memset(result, 0, sizeof(*result));
    uint8_t* buffer = malloc(576);
    if(!buffer) return false;

    FuriTimer* timer = furi_timer_alloc(dhcp_timer_callback, FuriTimerTypePeriodic, NULL);
    furi_timer_start(timer, 1000);
    DHCP_init(ETHLAB_SOCKET_DHCP, buffer);

    uint32_t started = furi_get_tick();
    while(furi_get_tick() - started < timeout_ms && (!running || *running)) {
        uint8_t state = DHCP_run();
        if(state == DHCP_IP_LEASED || state == DHCP_IP_ASSIGN || state == DHCP_IP_CHANGED) {
            getIPfromDHCP(result->ip);
            getSNfromDHCP(result->mask);
            getGWfromDHCP(result->gateway);
            getDNSfromDHCP(result->dns);
            result->success = true;
            break;
        }
        if(state == DHCP_FAILED) break;
        furi_delay_ms(10);
    }
    result->elapsed_ms = furi_get_tick() - started;
    DHCP_stop();
    furi_timer_stop(timer);
    furi_timer_free(timer);
    free(buffer);
    return result->success;
}

static void put_u16(uint8_t* destination, uint16_t value) {
    destination[0] = value >> 8;
    destination[1] = value & 0xFF;
}

bool ethlab_arp(
    const uint8_t own_mac[6],
    const uint8_t own_ip[4],
    const uint8_t target_ip[4],
    uint32_t timeout_ms,
    volatile bool* running,
    EthLabArpResult* result) {
    memset(result, 0, sizeof(*result));
    if(!w5500_hal_open_macraw()) return false;
    uint8_t frame[60] = {0};
    memset(frame, 0xFF, 6);
    memcpy(frame + 6, own_mac, 6);
    put_u16(frame + 12, ETHERTYPE_ARP);
    put_u16(frame + 14, 1);
    put_u16(frame + 16, 0x0800);
    frame[18] = 6;
    frame[19] = 4;
    put_u16(frame + 20, 1);
    memcpy(frame + 22, own_mac, 6);
    memcpy(frame + 28, own_ip, 4);
    memcpy(frame + 38, target_ip, 4);
    if(w5500_hal_raw_send(frame, sizeof(frame)) != sizeof(frame)) return false;

    uint32_t started = furi_get_tick();
    uint8_t received[128];
    while(furi_get_tick() - started < timeout_ms && (!running || *running)) {
        uint16_t length = w5500_hal_raw_receive(received, sizeof(received));
        if(length >= 42 && received[12] == 0x08 && received[13] == 0x06 && received[20] == 0 &&
           received[21] == 2 && memcmp(received + 28, target_ip, 4) == 0 &&
           memcmp(received + 38, own_ip, 4) == 0) {
            memcpy(result->mac, received + 22, 6);
            result->elapsed_ms = furi_get_tick() - started;
            result->success = true;
            return true;
        }
        furi_delay_ms(1);
    }
    result->elapsed_ms = furi_get_tick() - started;
    return false;
}

bool ethlab_ping(
    const uint8_t target_ip[4],
    uint16_t sequence,
    uint32_t timeout_ms,
    EthLabPattern pattern,
    volatile bool* running,
    EthLabPingResult* result) {
    memset(result, 0, sizeof(*result));
    /*
     * Keeping IPRAW open preserves the W5500 ARP resolution for the target
     * throughout the burst. Reopening it for each echo generated an ARP request
     * before every ICMP packet, so the oscilloscope always triggered on that
     * first frame.
     */
    if(getSn_SR(ETHLAB_SOCKET_PING) != SOCK_IPRAW) {
        close(ETHLAB_SOCKET_PING);
        WIZCHIP_WRITE(Sn_PROTO(ETHLAB_SOCKET_PING), 1);
        if(socket(ETHLAB_SOCKET_PING, Sn_MR_IPRAW, 1, 0) != ETHLAB_SOCKET_PING) return false;
    }
    uint8_t packet[ICMP_SIZE] = {0};
    packet[0] = 8;
    packet[4] = 0x45;
    packet[5] = 0x4C;
    put_u16(packet + 6, sequence);
    for(uint8_t index = 0; index < ICMP_SIZE - 8; index++) {
        packet[8 + index] = pattern == EthLabPatternIncrement ? index :
                            pattern == EthLabPatternFF        ? 0xFF :
                            pattern == EthLabPattern55        ? 0x55 :
                            pattern == EthLabPatternAA        ? 0xAA :
                                                                0x00;
    }
    put_u16(packet + 2, ethlab_checksum(packet, sizeof(packet)));
    if(sendto(ETHLAB_SOCKET_PING, packet, sizeof(packet), (uint8_t*)target_ip, 1) <= 0) {
        close(ETHLAB_SOCKET_PING);
        return false;
    }
    uint32_t started = furi_get_tick();
    uint8_t reply[80], from[4];
    uint16_t from_port;
    while(furi_get_tick() - started < timeout_ms && (!running || *running)) {
        if(getSn_RX_RSR(ETHLAB_SOCKET_PING)) {
            int32_t length = recvfrom(ETHLAB_SOCKET_PING, reply, sizeof(reply), from, &from_port);
            if(length >= 8 && reply[0] == 0 && reply[4] == 0x45 && reply[5] == 0x4C &&
               (((uint16_t)reply[6] << 8) | reply[7]) == sequence) {
                result->success = true;
                result->elapsed_ms = furi_get_tick() - started;
                return true;
            }
        }
        furi_delay_ms(1);
    }
    result->elapsed_ms = furi_get_tick() - started;
    close(ETHLAB_SOCKET_PING);
    return false;
}

bool ethlab_http_get(
    const uint8_t target_ip[4],
    uint16_t port,
    const char* path,
    uint32_t timeout_ms,
    volatile bool* running,
    EthLabHttpResult* result) {
    memset(result, 0, sizeof(*result));
    close(ETHLAB_SOCKET_HTTP);
    if(socket(ETHLAB_SOCKET_HTTP, Sn_MR_TCP, 49152, 0) != ETHLAB_SOCKET_HTTP) return false;
    if(connect(ETHLAB_SOCKET_HTTP, (uint8_t*)target_ip, port) != SOCK_OK) {
        close(ETHLAB_SOCKET_HTTP);
        return false;
    }
    char request[160];
    int length = snprintf(
        request,
        sizeof(request),
        "GET %s HTTP/1.0\r\nHost: %u.%u.%u.%u\r\nConnection: close\r\n\r\n",
        path,
        target_ip[0],
        target_ip[1],
        target_ip[2],
        target_ip[3]);
    if(length <= 0 || (size_t)length >= sizeof(request) ||
       send(ETHLAB_SOCKET_HTTP, (uint8_t*)request, length) != length) {
        close(ETHLAB_SOCKET_HTTP);
        return false;
    }
    uint32_t started = furi_get_tick();
    bool first_chunk = true;
    uint8_t buffer[257];
    while(furi_get_tick() - started < timeout_ms && (!running || *running)) {
        uint16_t available = getSn_RX_RSR(ETHLAB_SOCKET_HTTP);
        if(available) {
            uint16_t chunk = available >= sizeof(buffer) ? sizeof(buffer) - 1 : available;
            int32_t received = recv(ETHLAB_SOCKET_HTTP, buffer, chunk);
            if(received > 0) {
                buffer[received] = '\0';
                if(first_chunk && received >= 12 && memcmp(buffer, "HTTP/", 5) == 0) {
                    unsigned int code = 0;
                    sscanf((char*)buffer, "HTTP/%*u.%*u %u", &code);
                    result->status_code = code;
                    first_chunk = false;
                }
                result->bytes_received += received;
                started = furi_get_tick();
            }
        }
        uint8_t status = getSn_SR(ETHLAB_SOCKET_HTTP);
        if(status == SOCK_CLOSED || status == SOCK_CLOSE_WAIT) {
            result->success = result->bytes_received > 0;
            close(ETHLAB_SOCKET_HTTP);
            return result->success;
        }
        furi_delay_ms(2);
    }
    close(ETHLAB_SOCKET_HTTP);
    return false;
}

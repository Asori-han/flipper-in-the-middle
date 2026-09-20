#include "script_runner.h"

#include "../hal/w5500_hal.h"
#include "../protocols/ethernet_tests.h"

#include <furi.h>
#include <stdio.h>
#include <string.h>

typedef struct {
    uint8_t mac[6];
    uint8_t ip[4];
    uint8_t mask[4];
    uint8_t gateway[4];
    uint8_t dns[4];
    EthLabPhyMode phy;
} RunnerConfig;

static void output(EthLabLogCallback log, void* context, const char* text) {
    if(log) log(context, text);
}

static void apply_network(const RunnerConfig* config) {
    w5500_hal_set_network(config->mac, config->ip, config->mask, config->gateway, config->dns);
}

bool ethlab_script_run(
    const EthLabScript* script,
    volatile bool* running,
    EthLabLogCallback log,
    void* context) {
    RunnerConfig config = {
        .mac = {0x02, 0x00, 0x00, 0x00, 0x00, 0x01},
        .ip = {192, 168, 1, 250},
        .mask = {255, 255, 255, 0},
        .gateway = {192, 168, 1, 1},
        .dns = {192, 168, 1, 1},
        .phy = EthLabPhyAuto,
    };
    output(log, context, "W5500: init");
    if(!w5500_hal_init() || !w5500_hal_chip_init()) {
        output(log, context, "ERROR: W5500 not found");
        w5500_hal_deinit();
        return false;
    }
    apply_network(&config);
    uint16_t sequence = 1;
    bool all_ok = true;
    char line[96];

    for(size_t index = 0; index < script->count && *running; index++) {
        const EthLabCommand* command = &script->commands[index];
        switch(command->type) {
        case EthLabCommandMac:
            memcpy(config.mac, command->data.mac, 6);
            apply_network(&config);
            snprintf(line, sizeof(line), "L%u MAC configured", command->line);
            output(log, context, line);
            break;
        case EthLabCommandIp:
            memcpy(config.ip, command->data.ip, 4);
            apply_network(&config);
            output(log, context, "IP configured");
            break;
        case EthLabCommandMask:
            memcpy(config.mask, command->data.ip, 4);
            apply_network(&config);
            output(log, context, "Mask configured");
            break;
        case EthLabCommandGateway:
            memcpy(config.gateway, command->data.ip, 4);
            apply_network(&config);
            output(log, context, "Gateway configured");
            break;
        case EthLabCommandDns:
            memcpy(config.dns, command->data.ip, 4);
            apply_network(&config);
            output(log, context, "DNS configured");
            break;
        case EthLabCommandDhcp: {
            output(log, context, "DHCP: requesting lease...");
            EthLabDhcpResult result;
            bool ok = ethlab_dhcp(command->data.dhcp.timeout_ms, running, &result);
            if(ok) {
                memcpy(config.ip, result.ip, 4);
                memcpy(config.mask, result.mask, 4);
                memcpy(config.gateway, result.gateway, 4);
                memcpy(config.dns, result.dns, 4);
                snprintf(
                    line,
                    sizeof(line),
                    "DHCP: %u.%u.%u.%u gw %u.%u.%u.%u %lums",
                    result.ip[0], result.ip[1], result.ip[2], result.ip[3],
                    result.gateway[0], result.gateway[1], result.gateway[2], result.gateway[3],
                    result.elapsed_ms);
            } else {
                snprintf(line, sizeof(line), "DHCP: timeout");
            }
            output(log, context, line);
            all_ok &= ok;
            break;
        }
        case EthLabCommandPhy:
            config.phy = command->data.phy;
            w5500_hal_set_phy(config.phy);
            output(log, context, "PHY configured");
            break;
        case EthLabCommandLink: {
            output(log, context, "LINK: waiting...");
            uint32_t started = furi_get_tick();
            bool speed_100 = false, full_duplex = false, linked = false;
            while(furi_get_tick() - started < command->data.link.timeout_ms && *running) {
                if((linked = w5500_hal_link(&speed_100, &full_duplex))) break;
                furi_delay_ms(20);
            }
            if(linked)
                snprintf(
                    line,
                    sizeof(line),
                    "LINK: %uM %s",
                    speed_100 ? 100 : 10,
                    full_duplex ? "full" : "half");
            else
                snprintf(line, sizeof(line), "LINK: timeout");
            output(log, context, line);
            all_ok &= linked;
            break;
        }
        case EthLabCommandArp: {
            uint8_t attempted = 0;
            uint8_t replies = 0;
            uint32_t minimum_ms = command->data.arp.timeout_ms;
            uint32_t maximum_ms = 0;
            uint8_t resolved_mac[6] = {0};
            for(uint8_t count = 0; count < command->data.arp.count && *running; count++) {
                EthLabArpResult result;
                bool ok = ethlab_arp(
                    config.mac,
                    config.ip,
                    command->data.arp.ip,
                    command->data.arp.timeout_ms,
                    running,
                    &result);
                attempted++;
                if(ok) {
                    replies++;
                    memcpy(resolved_mac, result.mac, sizeof(resolved_mac));
                    if(result.elapsed_ms < minimum_ms) minimum_ms = result.elapsed_ms;
                    if(result.elapsed_ms > maximum_ms) maximum_ms = result.elapsed_ms;
                }
                all_ok &= ok;
                if(count + 1 < command->data.arp.count && *running) furi_delay_ms(10);
            }
            if(replies)
                snprintf(
                    line,
                    sizeof(line),
                    "ARP: %u/%u replies %02X:%02X:%02X:%02X:%02X:%02X %lu..%lums",
                    replies,
                    attempted,
                    resolved_mac[0],
                    resolved_mac[1],
                    resolved_mac[2],
                    resolved_mac[3],
                    resolved_mac[4],
                    resolved_mac[5],
                    minimum_ms,
                    maximum_ms);
            else
                snprintf(line, sizeof(line), "ARP: 0/%u replies", attempted);
            output(log, context, line);
            break;
        }
        case EthLabCommandPing: {
            uint8_t attempted = 0;
            uint8_t replies = 0;
            uint32_t minimum_ms = command->data.ping.timeout_ms;
            uint32_t maximum_ms = 0;
            for(uint8_t count = 0; count < command->data.ping.count && *running; count++) {
                EthLabPingResult result;
                bool ok = ethlab_ping(
                    command->data.ping.ip,
                    sequence++,
                    command->data.ping.timeout_ms,
                    command->data.ping.pattern,
                    running,
                    &result);
                attempted++;
                if(ok) {
                    replies++;
                    if(result.elapsed_ms < minimum_ms) minimum_ms = result.elapsed_ms;
                    if(result.elapsed_ms > maximum_ms) maximum_ms = result.elapsed_ms;
                }
                all_ok &= ok;
                if(count + 1 < command->data.ping.count && *running) furi_delay_ms(10);
            }
            if(replies)
                snprintf(
                    line,
                    sizeof(line),
                    "PING: %u/%u replies %lu..%lums",
                    replies,
                    attempted,
                    minimum_ms,
                    maximum_ms);
            else
                snprintf(line, sizeof(line), "PING: 0/%u replies", attempted);
            output(log, context, line);
            break;
        }
        case EthLabCommandHttpGet: {
            uint8_t attempted = 0;
            uint8_t replies = 0;
            uint16_t status_code = 0;
            uint32_t bytes_received = 0;
            for(uint8_t count = 0; count < command->data.http_get.count && *running; count++) {
                EthLabHttpResult result;
                bool ok = ethlab_http_get(
                    command->data.http_get.ip,
                    command->data.http_get.port,
                    command->data.http_get.path,
                    5000,
                    running,
                    &result);
                attempted++;
                if(ok) {
                    replies++;
                    status_code = result.status_code;
                    bytes_received += result.bytes_received;
                }
                all_ok &= ok;
                if(count + 1 < command->data.http_get.count && *running) furi_delay_ms(10);
            }
            if(replies)
                snprintf(
                    line,
                    sizeof(line),
                    "HTTP: %u/%u status %u, %lu bytes",
                    replies,
                    attempted,
                    status_code,
                    bytes_received);
            else
                snprintf(line, sizeof(line), "HTTP: 0/%u replies", attempted);
            output(log, context, line);
            break;
        }
        case EthLabCommandWait: {
            uint32_t waited = 0;
            while(waited < command->data.wait.duration_ms && *running) {
                uint32_t step = command->data.wait.duration_ms - waited;
                if(step > 20) step = 20;
                furi_delay_ms(step);
                waited += step;
            }
            break;
        }
        case EthLabCommandNote:
            output(log, context, command->data.note);
            break;
        }
    }
    w5500_hal_deinit();
    output(
        log, context, *running ? (all_ok ? "DONE: all passed" : "DONE: failures") : "CANCELLED");
    return all_ok && *running;
}

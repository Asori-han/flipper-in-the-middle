#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define ETHLAB_SCRIPT_MAGIC "ETHERNET-LAB/1"
#define ETHLAB_MAX_COMMANDS 64
#define ETHLAB_MAX_LINE     192
#define ETHLAB_MAX_NOTE     96
#define ETHLAB_MAX_PATH     96

typedef enum {
    EthLabCommandMac,
    EthLabCommandIp,
    EthLabCommandMask,
    EthLabCommandGateway,
    EthLabCommandDns,
    EthLabCommandDhcp,
    EthLabCommandPhy,
    EthLabCommandLink,
    EthLabCommandArp,
    EthLabCommandPing,
    EthLabCommandHttpGet,
    EthLabCommandWait,
    EthLabCommandNote,
} EthLabCommandType;

typedef enum {
    EthLabPhyAuto,
    EthLabPhy10Half,
    EthLabPhy10Full,
    EthLabPhy100Half,
    EthLabPhy100Full,
} EthLabPhyMode;

typedef enum {
    EthLabPatternIncrement,
    EthLabPattern00,
    EthLabPatternFF,
    EthLabPattern55,
    EthLabPatternAA,
} EthLabPattern;

typedef struct {
    EthLabCommandType type;
    uint16_t line;
    union {
        uint8_t mac[6];
        uint8_t ip[4];
        EthLabPhyMode phy;
        struct {
            uint32_t timeout_ms;
        } link;
        struct {
            uint32_t timeout_ms;
        } dhcp;
        struct {
            uint8_t ip[4];
            uint32_t timeout_ms;
            uint8_t count;
        } arp;
        struct {
            uint8_t ip[4];
            uint8_t count;
            uint32_t timeout_ms;
            EthLabPattern pattern;
        } ping;
        struct {
            uint8_t ip[4];
            uint16_t port;
            char path[ETHLAB_MAX_PATH + 1];
            uint8_t count;
        } http_get;
        struct {
            uint32_t duration_ms;
        } wait;
        char note[ETHLAB_MAX_NOTE + 1];
    } data;
} EthLabCommand;

typedef struct {
    EthLabCommand commands[ETHLAB_MAX_COMMANDS];
    size_t count;
} EthLabScript;

typedef struct {
    uint16_t line;
    char message[96];
} EthLabParseError;

bool ethlab_script_parse(char* text, EthLabScript* script, EthLabParseError* error);

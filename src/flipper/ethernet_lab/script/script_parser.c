#include "script_parser.h"

#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void set_error(EthLabParseError* error, uint16_t line, const char* message) {
    error->line = line;
    snprintf(error->message, sizeof(error->message), "%s", message);
}

static char* trim(char* text) {
    while(isspace((unsigned char)*text))
        text++;
    char* end = text + strlen(text);
    while(end > text && isspace((unsigned char)end[-1]))
        end--;
    *end = '\0';
    return text;
}

static bool parse_u32(const char* text, uint32_t min, uint32_t max, uint32_t* value) {
    if(!text || !isdigit((unsigned char)*text)) return false;
    char* end;
    unsigned long parsed = strtoul(text, &end, 10);
    if(*end || parsed < min || parsed > max) return false;
    *value = (uint32_t)parsed;
    return true;
}

static bool parse_ipv4(const char* text, uint8_t out[4]) {
    if(!text) return false;
    for(size_t index = 0; index < 4; index++) {
        if(!isdigit((unsigned char)*text)) return false;
        char* end;
        unsigned long octet = strtoul(text, &end, 10);
        if(octet > 255 || end == text) return false;
        out[index] = (uint8_t)octet;
        if(index < 3) {
            if(*end != '.') return false;
            text = end + 1;
        } else if(*end) {
            return false;
        }
    }
    return true;
}

static bool parse_mac(const char* text, uint8_t out[6]) {
    if(!text || strlen(text) != 17) return false;
    for(size_t index = 0; index < 17; index++) {
        if(index % 3 == 2) {
            if(text[index] != ':') return false;
        } else if(!isxdigit((unsigned char)text[index])) {
            return false;
        }
    }
    unsigned int b[6];
    if(sscanf(text, "%2x:%2x:%2x:%2x:%2x:%2x", &b[0], &b[1], &b[2], &b[3], &b[4], &b[5]) != 6)
        return false;
    for(size_t i = 0; i < 6; i++)
        out[i] = b[i];
    /* Demo identities must be unicast and locally administered. */
    return (out[0] & 0x03U) == 0x02U;
}

static char* next_token(char** cursor) {
    char* start = trim(*cursor);
    if(!*start) {
        *cursor = start;
        return NULL;
    }
    char* end = start;
    while(*end && !isspace((unsigned char)*end))
        end++;
    if(*end) *end++ = '\0';
    *cursor = end;
    return start;
}

static bool no_more(char* cursor) {
    return *trim(cursor) == '\0';
}

static bool add_command(
    EthLabScript* script,
    EthLabCommand** command,
    uint16_t line,
    EthLabParseError* error) {
    if(script->count >= ETHLAB_MAX_COMMANDS) {
        set_error(error, line, "too many commands (maximum 64)");
        return false;
    }
    *command = &script->commands[script->count++];
    memset(*command, 0, sizeof(**command));
    (*command)->line = line;
    return true;
}

static bool parse_address_command(char* cursor, EthLabCommand* command, EthLabParseError* error) {
    char* value = next_token(&cursor);
    if(!value || !no_more(cursor) || !parse_ipv4(value, command->data.ip)) {
        set_error(error, command->line, "expected one IPv4 address");
        return false;
    }
    return true;
}

static bool
    parse_line(char* line, uint16_t line_number, EthLabScript* script, EthLabParseError* error) {
    char* cursor = line;
    char* name = next_token(&cursor);
    EthLabCommand* command;
    if(!name) return true;
    if(!add_command(script, &command, line_number, error)) return false;

    if(strcmp(name, "MAC") == 0) {
        command->type = EthLabCommandMac;
        char* value = next_token(&cursor);
        if(!value || !no_more(cursor) || !parse_mac(value, command->data.mac)) {
            set_error(error, line_number, "MAC must be local unicast (example 02:00:00:00:00:01)");
            return false;
        }
    } else if(
        strcmp(name, "IP") == 0 || strcmp(name, "MASK") == 0 || strcmp(name, "GATEWAY") == 0 ||
        strcmp(name, "DNS") == 0) {
        command->type = strcmp(name, "IP") == 0      ? EthLabCommandIp :
                        strcmp(name, "MASK") == 0    ? EthLabCommandMask :
                        strcmp(name, "GATEWAY") == 0 ? EthLabCommandGateway :
                                                       EthLabCommandDns;
        if(!parse_address_command(cursor, command, error)) return false;
    } else if(strcmp(name, "DHCP") == 0) {
        command->type = EthLabCommandDhcp;
        char* timeout = next_token(&cursor);
        command->data.dhcp.timeout_ms = 15000;
        if((timeout && !parse_u32(timeout, 1000, 30000, &command->data.dhcp.timeout_ms)) ||
           !no_more(cursor)) {
            set_error(error, line_number, "DHCP timeout must be 1000..30000 ms");
            return false;
        }
    } else if(strcmp(name, "PHY") == 0) {
        command->type = EthLabCommandPhy;
        char* value = next_token(&cursor);
        if(!value || !no_more(cursor)) {
            set_error(error, line_number, "expected PHY AUTO|10_HALF|10_FULL|100_HALF|100_FULL");
            return false;
        }
        if(strcmp(value, "AUTO") == 0)
            command->data.phy = EthLabPhyAuto;
        else if(strcmp(value, "10_HALF") == 0)
            command->data.phy = EthLabPhy10Half;
        else if(strcmp(value, "10_FULL") == 0)
            command->data.phy = EthLabPhy10Full;
        else if(strcmp(value, "100_HALF") == 0)
            command->data.phy = EthLabPhy100Half;
        else if(strcmp(value, "100_FULL") == 0)
            command->data.phy = EthLabPhy100Full;
        else {
            set_error(error, line_number, "unknown PHY mode");
            return false;
        }
    } else if(strcmp(name, "LINK") == 0) {
        command->type = EthLabCommandLink;
        char* timeout = next_token(&cursor);
        command->data.link.timeout_ms = 5000;
        if((timeout && !parse_u32(timeout, 100, 10000, &command->data.link.timeout_ms)) ||
           !no_more(cursor)) {
            set_error(error, line_number, "LINK timeout must be 100..10000 ms");
            return false;
        }
    } else if(strcmp(name, "ARP") == 0) {
        command->type = EthLabCommandArp;
        char* ip = next_token(&cursor);
        char* timeout = next_token(&cursor);
        char* count = next_token(&cursor);
        uint32_t parsed_count = 1;
        command->data.arp.timeout_ms = 2000;
        if(!ip || !parse_ipv4(ip, command->data.arp.ip) ||
           (timeout && !parse_u32(timeout, 100, 10000, &command->data.arp.timeout_ms)) ||
           (count && !parse_u32(count, 1, 30, &parsed_count)) ||
           !no_more(cursor)) {
            set_error(error, line_number, "expected ARP <ip> [timeout] [count 1..30]");
            return false;
        }
        command->data.arp.count = (uint8_t)parsed_count;
    } else if(strcmp(name, "PING") == 0) {
        command->type = EthLabCommandPing;
        char* ip = next_token(&cursor);
        char* count = next_token(&cursor);
        char* timeout = next_token(&cursor);
        char* pattern = next_token(&cursor);
        uint32_t parsed_count = 1;
        command->data.ping.timeout_ms = 2000;
        command->data.ping.pattern = EthLabPatternIncrement;
        if(!ip || !parse_ipv4(ip, command->data.ping.ip) ||
           (count && !parse_u32(count, 1, 30, &parsed_count)) ||
           (timeout && !parse_u32(timeout, 100, 10000, &command->data.ping.timeout_ms))) {
            set_error(error, line_number, "expected PING <ip> [count 1..30] [timeout] [pattern]");
            return false;
        }
        command->data.ping.count = (uint8_t)parsed_count;
        if(pattern) {
            if(strcmp(pattern, "INCREMENT") == 0)
                command->data.ping.pattern = EthLabPatternIncrement;
            else if(strcmp(pattern, "00") == 0)
                command->data.ping.pattern = EthLabPattern00;
            else if(strcmp(pattern, "FF") == 0)
                command->data.ping.pattern = EthLabPatternFF;
            else if(strcmp(pattern, "55") == 0)
                command->data.ping.pattern = EthLabPattern55;
            else if(strcmp(pattern, "AA") == 0)
                command->data.ping.pattern = EthLabPatternAA;
            else {
                set_error(error, line_number, "pattern must be INCREMENT, 00, FF, 55 or AA");
                return false;
            }
        }
        if(!no_more(cursor)) {
            set_error(error, line_number, "too many PING arguments");
            return false;
        }
    } else if(strcmp(name, "HTTP_GET") == 0) {
        command->type = EthLabCommandHttpGet;
        char* ip = next_token(&cursor);
        char* port = next_token(&cursor);
        char* path = next_token(&cursor);
        char* count = next_token(&cursor);
        uint32_t parsed_port, parsed_count = 1;
        if(!ip || !port || !path || !parse_ipv4(ip, command->data.http_get.ip) ||
           !parse_u32(port, 1, 65535, &parsed_port) ||
           (count && !parse_u32(count, 1, 30, &parsed_count)) || !no_more(cursor) || path[0] != '/' ||
           strlen(path) > ETHLAB_MAX_PATH) {
            set_error(error, line_number, "expected HTTP_GET <ip> <port> </path> [count 1..30]");
            return false;
        }
        command->data.http_get.port = (uint16_t)parsed_port;
        command->data.http_get.count = (uint8_t)parsed_count;
        strcpy(command->data.http_get.path, path);
    } else if(strcmp(name, "WAIT") == 0) {
        command->type = EthLabCommandWait;
        char* duration = next_token(&cursor);
        if(!duration || !parse_u32(duration, 1, 30000, &command->data.wait.duration_ms) ||
           !no_more(cursor)) {
            set_error(error, line_number, "WAIT duration must be 1..30000 ms");
            return false;
        }
    } else if(strcmp(name, "NOTE") == 0) {
        command->type = EthLabCommandNote;
        char* note = trim(cursor);
        if(!*note || strlen(note) > ETHLAB_MAX_NOTE) {
            set_error(error, line_number, "NOTE text must be 1..96 characters");
            return false;
        }
        strcpy(command->data.note, note);
    } else {
        script->count--;
        set_error(error, line_number, "unknown command");
        return false;
    }
    return true;
}

bool ethlab_script_parse(char* text, EthLabScript* script, EthLabParseError* error) {
    if(!text || !script || !error) return false;
    memset(script, 0, sizeof(*script));
    memset(error, 0, sizeof(*error));
    bool header_seen = false;
    uint16_t line_number = 0;
    char* cursor = text;
    while(cursor) {
        line_number++;
        char* next = strchr(cursor, '\n');
        if(next) *next++ = '\0';
        if(strlen(cursor) > ETHLAB_MAX_LINE) {
            set_error(error, line_number, "line is longer than 192 characters");
            return false;
        }
        char* line = trim(cursor);
        char* comment = strchr(line, '#');
        if(comment) *comment = '\0';
        line = trim(line);
        if(*line) {
            if(!header_seen) {
                if(strcmp(line, ETHLAB_SCRIPT_MAGIC) != 0) {
                    set_error(error, line_number, "missing ETHERNET-LAB/1 header");
                    return false;
                }
                header_seen = true;
            } else if(!parse_line(line, line_number, script, error)) {
                return false;
            }
        }
        cursor = next;
    }
    if(!header_seen) {
        set_error(error, 1, "empty script");
        return false;
    }
    if(script->count == 0) {
        set_error(error, line_number, "script contains no commands");
        return false;
    }
    return true;
}

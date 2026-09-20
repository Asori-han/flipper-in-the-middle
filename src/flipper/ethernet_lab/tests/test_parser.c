#include "../script/script_parser.h"

#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void parses_complete_demo(void) {
    char input[] = "# lead comment\nETHERNET-LAB/1\nMAC 02:00:00:00:00:01\nIP 192.168.1.2\n"
                   "PHY 10_FULL\nLINK\nDHCP 15000\nARP 192.168.1.1 1000 3\n"
                   "PING 192.168.1.1 2 2000 AA\nHTTP_GET 192.168.1.1 80 /status 4\n"
                   "WAIT 20\nNOTE ready for capture\n";
    EthLabScript script;
    EthLabParseError error;
    assert(ethlab_script_parse(input, &script, &error));
    assert(script.count == 10);
    assert(script.commands[0].type == EthLabCommandMac);
    assert(script.commands[2].data.phy == EthLabPhy10Full);
    assert(script.commands[4].type == EthLabCommandDhcp);
    assert(script.commands[4].data.dhcp.timeout_ms == 15000);
    assert(script.commands[5].data.arp.count == 3);
    assert(script.commands[6].data.ping.count == 2);
    assert(script.commands[6].data.ping.pattern == EthLabPatternAA);
    assert(strcmp(script.commands[7].data.http_get.path, "/status") == 0);
    assert(script.commands[7].data.http_get.count == 4);
}

static void rejects_invalid_input(void) {
    EthLabScript script;
    EthLabParseError error;
    char missing_header[] = "PING 192.168.1.1\n";
    assert(!ethlab_script_parse(missing_header, &script, &error));
    assert(error.line == 1);

    char vendor_mac[] = "ETHERNET-LAB/1\nMAC 00:11:22:33:44:55\n";
    assert(!ethlab_script_parse(vendor_mac, &script, &error));
    assert(error.line == 2);

    char short_mac[] = "ETHERNET-LAB/1\nMAC 2:00:00:00:00:01\n";
    assert(!ethlab_script_parse(short_mac, &script, &error));

    char signed_ip[] = "ETHERNET-LAB/1\nIP +192.168.1.2\n";
    assert(!ethlab_script_parse(signed_ip, &script, &error));

    char unsafe_count[] = "ETHERNET-LAB/1\nPING 192.168.1.1 31\n";
    assert(!ethlab_script_parse(unsafe_count, &script, &error));

    char trailing[] = "ETHERNET-LAB/1\nARP 192.168.1.1 500 extra\n";
    assert(!ethlab_script_parse(trailing, &script, &error));

    char short_dhcp[] = "ETHERNET-LAB/1\nDHCP 999\n";
    assert(!ethlab_script_parse(short_dhcp, &script, &error));
}

static void parses_example_file(const char* path, size_t expected_commands) {
    FILE* file = fopen(path, "rb");
    assert(file);
    assert(fseek(file, 0, SEEK_END) == 0);
    long size = ftell(file);
    assert(size >= 0);
    rewind(file);
    char* input = malloc((size_t)size + 1);
    assert(input);
    assert(fread(input, 1, (size_t)size, file) == (size_t)size);
    input[size] = '\0';
    fclose(file);

    EthLabScript script;
    EthLabParseError error;
    assert(ethlab_script_parse(input, &script, &error));
    assert(script.count == expected_commands);
    free(input);
}

int main(void) {
    parses_complete_demo();
    rejects_invalid_input();
    parses_example_file("examples/oscilloscope-burst.eth", 61);
    parses_example_file("examples/scope-increment.eth", 47);
    parses_example_file("examples/scope-00.eth", 47);
    parses_example_file("examples/scope-ff.eth", 47);
    parses_example_file("examples/scope-55.eth", 47);
    parses_example_file("examples/scope-aa.eth", 47);
    parses_example_file("examples/scope-arp.eth", 27);
    parses_example_file("examples/scope-http.eth", 17);
    puts("parser tests passed");
    return 0;
}

#include "w5500_hal.h"

#include <furi.h>
#include <furi_hal.h>
#include <socket.h>
#include <string.h>
#include <w5500.h>
#include <wizchip_conf.h>

static const GpioPin gpio_cs = {.port = GPIOA, .pin = LL_GPIO_PIN_4};
static const GpioPin gpio_reset = {.port = GPIOC, .pin = LL_GPIO_PIN_3};
static bool initialized;

static void chip_select(void) {
    furi_hal_gpio_write(&gpio_cs, false);
}
static void chip_deselect(void) {
    furi_hal_gpio_write(&gpio_cs, true);
}
static uint8_t spi_read(void) {
    uint8_t value = 0;
    furi_hal_spi_bus_rx(&furi_hal_spi_bus_handle_external, &value, 1, 1000);
    return value;
}
static void spi_write(uint8_t value) {
    furi_hal_spi_bus_tx(&furi_hal_spi_bus_handle_external, &value, 1, 1000);
}
static void spi_read_burst(uint8_t* data, uint16_t length) {
    furi_hal_spi_bus_rx(&furi_hal_spi_bus_handle_external, data, length, 1000);
}
static void spi_write_burst(uint8_t* data, uint16_t length) {
    furi_hal_spi_bus_tx(&furi_hal_spi_bus_handle_external, data, length, 1000);
}

bool w5500_hal_init(void) {
    if(initialized) return true;
    furi_hal_spi_bus_handle_init(&furi_hal_spi_bus_handle_external);
    furi_hal_spi_acquire(&furi_hal_spi_bus_handle_external);
    furi_hal_gpio_write(&gpio_cs, true);
    furi_hal_gpio_init(&gpio_cs, GpioModeOutputPushPull, GpioPullNo, GpioSpeedVeryHigh);
    furi_hal_gpio_write(&gpio_reset, false);
    furi_hal_gpio_init(&gpio_reset, GpioModeOutputPushPull, GpioPullNo, GpioSpeedVeryHigh);
    furi_hal_gpio_write(&gpio_reset, true);
    furi_delay_ms(100);
    reg_wizchip_spi_cbfunc(spi_read, spi_write);
    reg_wizchip_spiburst_cbfunc(spi_read_burst, spi_write_burst);
    reg_wizchip_cs_cbfunc(chip_select, chip_deselect);
    initialized = true;
    return getVERSIONR() == 0x04;
}

void w5500_hal_deinit(void) {
    if(!initialized) return;
    for(uint8_t socket_number = 0; socket_number < 8; socket_number++)
        close(socket_number);
    furi_hal_spi_release(&furi_hal_spi_bus_handle_external);
    furi_hal_spi_bus_handle_deinit(&furi_hal_spi_bus_handle_external);
    furi_hal_gpio_init(&gpio_cs, GpioModeAnalog, GpioPullNo, GpioSpeedLow);
    furi_hal_gpio_init(&gpio_reset, GpioModeAnalog, GpioPullNo, GpioSpeedLow);
    initialized = false;
}

bool w5500_hal_chip_init(void) {
    uint8_t sizes[2][8] = {{8, 2, 2, 1, 1, 1, 1, 0}, {8, 2, 2, 1, 1, 1, 1, 0}};
    return ctlwizchip(CW_INIT_WIZCHIP, sizes) == 0;
}

bool w5500_hal_set_phy(EthLabPhyMode mode) {
    wiz_PhyConf config = {
        .by = PHY_CONFBY_SW,
        .mode = mode == EthLabPhyAuto ? PHY_MODE_AUTONEGO : PHY_MODE_MANUAL,
        .speed = (mode == EthLabPhy100Half || mode == EthLabPhy100Full) ? PHY_SPEED_100 :
                                                                          PHY_SPEED_10,
        .duplex = (mode == EthLabPhy10Full || mode == EthLabPhy100Full) ? PHY_DUPLEX_FULL :
                                                                          PHY_DUPLEX_HALF,
    };
    wizphy_setphyconf(&config);
    return true;
}

void w5500_hal_set_network(
    const uint8_t mac[6],
    const uint8_t ip[4],
    const uint8_t mask[4],
    const uint8_t gateway[4],
    const uint8_t dns[4]) {
    wiz_NetInfo info = {.dhcp = NETINFO_STATIC};
    memcpy(info.mac, mac, 6);
    memcpy(info.ip, ip, 4);
    memcpy(info.sn, mask, 4);
    memcpy(info.gw, gateway, 4);
    memcpy(info.dns, dns, 4);
    wizchip_setnetinfo(&info);
}

bool w5500_hal_link(bool* speed_100, bool* full_duplex) {
    uint8_t value = getPHYCFGR();
    if(speed_100) *speed_100 = (value & 0x02U) != 0;
    if(full_duplex) *full_duplex = (value & 0x04U) != 0;
    return (value & 0x01U) != 0;
}

bool w5500_hal_open_macraw(void) {
    close(ETHLAB_SOCKET_MACRAW);
    return socket(ETHLAB_SOCKET_MACRAW, Sn_MR_MACRAW, 1, 0) == ETHLAB_SOCKET_MACRAW;
}

uint16_t w5500_hal_raw_send(const uint8_t* frame, uint16_t length) {
    uint8_t unused[4] = {0};
    int32_t result = sendto(ETHLAB_SOCKET_MACRAW, (uint8_t*)frame, length, unused, 1);
    return result > 0 ? (uint16_t)result : 0;
}

uint16_t w5500_hal_raw_receive(uint8_t* frame, uint16_t capacity) {
    if(getSn_RX_RSR(ETHLAB_SOCKET_MACRAW) == 0) return 0;
    uint8_t unused[4];
    uint16_t port;
    int32_t result = recvfrom(ETHLAB_SOCKET_MACRAW, frame, capacity, unused, &port);
    return result > 0 ? (uint16_t)result : 0;
}

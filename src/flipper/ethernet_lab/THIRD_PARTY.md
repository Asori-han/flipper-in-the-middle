# Third-party software

Ethernet Lab contains a focused adaptation of the W5500 integration from
[`dok2d/fz-W5500-lan-analyse`](https://github.com/dok2d/fz-W5500-lan-analyse),
revision `8c892cafe9570b9d900d3f157ce5d0ef28298b8e`. That project is distributed
under the MIT license (copyright 2025). Its SPI/W5500 approach and ICMP
implementation informed `hal/w5500_hal.c` and `protocols/ethernet_tests.c`.
Its complete license notice is preserved in
`licenses/fz-W5500-lan-analyse.LICENSE`.

The bundled `lib/ioLibrary_Driver` files come from the official
[`WIZnet ioLibrary`](https://github.com/Wiznet/ioLibrary_Driver), through that
upstream project. The original license is preserved in
`lib/ioLibrary_Driver/license.txt`.

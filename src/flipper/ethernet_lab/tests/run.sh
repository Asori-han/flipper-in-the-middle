#!/usr/bin/env sh
set -eu
APP_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$APP_DIR"
cc -std=c11 -Wall -Wextra -Werror -pedantic \
  tests/test_parser.c script/script_parser.c -o /tmp/ethernet_lab_parser_test
/tmp/ethernet_lab_parser_test

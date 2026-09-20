#pragma once

#include "script_parser.h"

typedef void (*EthLabLogCallback)(void* context, const char* message);

bool ethlab_script_run(
    const EthLabScript* script,
    volatile bool* running,
    EthLabLogCallback log,
    void* context);

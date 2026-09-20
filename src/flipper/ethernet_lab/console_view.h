#pragma once

#include <gui/view.h>

typedef struct EthLabConsoleView EthLabConsoleView;
EthLabConsoleView* ethlab_console_alloc(void);
void ethlab_console_free(EthLabConsoleView* console);
View* ethlab_console_get_view(EthLabConsoleView* console);
void ethlab_console_print(EthLabConsoleView* console, const char* text);

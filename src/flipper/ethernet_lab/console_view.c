#include "console_view.h"

#include <furi.h>
#include <gui/canvas.h>
#include <input/input.h>
#include <string.h>

#define CONSOLE_LINES   6
#define CONSOLE_COLUMNS 21

struct EthLabConsoleView {
    View* view;
};

typedef struct {
    char lines[CONSOLE_LINES][CONSOLE_COLUMNS + 1];
} ConsoleModel;

static void draw(Canvas* canvas, void* model_ptr) {
    ConsoleModel* model = model_ptr;
    canvas_set_font(canvas, FontSecondary);
    for(size_t index = 0; index < CONSOLE_LINES; index++)
        canvas_draw_str(canvas, 1, 10 + index * 10, model->lines[index]);
}

EthLabConsoleView* ethlab_console_alloc(void) {
    EthLabConsoleView* console = malloc(sizeof(*console));
    console->view = view_alloc();
    view_allocate_model(console->view, ViewModelTypeLocking, sizeof(ConsoleModel));
    view_set_draw_callback(console->view, draw);
    return console;
}

void ethlab_console_free(EthLabConsoleView* console) {
    view_free(console->view);
    free(console);
}

View* ethlab_console_get_view(EthLabConsoleView* console) {
    return console->view;
}

void ethlab_console_print(EthLabConsoleView* console, const char* text) {
    with_view_model(
        console->view,
        ConsoleModel * model,
        {
            for(size_t index = 0; index < CONSOLE_LINES - 1; index++)
                memcpy(model->lines[index], model->lines[index + 1], CONSOLE_COLUMNS + 1);
            snprintf(
                model->lines[CONSOLE_LINES - 1],
                CONSOLE_COLUMNS + 1,
                "%.*s",
                CONSOLE_COLUMNS,
                text);
        },
        true);
}

#include "console_view.h"
#include "script/script_parser.h"
#include "script/script_runner.h"

#include <dialogs/dialogs.h>
#include <furi.h>
#include <gui/gui.h>
#include <gui/view_dispatcher.h>
#include <storage/storage.h>
#include <string.h>

#define SCRIPT_MAX_BYTES (16U * 1024U)
#define DEFAULT_SCRIPT   APP_DATA_PATH("demo.eth")
#define SCRIPT_FOLDER    APP_DATA_PATH("")
#define LAST_RUN_LOG     APP_DATA_PATH("last_run.log")

static const char default_script[] = "ETHERNET-LAB/1\n"
                                     "# Edit these addresses for the demo network.\n"
                                     "MAC 02:00:00:00:00:01\n"
                                     "PHY AUTO\n"
                                     "NOTE Preparing capture\n"
                                     "WAIT 2000\n"
                                     "NOTE Checking negotiated link\n"
                                     "LINK 5000\n"
                                     "WAIT 2000\n"
                                     "NOTE Obtaining IPv4 configuration\n"
                                     "DHCP 15000\n"
                                     "WAIT 2000\n"
                                     "ARP 192.168.7.1 2000\n"
                                     "PING 192.168.7.1 1 2000 INCREMENT\n"
                                     "WAIT 2000\n"
                                     "PING 192.168.7.1 1 2000 00\n"
                                     "WAIT 2000\n"
                                     "PING 192.168.7.1 1 2000 FF\n"
                                     "WAIT 2000\n"
                                     "PING 192.168.7.1 1 2000 55\n"
                                     "WAIT 2000\n"
                                     "PING 192.168.7.1 1 2000 AA\n"
                                     "WAIT 2000\n"
                                     "HTTP_GET 192.168.7.1 80 /\n";

typedef struct {
    Gui* gui;
    ViewDispatcher* dispatcher;
    EthLabConsoleView* console;
    FuriThread* worker;
    EthLabScript* script;
    FuriString* script_path;
    File* log_file;
    volatile bool running;
} EthLabApp;

static void write_default_script(Storage* storage) {
    File* file = storage_file_alloc(storage);
    if(!storage_file_open(file, DEFAULT_SCRIPT, FSAM_READ, FSOM_OPEN_EXISTING)) {
        storage_file_close(file);
        if(storage_file_open(file, DEFAULT_SCRIPT, FSAM_WRITE, FSOM_CREATE_ALWAYS))
            storage_file_write(file, default_script, sizeof(default_script) - 1);
    }
    storage_file_close(file);
    storage_file_free(file);
}

static char* load_script(Storage* storage, const char* path, char* error, size_t error_size) {
    File* file = storage_file_alloc(storage);
    char* text = NULL;
    if(!storage_file_open(file, path, FSAM_READ, FSOM_OPEN_EXISTING)) {
        snprintf(error, error_size, "Cannot open script");
    } else {
        uint64_t size = storage_file_size(file);
        if(size == 0 || size > SCRIPT_MAX_BYTES) {
            snprintf(error, error_size, "File must be 1..16 KiB");
        } else {
            text = malloc((size_t)size + 1);
            if(storage_file_read(file, text, size) != size) {
                free(text);
                text = NULL;
                snprintf(error, error_size, "Cannot read script");
            } else {
                text[size] = '\0';
            }
        }
    }
    storage_file_close(file);
    storage_file_free(file);
    return text;
}

static void worker_log(void* context, const char* message) {
    EthLabApp* app = context;
    ethlab_console_print(app->console, message);
    if(app->log_file) {
        storage_file_write(app->log_file, message, strlen(message));
        storage_file_write(app->log_file, "\n", 1);
        storage_file_sync(app->log_file);
    }
}

static int32_t worker_entry(void* context) {
    EthLabApp* app = context;
    Storage* storage = furi_record_open(RECORD_STORAGE);
    app->log_file = storage_file_alloc(storage);
    if(storage_file_open(app->log_file, LAST_RUN_LOG, FSAM_WRITE, FSOM_CREATE_ALWAYS)) {
        const char* header = "ETHERNET-LAB RESULT/1\nScript: ";
        storage_file_write(app->log_file, header, strlen(header));
        storage_file_write(
            app->log_file,
            furi_string_get_cstr(app->script_path),
            furi_string_size(app->script_path));
        storage_file_write(app->log_file, "\n", 1);
    } else {
        storage_file_free(app->log_file);
        app->log_file = NULL;
        ethlab_console_print(app->console, "WARN: log unavailable");
    }
    ethlab_script_run(app->script, &app->running, worker_log, app);
    if(app->log_file) {
        storage_file_close(app->log_file);
        storage_file_free(app->log_file);
        app->log_file = NULL;
    }
    furi_record_close(RECORD_STORAGE);
    return 0;
}

static uint32_t previous_view(void* context) {
    EthLabApp* app = context;
    app->running = false;
    return VIEW_NONE;
}

int32_t ethernet_lab_app(void* argument) {
    Storage* storage = furi_record_open(RECORD_STORAGE);
    write_default_script(storage);
    FuriString* path = furi_string_alloc_set(DEFAULT_SCRIPT);
    bool selected = false;
    if(argument && strlen(argument)) {
        furi_string_set(path, (const char*)argument);
        selected = true;
    } else {
        DialogsFileBrowserOptions options;
        dialog_file_browser_set_basic_options(&options, ".eth", NULL);
        options.base_path = SCRIPT_FOLDER;
        options.skip_assets = true;
        DialogsApp* dialogs = furi_record_open(RECORD_DIALOGS);
        selected = dialog_file_browser_show(dialogs, path, path, &options);
        furi_record_close(RECORD_DIALOGS);
    }
    if(!selected) {
        furi_string_free(path);
        furi_record_close(RECORD_STORAGE);
        return 0;
    }

    char load_error[96] = {0};
    char* text = load_script(storage, furi_string_get_cstr(path), load_error, sizeof(load_error));
    furi_record_close(RECORD_STORAGE);

    EthLabApp* app = malloc(sizeof(*app));
    memset(app, 0, sizeof(*app));
    app->script = malloc(sizeof(*app->script));
    app->script_path = furi_string_alloc_set(path);
    furi_string_free(path);
    app->console = ethlab_console_alloc();
    app->dispatcher = view_dispatcher_alloc();
    app->gui = furi_record_open(RECORD_GUI);
    view_dispatcher_attach_to_gui(app->dispatcher, app->gui, ViewDispatcherTypeFullscreen);
    view_dispatcher_add_view(app->dispatcher, 0, ethlab_console_get_view(app->console));
    view_set_context(ethlab_console_get_view(app->console), app);
    view_set_previous_callback(ethlab_console_get_view(app->console), previous_view);
    view_dispatcher_switch_to_view(app->dispatcher, 0);

    if(!text) {
        ethlab_console_print(app->console, "SCRIPT ERROR");
        ethlab_console_print(app->console, load_error);
    } else {
        EthLabParseError parse_error;
        if(!ethlab_script_parse(text, app->script, &parse_error)) {
            char message[96];
            ethlab_console_print(app->console, "SCRIPT ERROR");
            snprintf(
                message, sizeof(message), "Line %u: %.75s", parse_error.line, parse_error.message);
            ethlab_console_print(app->console, message);
        } else {
            ethlab_console_print(app->console, "Script validated");
            app->running = true;
            app->worker = furi_thread_alloc_ex("EthLabWorker", 4096, worker_entry, app);
            furi_thread_start(app->worker);
        }
        free(text);
    }

    view_dispatcher_run(app->dispatcher);
    app->running = false;
    if(app->worker) {
        furi_thread_join(app->worker);
        furi_thread_free(app->worker);
    }
    view_dispatcher_remove_view(app->dispatcher, 0);
    view_dispatcher_free(app->dispatcher);
    ethlab_console_free(app->console);
    furi_record_close(RECORD_GUI);
    furi_string_free(app->script_path);
    free(app->script);
    free(app);
    return 0;
}

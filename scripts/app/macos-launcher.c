// Orchard.app's executable: start Orchard with the Python inside the app, and say why if it stops without opening.
// It is compiled, not a script, so macOS credits the app with the folders it reads, asks to allow Desktop and
// Documents, and remembers the answer. Python runs as its child from Contents/MacOS, so its window is this app's.
#include <fcntl.h>
#include <libgen.h>
#include <limits.h>
#include <mach-o/dyld.h>
#include <spawn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>

#define TAIL_LINES 15
#define TAIL_BYTES 4096

extern char **environ;

// The last lines of the log, for the alert.
static void tail(const char *log, char *text, size_t size) {
    text[0] = '\0';
    FILE *file = fopen(log, "r");
    if (!file) return;
    fseek(file, 0, SEEK_END);
    long length = ftell(file);
    long start = length > TAIL_BYTES ? length - TAIL_BYTES : 0;
    fseek(file, start, SEEK_SET);
    size_t read = fread(text, 1, size - 1, file);
    fclose(file);
    text[read] = '\0';
    int lines = 0;
    for (char *end = text + read; end > text; end--) {
        if (end[-1] == '\n' && end != text + read && ++lines == TAIL_LINES) {
            memmove(text, end, strlen(end) + 1);
            return;
        }
    }
}

int main(int argc, char **argv) {
    char executable[PATH_MAX], python[PATH_MAX], logs[PATH_MAX], log[PATH_MAX];
    uint32_t size = sizeof executable;
    const char *home = getenv("HOME");
    if (_NSGetExecutablePath(executable, &size) != 0 || !home) return 1;
    snprintf(python, sizeof python, "%s/python", dirname(executable));
    snprintf(logs, sizeof logs, "%s/Library/Logs", home);
    mkdir(logs, 0755);
    snprintf(log, sizeof log, "%s/Orchard.log", logs);

    char *arguments[argc + 7];
    char *fixed[] = {python, "-I", "-B", "-m", "server.api", "--window"};
    int count = sizeof fixed / sizeof *fixed;
    memcpy(arguments, fixed, sizeof fixed);
    for (int i = 1; i < argc; i++) arguments[count++] = argv[i];
    arguments[count] = NULL;

    posix_spawn_file_actions_t output;
    posix_spawn_file_actions_init(&output);
    posix_spawn_file_actions_addopen(&output, STDOUT_FILENO, log, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    posix_spawn_file_actions_adddup2(&output, STDOUT_FILENO, STDERR_FILENO);
    pid_t child;
    int status = 1;
    if (posix_spawn(&child, python, &output, NULL, arguments, environ) == 0) waitpid(child, &status, 0);
    if (WIFEXITED(status) && WEXITSTATUS(status) == 0) return 0;

    char end[TAIL_BYTES], message[PATH_MAX + TAIL_BYTES];
    tail(log, end, sizeof end);
    snprintf(message, sizeof message, "The end of its log, %s:\n\n%s", log, end);
    char *alert[] = {"osascript", "-e", "on run argv", "-e", "display alert \"Orchard stopped\" message (item 1 of argv) as critical",
                     "-e", "end run", message, NULL};
    // Not waited for, so whatever started this sees it stop, even before the alert is closed.
    posix_spawn(&child, "/usr/bin/osascript", NULL, NULL, alert, environ);
    return 1;
}

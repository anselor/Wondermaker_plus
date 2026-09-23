/* Keep the vendor touchscreen's physical-head operations unambiguous when
 * openACE owns the virtual T<n> namespace.  With no live `openace` Klipper
 * object, every command and the stock resume path remain untouched.
 */
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <ctype.h>
#include <dlfcn.h>
#include <elf.h>
#include <errno.h>
#include <netinet/in.h>
#include <pthread.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>

#define FNV_INIT UINT64_C(0xcbf29ce484222325)
#define NOP UINT32_C(0xd503201f)

struct profile {
    const char *version;
    off_t file_size;
    uint64_t file_hash;
    uintptr_t resume_prepare;
    uintptr_t run_gcode;
};

static const struct profile profiles[] = {
    {"1.1.08", 61340144, UINT64_C(0x3872f8647e4366ae), 0x51a73c, 0x61425c},
    {"1.1.12", 61340216, UINT64_C(0xcef6a2287ca04bc8), 0x51a7b4, 0x61434c},
};

static uint64_t fingerprint(uint64_t hash, const void *data, size_t size)
{
    const unsigned char *p = data;
    for (size_t i = 0; i < size; i++) hash = (hash ^ p[i]) * UINT64_C(0x100000001b3);
    return hash;
}

static const struct profile *identify(FILE *f)
{
    Elf64_Ehdr eh;
    struct stat st;
    if (fstat(fileno(f), &st) || fread(&eh, sizeof eh, 1, f) != 1 ||
        memcmp(eh.e_ident, ELFMAG, SELFMAG) || eh.e_ident[EI_CLASS] != ELFCLASS64 ||
        eh.e_ident[EI_DATA] != ELFDATA2LSB || eh.e_type != ET_EXEC ||
        eh.e_machine != EM_AARCH64) return NULL;
    rewind(f);
    unsigned char buf[65536];
    uint64_t hash = FNV_INIT;
    size_t n;
    while ((n = fread(buf, 1, sizeof buf, f))) hash = fingerprint(hash, buf, n);
    if (ferror(f)) return NULL;
    for (size_t i = 0; i < sizeof profiles / sizeof profiles[0]; i++)
        if (st.st_size == profiles[i].file_size && hash == profiles[i].file_hash)
            return &profiles[i];
    return NULL;
}

static int response_has_openace(const char *response)
{
    const char *body = strstr(response, "\r\n\r\n");
    return body && strstr(body + 4, "\"openace\"") != NULL;
}

/* Rewrite only complete, simple M104/M109 commands with physical T0..T3.
 * Unknown parameters are passed through rather than silently discarded.
 */
static int rewrite_physical_heater(const char *input, char *output, size_t size)
{
    char copy[512];
    if (!input || strlen(input) >= sizeof copy) return 0;
    strcpy(copy, input);
    char *save = NULL, *word = strtok_r(copy, " \t\r\n", &save);
    if (!word || (strcasecmp(word, "M104") && strcasecmp(word, "M109"))) return 0;
    int wait = !strcasecmp(word, "M109"), tool = -1, have_temp = 0;
    double temp = 0.;
    while ((word = strtok_r(NULL, " \t\r\n", &save))) {
        if (!word[0] || !word[1]) return 0;
        char key = (char)toupper((unsigned char)word[0]);
        char *end = NULL;
        if (key == 'T') {
            long value = strtol(word + 1, &end, 10);
            if (*end || value < 0 || value > 3) return 0;
            tool = (int)value;
        } else if (key == 'S') {
            temp = strtod(word + 1, &end);
            if (*end) return 0;
            have_temp = 1;
        } else {
            return 0;
        }
    }
    if (tool < 0 || !have_temp) return 0;
    char heater[16];
    snprintf(heater, sizeof heater, tool ? "extruder%d" : "extruder", tool);
    int n = snprintf(output, size,
        "SET_HEATER_TEMPERATURE HEATER=%s TARGET=%.10g", heater, temp);
    if (wait && temp > 0 && n > 0 && (size_t)n < size)
        n += snprintf(output + n, size - (size_t)n,
            "\nTEMPERATURE_WAIT SENSOR=%s MINIMUM=%.10g MAXIMUM=%.10g",
            heater, temp - 2.5, temp + 2.5);
    return n > 0 && (size_t)n < size;
}

#ifdef WMP_OPENACE_TEST
int wmp_response_has_openace(const char *response) { return response_has_openace(response); }
int wmp_rewrite_physical_heater(const char *in, char *out, size_t n)
{ return rewrite_physical_heater(in, out, n); }
#else

static pthread_mutex_t state_lock = PTHREAD_MUTEX_INITIALIZER;
static struct timespec checked_at;
static int cached_openace;
static void (*original_resume)(void);
static void (*original_run_gcode)(void *);
static const char *(*string_data)(const void *);
static void (*string_construct)(void *);
static void *(*string_assign)(void *, const char *);
static void (*string_destroy)(void *);

static void logmsg(const char *message)
{
    FILE *f = fopen("/tmp/wmp_openace_compat.log", "a");
    if (f) { fprintf(f, "[pid %d] %s\n", (int)getpid(), message); fclose(f); }
}

static int query_openace(void)
{
    int fd = socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);
    if (fd < 0) return 0;
    struct timeval timeout = {.tv_sec = 0, .tv_usec = 250000};
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof timeout);
    setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof timeout);
    struct sockaddr_in address = {
        .sin_family = AF_INET, .sin_port = htons(7125),
        .sin_addr.s_addr = htonl(INADDR_LOOPBACK),
    };
    if (connect(fd, (struct sockaddr *)&address, sizeof address)) { close(fd); return 0; }
    static const char request[] =
        "GET /printer/objects/list HTTP/1.0\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n";
    if (send(fd, request, sizeof request - 1, MSG_NOSIGNAL) != sizeof request - 1) {
        close(fd); return 0;
    }
    char response[65536];
    size_t used = 0;
    ssize_t got;
    while (used + 1 < sizeof response &&
           (got = recv(fd, response + used, sizeof response - used - 1, 0)) > 0)
        used += (size_t)got;
    close(fd);
    response[used] = 0;
    return response_has_openace(response);
}

static int openace_active(void)
{
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    pthread_mutex_lock(&state_lock);
    if (!checked_at.tv_sec || now.tv_sec - checked_at.tv_sec >= 2) {
        cached_openace = query_openace();
        checked_at = now;
    }
    int active = cached_openace;
    pthread_mutex_unlock(&state_lock);
    return active;
}

static void send_text(const char *text)
{
    /* libstdc++'s current string object is 32 bytes on this target.  Use the
     * client's constructors/accessors instead of encoding its layout here. */
    union { max_align_t align; unsigned char bytes[32]; } value;
    string_construct(value.bytes);
    string_assign(value.bytes, text);
    original_run_gcode(value.bytes);
    string_destroy(value.bytes);
}

static void run_gcode(void *command)
{
    const char *text = string_data(command);
    char rewritten[256];
    if (openace_active() && rewrite_physical_heater(text, rewritten, sizeof rewritten)) {
        send_text(rewritten);
        return;
    }
    original_run_gcode(command);
}

static void resume_prepare(void)
{
    if (!openace_active()) {
        original_resume();
        return;
    }
    logmsg("openace detected: screen Resume sent directly to Klipper");
    send_text("RESUME");
}

static int loaded_matches(FILE *f, uintptr_t address, size_t size)
{
    unsigned char *original = malloc(size);
    if (!original) return 0;
    int ok = !fseeko(f, address - 0x400000, SEEK_SET) &&
             fread(original, size, 1, f) == 1 &&
             !memcmp(original, (const void *)address, size);
    free(original);
    return ok;
}

static int protect(uintptr_t address, size_t length, int flags)
{
    long page = sysconf(_SC_PAGESIZE);
    if (page <= 0) return -1;
    uintptr_t start = address & ~((uintptr_t)page - 1);
    uintptr_t end = (address + length + page - 1) & ~((uintptr_t)page - 1);
    return mprotect((void *)start, end - start, flags);
}

static void write_jump(void *destination, uintptr_t target)
{
    const uint32_t instructions[2] = {0x58000050U, 0xd61f0200U};
    memcpy(destination, instructions, sizeof instructions);
    memcpy((char *)destination + 8, &target, sizeof target);
}

static void *make_trampoline(uintptr_t address)
{
    void *code = mmap(NULL, 32, PROT_READ | PROT_WRITE,
                      MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (code == MAP_FAILED) return NULL;
    memcpy(code, (const void *)address, 16);
    write_jump((char *)code + 16, address + 16);
    __builtin___clear_cache(code, (char *)code + 32);
    if (mprotect(code, 32, PROT_READ | PROT_EXEC)) { munmap(code, 32); return NULL; }
    return code;
}

__attribute__((constructor))
static void initialize(void)
{
    char exe[512];
    ssize_t n = readlink("/proc/self/exe", exe, sizeof exe - 1);
    if (n <= 0 || n == sizeof exe - 1) return;
    exe[n] = 0;
    const char *base = strrchr(exe, '/');
    if (strcmp(base ? base + 1 : exe, "client")) return;
    if (getenv("WMP_OPENACE_COMPAT_DISABLE")) { logmsg("disabled by environment"); return; }
    FILE *f = fopen("/proc/self/exe", "rb");
    if (!f) return;
    const struct profile *p = identify(f);
    int recognized = p && loaded_matches(f, p->resume_prepare, 3128) &&
        loaded_matches(f, p->run_gcode, 404);
    fclose(f);
    if (!recognized) { logmsg("guard failed: unrecognized or modified client; not patching"); return; }

    string_data = dlsym(RTLD_DEFAULT,
        "_ZNKSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEE5c_strEv");
    string_construct = dlsym(RTLD_DEFAULT,
        "_ZNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEC1Ev");
    string_assign = dlsym(RTLD_DEFAULT,
        "_ZNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEaSEPKc");
    string_destroy = dlsym(RTLD_DEFAULT,
        "_ZNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEED1Ev");
    if (!string_data || !string_construct || !string_assign || !string_destroy) {
        logmsg("std::string methods unavailable; not patching"); return;
    }

    original_resume = make_trampoline(p->resume_prepare);
    original_run_gcode = make_trampoline(p->run_gcode);
    if (!original_resume || !original_run_gcode) {
        logmsg("trampoline creation failed; not patching"); return;
    }
    uintptr_t addresses[] = {p->resume_prepare, p->run_gcode};
    for (size_t i = 0; i < 2; i++)
        if (protect(addresses[i], 16, PROT_READ | PROT_WRITE | PROT_EXEC)) {
            logmsg("mprotect failed; not patching"); return;
        }
    write_jump((void *)p->resume_prepare, (uintptr_t)resume_prepare);
    write_jump((void *)p->run_gcode, (uintptr_t)run_gcode);
    for (size_t i = 0; i < 2; i++) {
        __builtin___clear_cache((char *)addresses[i], (char *)addresses[i] + 16);
        if (protect(addresses[i], 16, PROT_READ | PROT_EXEC))
            logmsg("warning: could not restore page permissions");
    }
    char message[128];
    snprintf(message, sizeof message,
        "client %s: openace-gated Resume and physical heater routing installed", p->version);
    logmsg(message);
}
#endif

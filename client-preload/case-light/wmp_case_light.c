/* Share Klipper's saved light preference with the stock screen and wake path.
 * Automatic light policy lives in wmp_case_light.py. At startup only, repair
 * a missing/input GPIO using the factory OFF initializer before delegating it.
 * Original setters still initialize the vendor GPIO and provide manual fallback.
 *
 * Also wakes a sleeping screen when the door is opened. See door_wake_poll().
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <ctype.h>
#include <stdatomic.h>
#include <arpa/inet.h>
#include <elf.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/input.h>
#include <pthread.h>
#include <pwd.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <unistd.h>

#define FNV_INIT UINT64_C(0xcbf29ce484222325)
struct profile {
    const char *version;
    off_t file_size;
    uint64_t file_hash;
    uintptr_t low, high, run_gcode, get_value, brightness;
};
static const struct profile profiles[] = {
    {"1.1.08", 61340144, UINT64_C(0x3872f8647e4366ae), 0x624bd0, 0x624d94, 0x61425c, 0x624f58, 0x552f8c},
    {"1.1.12", 61340216, UINT64_C(0xcef6a2287ca04bc8), 0x624f28, 0x6250ec, 0x61434c, 0x6252b0, 0x55307c},
    {"1.1.13", 61340216, UINT64_C(0x3ed764ac9cdaa82d), 0x624f14, 0x6250d8, 0x614338, 0x62529c, 0x553068},
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
    if (fstat(fileno(f), &st) ||
        fread(&eh, sizeof eh, 1, f) != 1 || memcmp(eh.e_ident, ELFMAG, SELFMAG) ||
        eh.e_ident[EI_CLASS] != ELFCLASS64 || eh.e_ident[EI_DATA] != ELFDATA2LSB ||
        eh.e_type != ET_EXEC || eh.e_machine != EM_AARCH64) return NULL;
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


static const char *preference_command(int enabled)
{
    return enabled ? "SET_PIN PIN=case_light VALUE=1" : "SET_PIN PIN=case_light VALUE=0";
}

#ifndef WMP_CASE_LIGHT_TEST
static int (*original_low)(void), (*original_high)(void), (*original_get)(void);
static void (*original_brightness)(unsigned int);
static unsigned char *screen_led_on;
static atomic_int cached_preference = -1;
static int refresh_preference(void);
static void (*run_gcode)(void *);
static void (*string_construct)(void *), (*string_destroy)(void *);
static void *(*string_assign)(void *, const char *);

static void logmsg(const char *message)
{
    FILE *f = fopen("/tmp/wmp_case-light.log", "a");
    if (f) { fprintf(f, "[pid %d] %s\n", (int)getpid(), message); fclose(f); }
}

static int grant_gpio(const char *path, uid_t owner)
{
    int fd = open(path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (fd < 0) return -1;
    struct stat metadata = {0};
    int result = fstat(fd, &metadata);
    if (!result && !S_ISREG(metadata.st_mode)) result = -1;
    if (!result && metadata.st_uid != owner) result = fchown(fd, owner, (gid_t)-1);
    mode_t mode = (metadata.st_mode & 0777) | S_IRUSR | S_IWUSR;
    if (!result && (metadata.st_mode & 0777) != mode) result = fchmod(fd, mode);
    close(fd);
    return result;
}

/* Door-open screen wake.
 *
 * The vendor configuration reports two door switches as gcode_button
 * Door_button1 and Door_button2: PRESSED while closed, RELEASED while open.
 * The worker reads them twice a second. When either changes from closed to
 * open while the backlight is off, it sends one touch to the top-left corner
 * of the panel. A sleeping screen is covered by the screen program's own
 * full-screen wake layer, so that touch wakes the screen and reaches no
 * control. An open door sends nothing further, and the screen sleeps again
 * after its usual delay.
 */
#define TOUCH_DEVICE "/dev/input/event0"
#define BACKLIGHT_VALUE "/sys/class/backlight/backlight/brightness"
#define WAKE_X 2
#define WAKE_Y 2
#define DOOR_QUERY "GET /printer/objects/query?gcode_button%20Door_button1" \
    "&gcode_button%20Door_button2 HTTP/1.0\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n"

/* Bit n is set while door switch n+1 is open. -1: no switch state available. */
static int parse_doors(const char *response)
{
    static const char *const names[] = {"\"gcode_button Door_button1\"",
                                        "\"gcode_button Door_button2\""};
    int open = 0, found = 0;
    for (size_t i = 0; i < sizeof names / sizeof names[0]; i++) {
        const char *value = strstr(response, names[i]);
        if (!value || !(value = strstr(value, "\"state\"")) || !(value = strchr(value, ':')))
            continue;
        for (value++; isspace((unsigned char)*value); value++) {}
        if (!strncmp(value, "\"RELEASED\"", 10)) open |= 1 << i;
        else if (strncmp(value, "\"PRESSED\"", 9)) continue;
        found = 1;
    }
    return found ? open : -1;
}

/* True once for each change from closed to open. The first reading, and the
 * first reading after the switches were unavailable, only set the baseline.
 */
static int door_opened(int doors, int *last)
{
    int previous = *last;
    *last = doors;
    return doors >= 0 && previous >= 0 && (doors & ~previous);
}

static int backlight_off(const char *path)
{
    int fd = open(path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (fd < 0) return 0;
    char text[16] = {0};
    ssize_t count;
    do { count = read(fd, text, sizeof text - 1); } while (count < 0 && errno == EINTR);
    close(fd);
    return count > 0 && text[0] == '0' && (text[1] == '\n' || !text[1]);
}

static int send_events(int fd, const struct input_event *events, size_t count)
{
    const char *data = (const char *)events;
    size_t size = count * sizeof *events, sent = 0;
    while (sent < size) {
        ssize_t n = write(fd, data + sent, size - sent);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) return -1;
        sent += (size_t)n;
    }
    return 0;
}

static int touch_corner(const char *device)
{
    static int tracking = 20000;
    int fd = open(device, O_WRONLY | O_CLOEXEC | O_NOFOLLOW);
    if (fd < 0) return -1;
    tracking = tracking % 60000 + 1;
    /* evdev drops unchanged ABS values, so move both axes off the target
     * before the contact reports it.
     */
    const struct input_event prime[] = {
        {.type = EV_ABS, .code = ABS_X, .value = WAKE_X ^ 1},
        {.type = EV_ABS, .code = ABS_Y, .value = WAKE_Y ^ 1},
        {.type = EV_SYN, .code = SYN_REPORT}};
    const struct input_event down[] = {
        {.type = EV_ABS, .code = ABS_MT_SLOT},
        {.type = EV_ABS, .code = ABS_MT_TRACKING_ID, .value = tracking},
        {.type = EV_ABS, .code = ABS_MT_POSITION_X, .value = WAKE_X},
        {.type = EV_ABS, .code = ABS_MT_POSITION_Y, .value = WAKE_Y},
        {.type = EV_ABS, .code = ABS_MT_TOUCH_MAJOR, .value = 30},
        {.type = EV_KEY, .code = BTN_TOUCH, .value = 1},
        {.type = EV_ABS, .code = ABS_X, .value = WAKE_X},
        {.type = EV_ABS, .code = ABS_Y, .value = WAKE_Y},
        {.type = EV_SYN, .code = SYN_REPORT}};
    const struct input_event up[] = {
        {.type = EV_ABS, .code = ABS_MT_SLOT},
        {.type = EV_ABS, .code = ABS_MT_TRACKING_ID, .value = -1},
        {.type = EV_KEY, .code = BTN_TOUCH},
        {.type = EV_SYN, .code = SYN_REPORT}};
    int result = send_events(fd, prime, sizeof prime / sizeof prime[0]);
    if (!result) result = send_events(fd, down, sizeof down / sizeof down[0]);
    if (!result) {
        usleep(80000);
        result = send_events(fd, up, sizeof up / sizeof up[0]);
    }
    close(fd);
    return result;
}

static int moonraker_request(const char *, size_t, char *, size_t);
static int door_wake_enabled;

static void door_wake_poll(void)
{
    static int last = -1;
    char response[2048];
    if (!door_wake_enabled) return;
    int doors = moonraker_request(DOOR_QUERY, sizeof DOOR_QUERY - 1, response, sizeof response)
        ? -1 : parse_doors(response);
    if (!door_opened(doors, &last) || !backlight_off(BACKLIGHT_VALUE)) return;
    logmsg(touch_corner(TOUCH_DEVICE) ? "door opened: screen wake touch failed"
                                      : "door opened: screen wake touch sent");
}

static uid_t gpio_owner;
static int initialize_gpio_output(const char *direction_path)
{
    int fd = open(direction_path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (fd < 0) return errno == ENOENT ? original_low() : -1;
    char direction[8] = {0};
    ssize_t count;
    do { count = read(fd, direction, sizeof direction - 1); }
    while (count < 0 && errno == EINTR);
    close(fd);
    /* Preserve an already initialized output and its current level. A cold
     * export defaults to input, which the unprivileged policy cannot repair.
     * Call the original setter, not light_low(): initialization is not a new
     * user preference and must never persist OFF over the saved choice.
     */
    if (count == 4 && !memcmp(direction, "out\n", 4)) return 0;
    if (count == 3 && !memcmp(direction, "in\n", 3)) return original_low();
    return -1;
}

static void *gpio_permissions(void *unused)
{
    (void)unused;
    /* Sysfs permissions disappear if the vendor exports the GPIO again. Only
     * this value attribute is delegated; direction/export and other pins stay
     * root-owned. Open without following links and preserve unrelated bits.
     */
    for (;;) {
        grant_gpio("/sys/class/gpio/gpio76/value", gpio_owner);
        refresh_preference();
        door_wake_poll();
        usleep(500000);
    }
    return NULL;
}

static int moonraker_request(const char *request, size_t length,
                             char *response, size_t size)
{
    int fd = socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);
    if (fd < 0) return -1;
    struct timeval timeout = {.tv_sec = 0, .tv_usec = 250000};
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof timeout);
    setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof timeout);
    struct sockaddr_in address = {.sin_family = AF_INET, .sin_port = htons(7125),
                                 .sin_addr.s_addr = htonl(INADDR_LOOPBACK)};
    if (connect(fd, (struct sockaddr *)&address, sizeof address)) { close(fd); return -1; }
    size_t sent = 0, used = 0;
    while (sent < length) {
        ssize_t n = send(fd, request + sent, length - sent, MSG_NOSIGNAL);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) { close(fd); return -1; }
        sent += (size_t)n;
    }
    while (used + 1 < size) {
        ssize_t n = recv(fd, response + used, size - used - 1, 0);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) break;
        used += (size_t)n;
    }
    close(fd); response[used] = 0;
    if ((strncmp(response, "HTTP/1.1 200 ", 13) && strncmp(response, "HTTP/1.0 200 ", 13))
        || !strstr(response, "\"result\"")) return -1;
    return 0;
}

static int request_policy(const char *action, const char *body)
{
    char request[512], response[2048];
    int length = snprintf(request, sizeof request,
        "POST /printer/wmp_case_light/%s HTTP/1.0\r\nHost: 127.0.0.1\r\n"
        "Content-Type: application/json\r\nContent-Length: %zu\r\nConnection: close\r\n\r\n%s",
        action, strlen(body), body);
    if (moonraker_request(request, (size_t)length, response, sizeof response)) return -1;
    const char *value = strstr(response, "\"enabled\"");
    if (!value || !(value = strchr(value, ':'))) return -1;
    for (value++; isspace((unsigned char)*value); value++) {}
    int enabled;
    if (!strncmp(value, "true", 4)) enabled = 1;
    else if (!strncmp(value, "false", 5)) enabled = 0;
    else return -1;
    atomic_store(&cached_preference, enabled);
    return enabled;
}

static int refresh_preference(void) { return request_policy("status", "{}"); }
static int post_preference(int enabled)
{
    char body[32];
    snprintf(body, sizeof body, "{\"enabled\":%d}", !!enabled);
    return request_policy("set", body) >= 0;
}
static int (*wake_policy)(void);
static int notify_wake(void) { return request_policy("wake", "{}"); }

static int read_light_value(const char *path)
{
    /* The factory getter exports a missing GPIO without configuring output.
     * A status read must not create that partially initialized hardware state.
     */
    int fd = open(path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (fd < 0) return 0;
    char value = 0;
    ssize_t count;
    do { count = read(fd, &value, 1); } while (count < 0 && errno == EINTR);
    close(fd);
    return count == 1 && value == '1';
}

static int light_value(void)
{
    int enabled = atomic_load(&cached_preference);
    return enabled < 0 ? read_light_value("/sys/class/gpio/gpio76/value") : enabled;
}

static void screen_brightness(unsigned int value)
{
    if (value) {
        int enabled = wake_policy();
        if (enabled >= 0) *screen_led_on = (unsigned char)enabled;
    }
    original_brightness(value);
}

static int (*direct_preference)(int) = post_preference;

static void send_preference(int enabled)
{
    if (direct_preference(enabled)) return;
    union { max_align_t align; unsigned char bytes[32]; } value;
    string_construct(value.bytes);
    string_assign(value.bytes, preference_command(enabled));
    run_gcode(value.bytes);
    string_destroy(value.bytes);
}

static int light_low(void)
{
    int result = original_low();
    send_preference(0);
    return result;
}

static int light_high(void)
{
    int result = original_high();
    send_preference(1);
    return result;
}

static void write_jump(void *destination, uintptr_t target)
{
    const uint32_t instructions[2] = {0x58000050U, 0xd61f0200U};
    memcpy(destination, instructions, sizeof instructions);
    memcpy((char *)destination + 8, &target, sizeof target);
}

static int loaded_matches(FILE *f, uintptr_t address, size_t size)
{
    unsigned char original[512];
    if (size > sizeof original || fseeko(f, address - 0x400000, SEEK_SET) ||
        fread(original, size, 1, f) != 1) return 0;
    return !memcmp(original, (const void *)address, size);
}

static int protect(uintptr_t address, size_t length, int flags)
{
    long page = sysconf(_SC_PAGESIZE);
    if (page <= 0) return -1;
    uintptr_t start = address & ~((uintptr_t)page - 1);
    uintptr_t end = (address + length + page - 1) & ~((uintptr_t)page - 1);
    return mprotect((void *)start, end - start, flags);
}


static void install_jumps(const uintptr_t *addresses, const uintptr_t *targets, size_t count)
{
    /* Several hooks share one code page. Finish every write before restoring
     * any page to read/execute, or a later write would fault on that page.
     */
    for (size_t i = 0; i < count; i++)
        write_jump((void *)addresses[i], targets[i]);
    for (size_t i = 0; i < count; i++) {
        __builtin___clear_cache((char *)addresses[i], (char *)(addresses[i] + 16));
        if (protect(addresses[i], 16, PROT_READ | PROT_EXEC))
            logmsg("Warning: could not restore code permissions");
    }
}


static void *make_trampoline(uintptr_t address)
{
    void *code = mmap(NULL, 32, PROT_READ | PROT_WRITE,
                      MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (code == MAP_FAILED) return NULL;
    /* All reviewed hooks start with position-independent instructions. */
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
    if (getenv("WMP_CASE_LIGHT_DISABLE")) { logmsg("disabled by WMP_CASE_LIGHT_DISABLE"); return; }
    FILE *f = fopen("/proc/self/exe", "rb");
    if (!f) return;
    const struct profile *p = identify(f);
    int recognized = p && loaded_matches(f, p->low, 452) && loaded_matches(f, p->high, 452)
        && loaded_matches(f, p->get_value, 16) && loaded_matches(f, p->brightness, 16);
    fclose(f);
    if (!recognized) { logmsg("Patch skipped: unsupported or modified screen client"); return; }
    const struct passwd *user = getpwnam("t13dp");
    if (!user) { logmsg("Patch skipped: stock Klipper user t13dp is unavailable"); return; }
    gpio_owner = user->pw_uid;
    string_construct = dlsym(RTLD_DEFAULT,
        "_ZNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEC1Ev");
    string_assign = dlsym(RTLD_DEFAULT,
        "_ZNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEaSEPKc");
    string_destroy = dlsym(RTLD_DEFAULT,
        "_ZNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEED1Ev");
    if (!string_construct || !string_assign || !string_destroy) {
        logmsg("Patch skipped: required screen string functions unavailable"); return;
    }
    /* Calling the entry also composes with openace-compat's sender hook. */
    run_gcode = (void *)p->run_gcode;
    const uintptr_t addresses[] = {p->low, p->high, p->get_value, p->brightness};
    const uintptr_t targets[] = {(uintptr_t)light_low, (uintptr_t)light_high,
                                 (uintptr_t)light_value, (uintptr_t)screen_brightness};
    void *trampolines[4] = {0};
    size_t count = sizeof addresses / sizeof addresses[0];
    for (size_t i = 0; i < count; i++) {
        trampolines[i] = make_trampoline(addresses[i]);
        if (!trampolines[i]) goto failed;
    }
    for (size_t i = 0; i < count; i++)
        if (protect(addresses[i], 16, PROT_READ | PROT_WRITE | PROT_EXEC)) goto failed;
    original_low = trampolines[0]; original_high = trampolines[1];
    original_get = trampolines[2]; original_brightness = trampolines[3];
    /* The reviewed UI caches the LED button in this bool on all three builds.
     * Only the UI thread writes it; the worker shares an atomic preference.
     */
    screen_led_on = (void *)0x386ce2c;
    wake_policy = notify_wake;
    door_wake_enabled = !getenv("WMP_DOOR_WAKE_DISABLE");
    install_jumps(addresses, targets, count);
    if (initialize_gpio_output("/sys/class/gpio/gpio76/direction"))
        logmsg("GPIO76 output initialization failed; automatic light control is unconfirmed");
    char message[128];
    snprintf(message, sizeof message, "client %s: case-light preference display and wake hooks active", p->version);
    logmsg(message);
    pthread_t worker;
    if (pthread_create(&worker, NULL, gpio_permissions, NULL))
        logmsg("GPIO76 permission monitor failed to start; Klipper light access is unconfirmed");
    else
        pthread_detach(worker);
    return;
failed:
    for (size_t i = 0; i < count; i++) {
        protect(addresses[i], 16, PROT_READ | PROT_EXEC);
        if (trampolines[i]) munmap(trampolines[i], 32);
    }
    logmsg("Patch skipped: could not prepare screen hooks");
}
#endif

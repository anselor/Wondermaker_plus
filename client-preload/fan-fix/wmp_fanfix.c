/* Bound automatic air-filter requests at their source in reviewed clients.
 * Manual UI/slicer controls remain intact. No tmt1.ini or Klipper fan changes.
 * See docs/firmware-1.1.12.md for the latest reviewed addresses and policy.
 */
#define _GNU_SOURCE
#include <elf.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

#define FNV_INIT UINT64_C(0xcbf29ce484222325)

struct profile {
    const char *version;
    off_t file_size;
    uint64_t file_hash;
    uintptr_t material_check, parse_air_fan, redundant_off, set_air_fan;
};
static const struct profile profiles[] = {
    {"1.1.08", 61340144, UINT64_C(0x3872f8647e4366ae),
     0x61a8cc, 0x638488, 0x6385c8, 0x53fe54},
    {"1.1.12", 61340216, UINT64_C(0xcef6a2287ca04bc8),
     0x61a9bc, 0x6387f0, 0x638930, 0x53ff44},
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

/* Only known terminal print states re-arm. Pause, missing state, host shutdown
 * and reconnect do not. Consume the allowance BEFORE sending, including when
 * the fan is already running. A later manual OFF must not be fought by polling.
 */
static int should_start(atomic_int *spent, int terminal, int printing,
                        int ready, int eligible, float reported_speed)
{
    if (terminal && ready) { atomic_store(spent, 0); return 0; }
    if (!ready) { atomic_store(spent, 1); return 0; }
    if (!printing || !eligible) return 0;
    int expected = 0;
    if (!atomic_compare_exchange_strong(spent, &expected, 1)) return 0;
    return reported_speed == 0.0f;
}

/* Explicit touchscreen requests during a print take precedence even if they
 * arrive before the first automatic check (or before switching to ABS).
 */
static void note_explicit_request(atomic_int *spent, int active_print)
{
    if (active_print) atomic_store(spent, 1);
}

static void write_jump(void *destination, uintptr_t target)
{
    const uint32_t instructions[2] = {0x58000050U, 0xd61f0200U};
    memcpy(destination, instructions, sizeof instructions);
    memcpy((char *)destination + 8, &target, sizeof target);
}

#ifndef WMP_FANFIX_TEST
static atomic_int spent;
static pthread_mutex_t dispatch_lock = PTHREAD_MUTEX_INITIALIZER;
static void (*original_set_speed)(int);
static void logmsg(const char *message)
{
    FILE *f = fopen("/tmp/wmp_fanfix.log", "a");
    if (f) { fprintf(f, "[pid %d] %s\n", (int)getpid(), message); fclose(f); }
}

/* Use the client's own std::string comparison; do not reproduce C++ layout.
 * Fixed addresses are used only after the complete ELF and loaded code match.
 */
static bool string_is(uintptr_t address, const char *text)
{
    bool (*equal)(const void *, const char *) = (void *)0x4b3b94;
    return equal((const void *)address, text);
}

static void explicit_fan_speed(int speed)
{
    pthread_mutex_lock(&dispatch_lock);
    note_explicit_request(&spent, string_is(0xe645338, "printing") ||
                                  string_is(0xe645338, "paused"));
    original_set_speed(speed);
    pthread_mutex_unlock(&dispatch_lock);
}

static void material_check(void)
{
    pthread_mutex_lock(&dispatch_lock);
    int printing = string_is(0xe645338, "printing");
    int terminal = string_is(0xe645338, "complete") || string_is(0xe645338, "cancelled") ||
                   string_is(0xe645338, "error") || string_is(0xe645338, "standby");
    int ready = string_is(0xe645170, "ready");
    unsigned tool = *(const unsigned *)0xe64570c;
    unsigned count = *(const unsigned *)0x385c260;
    int eligible = 0;
    if (printing && ready && tool < count && tool < 4 && *(const unsigned char *)0x386ea51) {
        unsigned material = *(const unsigned char *)((uintptr_t)0x384d078 + tool * 8 + 1);
        /* The reviewed materials_str array contains 18 std::strings. */
        eligible = material < 18 && string_is(0x38624a8 + material * 32, "ABS");
    }
    if (should_start(&spent, terminal, printing, ready, eligible, *(const float *)0xe645894)) {
        original_set_speed(100);
        logmsg("automatic ABS filter-on requested; no retry during this print");
    }
    pthread_mutex_unlock(&dispatch_lock);
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

__attribute__((constructor))
static void initialize(void)
{
    if (getenv("WMP_FANFIX_DISABLE")) { logmsg("disabled by WMP_FANFIX_DISABLE"); return; }
    FILE *f = fopen("/proc/self/exe", "rb");
    if (!f) return;
    const struct profile *p = identify(f);
    int recognized = p && loaded_matches(f, p->material_check, 436) &&
        loaded_matches(f, p->parse_air_fan, 396) && loaded_matches(f, p->set_air_fan, 192) &&
        loaded_matches(f, 0x4b3b94, 48);
    fclose(f);
    if (!recognized) { logmsg("guard failed: unrecognized or modified client; not patching"); return; }
    /* The guarded sender starts with four position-independent instructions:
     * stp x29,x30,[sp,#-112]!; mov x29,sp; str x19,[sp,#16]; str w0,[sp,#44].
     * Preserve them in a trampoline, followed by a jump to the untouched body.
     */
    void *trampoline = mmap(NULL, 32, PROT_READ | PROT_WRITE,
                            MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (trampoline == MAP_FAILED) { logmsg("mmap failed; not patching"); return; }
    memcpy(trampoline, (const void *)p->set_air_fan, 16);
    write_jump((char *)trampoline + 16, p->set_air_fan + 16);
    __builtin___clear_cache(trampoline, (char *)trampoline + 32);
    if (mprotect(trampoline, 32, PROT_READ | PROT_EXEC)) {
        munmap(trampoline, 32); logmsg("trampoline mprotect failed; not patching"); return;
    }
    original_set_speed = trampoline;
    const uintptr_t addresses[] = {p->material_check, p->redundant_off, p->set_air_fan};
    const size_t lengths[] = {16, 4, 16};
    size_t writable = 0;
    for (; writable < 3; writable++) {
        if (protect(addresses[writable], lengths[writable], PROT_READ | PROT_WRITE | PROT_EXEC)) {
            for (size_t j = 0; j < writable; j++)
                if (protect(addresses[j], lengths[j], PROT_READ | PROT_EXEC))
                    logmsg("warning: could not restore page permissions");
            munmap(trampoline, 32); logmsg("mprotect failed; not patching"); return;
        }
    }
    /* Constructors run before the vendor's timer/callback threads start. */
    write_jump((void *)p->material_check, (uintptr_t)material_check);
    write_jump((void *)p->set_air_fan, (uintptr_t)explicit_fan_speed);
    *(volatile uint32_t *)p->redundant_off = 0xd503201fU;
    for (size_t i = 0; i < 3; i++) {
        __builtin___clear_cache((char *)addresses[i], (char *)(addresses[i] + lengths[i]));
        if (protect(addresses[i], lengths[i], PROT_READ | PROT_EXEC))
            logmsg("warning: could not restore page permissions");
    }
    char message[128];
    snprintf(message, sizeof message, "client %s: automatic ABS request bounded; redundant status OFF removed", p->version);
    logmsg(message);
}
#endif

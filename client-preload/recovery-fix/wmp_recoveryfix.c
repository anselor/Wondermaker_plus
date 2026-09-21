/* Reviewed-client checkpoint coordinates: G-code XYZ, not compensated toolhead XYZ.
 * Guarded in-memory edits only. A hash-bound sidecar identifies new records;
 * unmarked or changed legacy records cannot start automatic recovery.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <elf.h>
#include <fcntl.h>
#include <limits.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

#define FNV_INIT UINT64_C(0xcbf29ce484222325)
#define FORMAT "WMP-GCODE-XYZ-1"

struct profile {
    const char *version;
    off_t file_size;
    uint64_t file_hash;
    uintptr_t writer, loader, start, send_gcode;
    size_t start_size;
};
static const struct profile profiles[] = {
    {"1.1.08", 61340144, UINT64_C(0x3872f8647e4366ae),
     0x62f4bc, 0x62c2a8, 0x62d5d8, 0x61425c, 0x1918},
    {"1.1.12", 61340216, UINT64_C(0xcef6a2287ca04bc8),
     0x62f824, 0x62c600, 0x62d930, 0x61434c, 0x1928},
};
static const struct profile *active_profile;

static uint64_t fingerprint(uint64_t hash, const void *data, size_t size)
{
    const unsigned char *p = data;
    for (size_t i = 0; i < size; i++) hash = (hash ^ p[i]) * UINT64_C(0x100000001b3);
    return hash;
}

static int file_hash(const char *path, uint64_t *hash)
{
    FILE *f = fopen(path, "rb");
    if (!f) return 0;
    unsigned char buf[65536]; size_t n, total = 0;
    *hash = FNV_INIT;
    while ((n = fread(buf, 1, sizeof buf, f))) {
        *hash = fingerprint(*hash, buf, n); total += n;
    }
    int ok = !ferror(f) && total > 0;
    fclose(f); return ok;
}

static int marker_path(const char *path, char *out, size_t size)
{
    int n = snprintf(out, size, "%s.wmp-coordinates", path);
    return n > 0 && (size_t)n < size;
}

static int verify_record(const char *path, uint64_t *hash)
{
    char name[PATH_MAX], format[64], extra;
    unsigned long long recorded;
    if (!marker_path(path, name, sizeof name) || !file_hash(path, hash)) return 0;
    FILE *f = fopen(name, "r");
    if (!f) return 0;
    int fields = fscanf(f, "%63s %llx %c", format, &recorded, &extra);
    fclose(f);
    return fields == 2 && !strcmp(format, FORMAT) && recorded == *hash;
}

/* Bind the format to the entire record, so a later stock writer, truncation,
 * partial write or stale sidecar fails closed. Publish only after data fsync.
 * A crash before sidecar publication may lose the newest checkpoint, never
 * silently reinterpret it. A/B selection remains the vendor's responsibility.
 */
static int stamp_record(const char *path)
{
    char name[PATH_MAX], temp[PATH_MAX]; uint64_t hash;
    if (!marker_path(path, name, sizeof name)) return 0;
    int fd = open(path, O_RDONLY);
    if (fd < 0) return 0;
    int synced = fsync(fd) == 0; close(fd);
    if (!synced || !file_hash(path, &hash)) return 0;
    int n = snprintf(temp, sizeof temp, "%s.tmp.XXXXXX", name);
    if (n <= 0 || (size_t)n >= sizeof temp) return 0;
    fd = mkstemp(temp);
    if (fd < 0) return 0;
    char body[96]; n = snprintf(body, sizeof body, FORMAT " %016llx\n", (unsigned long long)hash);
    int ok = write(fd, body, n) == n && fsync(fd) == 0;
    close(fd);
    if (ok) ok = rename(temp, name) == 0;
    if (!ok) unlink(temp);
    /* Directory persistence is helpful, but lack of a marker is always safe. */
    if (ok) {
        char directory[PATH_MAX]; snprintf(directory, sizeof directory, "%s", name);
        char *slash = strrchr(directory, '/');
        if (slash) { *slash = 0; fd = open(directory, O_RDONLY | O_DIRECTORY);
            if (fd >= 0) { (void)fsync(fd); close(fd); } }
    }
    return ok;
}

static const struct profile *identify(FILE *f)
{
    Elf64_Ehdr eh; struct stat st;
    if (fstat(fileno(f), &st) ||
        fread(&eh, sizeof eh, 1, f) != 1 || memcmp(eh.e_ident, ELFMAG, SELFMAG) ||
        eh.e_ident[EI_CLASS] != ELFCLASS64 || eh.e_ident[EI_DATA] != ELFDATA2LSB ||
        eh.e_type != ET_EXEC || eh.e_machine != EM_AARCH64) return NULL;
    rewind(f); unsigned char buf[65536]; size_t n; uint64_t hash = FNV_INIT;
    while ((n = fread(buf, 1, sizeof buf, f))) hash = fingerprint(hash, buf, n);
    if (ferror(f)) return NULL;
    for (size_t i = 0; i < sizeof profiles / sizeof profiles[0]; i++)
        if (st.st_size == profiles[i].file_size && hash == profiles[i].file_hash)
            return &profiles[i];
    return NULL;
}

struct coordinate_patch { uintptr_t address; unsigned offset; };
static struct coordinate_patch coordinates[] = {
    {0x62f648, 0x870}, {0x62f660, 0x870}, /* Z, both formatting branches */
    {0x62f6c8, 0x868}, {0x62f72c, 0x86c} /* X and Y */
};

static void coordinate_words(uint32_t words[3], unsigned offset)
{
    words[0] = 0xd00700a0U; /* adrp x0, 0xe645000 from this code page */
    words[1] = 0xbd400000U | ((offset / 4) << 10); /* ldr s0,[x0,#offset] */
    words[2] = 0x1e22c000U; /* fcvt d0,s0 (client G-code vector is float[4]) */
}

static void write_jump(void *destination, uintptr_t target)
{
    const uint32_t words[] = {0x58000050U, 0xd61f0200U};
    memcpy(destination, words, 8); memcpy((char *)destination + 8, &target, 8);
}

static void (*original_writer)(void *, double, int, double);
static void (*original_loader)(void *);
static void (*original_start)(void);
static const char *(*string_data)(const void *);
static void (*string_construct)(void *);
static void *(*string_assign)(void *, const char *);
static void (*string_destroy)(void *);
static pthread_mutex_t record_lock = PTHREAD_MUTEX_INITIALIZER;
static char loaded_path[PATH_MAX];
static uint64_t loaded_hash;
static int loaded_valid;

static void logmsg(const char *message)
{
#ifdef WMP_RECOVERYFIX_TEST
    (void)message; /* Never create the root client's /tmp log as a test user. */
#else
    FILE *f = fopen("/tmp/wmp_recoveryfix.log", "a");
    if (f) { fprintf(f, "[pid %d] %s\n", (int)getpid(), message); fclose(f); }
#endif
}

static int checkpoint_path(const void *name, char path[PATH_MAX])
{
    const char *value = string_data(name);
    char resolved[PATH_MAX];
    if (!value || !realpath(value, resolved)) return 0;
    const char *base = strrchr(resolved, '/');
    if (!base || (strcmp(base + 1, "plr_dataA.ini") && strcmp(base + 1, "plr_dataB.ini"))) return 0;
    snprintf(path, PATH_MAX, "%s", resolved); return 1;
}

static void save_checkpoint(void *name, double z, int filepos, double e)
{
    pthread_mutex_lock(&record_lock);
    char path[PATH_MAX]; uint64_t before = 0, after = 0;
    int known = checkpoint_path(name, path);
    int existed = known && file_hash(path, &before);
    original_writer(name, z, filepos, e);
    /* The vendor can return without writing. Never label an untouched legacy
     * checkpoint merely because this function was called with the same Z/pos.
     */
    if (known && file_hash(path, &after) && (!existed || before != after)) {
        if (!stamp_record(path)) logmsg("checkpoint format marker write failed; recovery will reject this record");
    }
    pthread_mutex_unlock(&record_lock);
}

static void load_checkpoint(void *name)
{
    pthread_mutex_lock(&record_lock);
    uint64_t after;
    loaded_valid = checkpoint_path(name, loaded_path) && verify_record(loaded_path, &loaded_hash);
    original_loader(name);
    loaded_valid = loaded_valid && verify_record(loaded_path, &after) && after == loaded_hash;
    logmsg(loaded_valid ? "loaded verified G-code XYZ checkpoint" :
                         "loaded legacy/unverified checkpoint; Continue will be blocked");
    pthread_mutex_unlock(&record_lock);
}

static void start_recovery(void)
{
    uint64_t hash;
    pthread_mutex_lock(&record_lock);
    int ok = loaded_valid && verify_record(loaded_path, &hash) && hash == loaded_hash;
    pthread_mutex_unlock(&record_lock);
    if (!ok) {
        logmsg("RECOVERY BLOCKED before motion: checkpoint lacks matching G-code XYZ format marker; migrate or start a new print");
        if (string_construct && string_assign && string_destroy) {
            /* Verified 32-byte C++11 string ABI; use libstdc++ operations. */
            uint64_t message[4];
            string_construct(message);
            string_assign(message, "M118 Recovery blocked: saved position needs migration; do not resume this checkpoint unchanged");
            void (*send_gcode)(void *) = (void *)active_profile->send_gcode;
            send_gcode(message);
            string_destroy(message);
        }
        return;
    }
    logmsg("starting recovery from verified G-code XYZ checkpoint");
    original_start();
}

static int protect(uintptr_t address, size_t length, int flags)
{
    long page = sysconf(_SC_PAGESIZE);
    if (page <= 0) return -1;
    uintptr_t start = address & ~((uintptr_t)page - 1);
    uintptr_t end = (address + length + page - 1) & ~((uintptr_t)page - 1);
    return mprotect((void *)start, end - start, flags);
}

static int loaded_matches(FILE *f, uintptr_t address, size_t size)
{
    unsigned char original[8192];
    if (size > sizeof original || fseeko(f, address - 0x400000, SEEK_SET) ||
        fread(original, size, 1, f) != 1) return 0;
    return !memcmp(original, (const void *)address, size);
}

#ifndef WMP_RECOVERYFIX_TEST
__attribute__((constructor))
#endif
static void initialize(void)
{
    if (getenv("WMP_RECOVERYFIX_DISABLE")) { logmsg("disabled by WMP_RECOVERYFIX_DISABLE"); return; }
    FILE *f = fopen("/proc/self/exe", "rb");
    if (!f) return;
    const struct profile *p = identify(f);
    int recognized = p && loaded_matches(f, p->writer, 0x15f0) &&
        loaded_matches(f, p->loader, 0x1330) && loaded_matches(f, p->start, p->start_size) &&
        loaded_matches(f, p->send_gcode, 16);
    fclose(f);
    if (!recognized) { logmsg("guard failed: unrecognized/modified client; not patching"); return; }
    string_data = dlsym(RTLD_DEFAULT, "_ZNKSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEE5c_strEv");
    string_construct = dlsym(RTLD_DEFAULT, "_ZNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEC1Ev");
    string_assign = dlsym(RTLD_DEFAULT, "_ZNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEaSEPKc");
    string_destroy = dlsym(RTLD_DEFAULT, "_ZNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEED1Ev");
    if (!string_data) { logmsg("std::string accessor unavailable; not patching"); return; }
    active_profile = p;
    uintptr_t delta = p->writer - profiles[0].writer;
    for (size_t i = 0; i < sizeof coordinates / sizeof coordinates[0]; i++)
        coordinates[i].address += delta;
    const uintptr_t entries[] = {p->writer, p->loader, p->start};
    const uintptr_t callbacks[] = {(uintptr_t)save_checkpoint, (uintptr_t)load_checkpoint, (uintptr_t)start_recovery};
    void *tramp = mmap(NULL, 96, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (tramp == MAP_FAILED) { logmsg("trampoline allocation failed"); return; }
    for (size_t i = 0; i < 3; i++) {
        /* All three guarded prologues are position-independent; no PC-relative
         * loads/branches are relocated. Loader includes its frame-size MOV.
         */
        void *slot = (char *)tramp + i * 32;
        memcpy(slot, (void *)entries[i], 16);
        write_jump((char *)slot + 16, entries[i] + 16);
    }
    __builtin___clear_cache(tramp, (char *)tramp + 96);
    if (mprotect(tramp, 96, PROT_READ | PROT_EXEC)) {
        munmap(tramp, 96); logmsg("trampoline protection failed"); return;
    }
    /* These functions share one continuous text range; change it atomically
     * before vendor callback/timer threads start, then restore RX.
     */
    if (protect(p->loader, p->writer + 0x15f0 - p->loader, PROT_READ | PROT_WRITE | PROT_EXEC)) {
        munmap(tramp, 96); logmsg("text protection failed; not patching"); return;
    }
    original_writer = tramp; original_loader = (void *)((char *)tramp + 32);
    original_start = (void *)((char *)tramp + 64);
    for (size_t i = 0; i < sizeof coordinates / sizeof coordinates[0]; i++) {
        uint32_t words[3]; coordinate_words(words, coordinates[i].offset);
        memcpy((void *)coordinates[i].address, words, sizeof words);
    }
    /* Preserve sub-millimetre XY/tool offsets instead of stock one-decimal
     * rounding. Z's non-integer branch already has six significant digits.
     */
    const uintptr_t precision[] = {p->writer + 0x174, p->writer + 0x1f4, p->writer + 0x258};
    for (size_t i = 0; i < 3; i++) *(uint32_t *)precision[i] = 0x528000c0U; /* mov w0,#6 */
    for (size_t i = 0; i < 3; i++) write_jump((void *)entries[i], callbacks[i]);
    __builtin___clear_cache((char *)p->loader, (char *)(p->writer + 0x15f0));
    if (protect(p->loader, p->writer + 0x15f0 - p->loader, PROT_READ | PROT_EXEC))
        logmsg("warning: could not restore text RX permissions");
    char message[128];
    snprintf(message, sizeof message, "client %s: G-code XYZ checkpoint writer and hash-bound recovery guard installed", p->version);
    logmsg(message);
}

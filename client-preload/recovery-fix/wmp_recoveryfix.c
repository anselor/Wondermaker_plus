/* Reviewed-client checkpoint coordinates: G-code XYZ, not compensated toolhead XYZ.
 * Guarded in-memory edits only. A hash-bound sidecar identifies new records;
 * unmarked or changed legacy records cannot start automatic recovery.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <elf.h>
#include <errno.h>
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
#define MATERIAL_FORMAT "WMP-GCODE-XYZ-MATERIAL-2"

struct profile {
    const char *version;
    off_t file_size;
    uint64_t file_hash;
    uintptr_t writer, loader, start, send_gcode;
    uintptr_t selected_file;
    size_t start_size;
};
static const struct profile profiles[] = {
    {"1.1.08", 61340144, UINT64_C(0x3872f8647e4366ae),
     0x62f4bc, 0x62c2a8, 0x62d5d8, 0x61425c, 0xe644ff8, 0x1918},
    {"1.1.12", 61340216, UINT64_C(0xcef6a2287ca04bc8),
     0x62f824, 0x62c600, 0x62d930, 0x61434c, 0xe644ff8, 0x1928},
    {"1.1.13", 61340216, UINT64_C(0x3ed764ac9cdaa82d),
     0x62f810, 0x62c5ec, 0x62d91c, 0x614338, 0xe644ff8, 0x1928},
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

struct material_binding { int present; uint64_t hash; };

/* This binds bytes, not material readiness. Backend admission must separately
 * validate the committed job, current sensors/identities and operation state.
 * A custom material path must also be configured in the service environment.
 */
static int material_binding(struct material_binding *binding)
{
    const char *path = getenv("WMP_RECOVERY_JOB_PATH");
    if (!path) path = "/home/t13dp/printer_data/config/wmp_recovery_job.json";
    if (path[0] != '/') return 0;
    int fd = open(path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK);
    if (fd < 0) {
        const char *required = getenv("WMP_RECOVERY_JOB_REQUIRED");
        if (errno != ENOENT || (required && strcmp(required, "0"))) return 0;
        binding->present = 0; binding->hash = 0; return 1;
    }
    struct stat info;
    if (fstat(fd, &info) || !S_ISREG(info.st_mode) || info.st_size <= 0 || info.st_size > 65536) {
        close(fd); return 0;
    }
    unsigned char buf[4096]; ssize_t n; size_t total = 0;
    uint64_t hash = FNV_INIT;
    while ((n = read(fd, buf, sizeof buf)) > 0) {
        total += (size_t)n;
        if (total > 65536) { close(fd); return 0; }
        hash = fingerprint(hash, buf, (size_t)n);
    }
    close(fd);
    if (n < 0 || total != (size_t)info.st_size) return 0;
    binding->present = 1; binding->hash = hash; return 1;
}

static int same_binding(const struct material_binding *a, const struct material_binding *b)
{
    return a->present == b->present && a->hash == b->hash;
}

static int verify_record(const char *path, uint64_t *hash, const struct material_binding *expected)
{
    char name[PATH_MAX], format[64], material_text[64], extra;
    unsigned long long recorded = 0, material = 0;
    struct material_binding binding;
    if (!marker_path(path, name, sizeof name) || !file_hash(path, hash)
            || !material_binding(&binding)
            || (expected && !same_binding(&binding, expected))) return 0;
    FILE *f = fopen(name, "r");
    if (!f) return 0;
    int fields = fscanf(f, "%63s %llx %63s %c", format, &recorded, material_text, &extra);
    fclose(f);
    if (fields < 2 || recorded != *hash) return 0;
    if (!strcmp(format, FORMAT))
        return fields == 2 && !binding.present;
    return fields == 3 && !strcmp(format, MATERIAL_FORMAT) && binding.present
        && sscanf(material_text, "%llx%c", &material, &extra) == 1
        && material == binding.hash;
}

/* Bind the format to the entire record, so a later stock writer, truncation,
 * partial write or stale sidecar fails closed. Publish only after data fsync.
 * A crash before sidecar publication may lose the newest checkpoint, never
 * silently reinterpret it. A/B selection remains the vendor's responsibility.
 */
static int stamp_bound_record(const char *path, const struct material_binding *expected)
{
    char name[PATH_MAX], temp[PATH_MAX]; uint64_t hash;
    struct material_binding binding;
    if (!material_binding(&binding) || !same_binding(&binding, expected)) return 0;
    if (!marker_path(path, name, sizeof name)) return 0;
    int fd = open(path, O_RDONLY);
    if (fd < 0) return 0;
    int synced = fsync(fd) == 0; close(fd);
    if (!synced || !file_hash(path, &hash)) return 0;
    int n = snprintf(temp, sizeof temp, "%s.tmp.XXXXXX", name);
    if (n <= 0 || (size_t)n >= sizeof temp) return 0;
    fd = mkstemp(temp);
    if (fd < 0) return 0;
    char body[128];
    n = binding.present
        ? snprintf(body, sizeof body, MATERIAL_FORMAT " %016llx %016llx\n",
                   (unsigned long long)hash, (unsigned long long)binding.hash)
        : snprintf(body, sizeof body, FORMAT " %016llx\n", (unsigned long long)hash);
    /* The stock screen runs as root; Klipper reads these format/hash markers
     * as the printer user. mkstemp's 0600 would make valid evidence unreadable.
     * Keep writes private until the complete marker is ready for publication.
     */
    int ok = write(fd, body, n) == n && fchmod(fd, 0644) == 0 && fsync(fd) == 0;
    struct material_binding after;
    if (ok) ok = material_binding(&after) && same_binding(&binding, &after);
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

#ifdef WMP_RECOVERYFIX_TEST
static int stamp_record(const char *path)
{
    struct material_binding binding;
    return material_binding(&binding) && stamp_bound_record(path, &binding);
}
#endif

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
static struct material_binding loaded_material;
static int loaded_valid;
static const void *selected_file_string;
static char loaded_file[PATH_MAX];
/* Receiver copies arguments synchronously; it must only queue UI/worker work.
 * A queued selection is not backend admission and never authorizes stock start.
 */
typedef int (*managed_selection_fn)(unsigned, const char *, const char *, const char *, const char *);
typedef int (*managed_review_fn)(unsigned, unsigned);
typedef int (*managed_ready_fn)(unsigned);
#ifdef WMP_RECOVERYFIX_TEST
static managed_selection_fn test_managed_selection;
static managed_review_fn test_managed_review;
static managed_ready_fn test_managed_ready;
#endif
static int managed_review(unsigned reason)
{
#ifdef WMP_RECOVERYFIX_TEST
    managed_review_fn review = test_managed_review;
#else
    managed_review_fn review = (managed_review_fn)dlsym(RTLD_DEFAULT, "wmp_managed_recovery_review");
#endif
    return review && review(1, reason);
}
static managed_selection_fn managed_receiver_symbol(void)
{
#ifdef WMP_RECOVERYFIX_TEST
    return test_managed_selection;
#else
    return (managed_selection_fn)dlsym(RTLD_DEFAULT, "wmp_managed_recovery_select");
#endif
}

static managed_selection_fn managed_receiver(void)
{
    managed_selection_fn receiver = managed_receiver_symbol();
#ifdef WMP_RECOVERYFIX_TEST
    managed_ready_fn ready = test_managed_ready;
#else
    managed_ready_fn ready = (managed_ready_fn)dlsym(RTLD_DEFAULT, "wmp_managed_recovery_ready");
#endif
    /* Older receiver builds retain their original ownership contract. New
     * builds advertise actual readiness, not mere symbol visibility. */
    return receiver && (!ready || ready(1)) ? receiver : NULL;
}

static void logmsg(const char *message);
static void recovery_notice(const char *text)
{
    logmsg(text);
    if (string_construct && string_assign && string_destroy && active_profile) {
        uint64_t message[4];
        string_construct(message);
        string_assign(message, text);
        void (*send_gcode)(void *) = (void *)active_profile->send_gcode;
        send_gcode(message);
        string_destroy(message);
    }
}


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
    struct material_binding binding;
    int material_known = material_binding(&binding);
    int existed = known && file_hash(path, &before);
    original_writer(name, z, filepos, e);
    /* The vendor can return without writing. Never label an untouched legacy
     * checkpoint merely because this function was called with the same Z/pos.
     */
    if (known && file_hash(path, &after) && (!existed || before != after)) {
        if (!material_known || !stamp_bound_record(path, &binding))
            logmsg("Could not bind checkpoint to stable job evidence; recovery will reject this record");
    }
    pthread_mutex_unlock(&record_lock);
}

static void load_checkpoint(void *name)
{
    pthread_mutex_lock(&record_lock);
    uint64_t after;
    loaded_valid = checkpoint_path(name, loaded_path) && material_binding(&loaded_material)
        && verify_record(loaded_path, &loaded_hash, &loaded_material);
    original_loader(name);
    loaded_file[0] = 0;
    if (selected_file_string && string_data) {
        const char *file = string_data(selected_file_string);
        if (file && file[0] && strnlen(file, sizeof loaded_file) < sizeof loaded_file)
            memcpy(loaded_file, file, strlen(file) + 1);
    }
    loaded_valid = loaded_valid && verify_record(loaded_path, &after, &loaded_material) && after == loaded_hash;
    logmsg(loaded_valid ? "Loaded a verified G-code position checkpoint" :
                         "Loaded an unverified checkpoint; Continue is blocked until coordinates are verified");
    pthread_mutex_unlock(&record_lock);
}

static void start_recovery(void)
{
    /* Ready managed UI owns review. On the current UI target an unavailable
     * receiver reports a recovery-only error; it never authorizes stock replay.
     * Old verified clients retain the existing coordinate-only fallback only
     * when record validation and the installed material policy permit it. */
    managed_selection_fn receiver = managed_receiver();
    if (!receiver && managed_receiver_symbol() && active_profile && !strcmp(active_profile->version, "1.1.13")) {
        recovery_notice("M118 Recovery unavailable: WM+ screen initialization is incomplete. Reinstall the matching screen package and reopen recovery; no preparation started. Other printer controls remain available.");
        return;
    }
    uint64_t hash;
    pthread_mutex_lock(&record_lock);
    int ok = loaded_valid && verify_record(loaded_path, &hash, &loaded_material) && hash == loaded_hash;
    int managed = loaded_material.present;
    char file[PATH_MAX], checkpoint[PATH_MAX], checkpoint_hash[17], job_hash[17];
    file[0] = checkpoint[0] = 0;
    if (ok && managed) {
        const char *current = selected_file_string && string_data ? string_data(selected_file_string) : NULL;
        ok = loaded_file[0] && current && !strcmp(current, loaded_file);
        if (ok) {
            memcpy(file, loaded_file, strlen(loaded_file) + 1);
            const char *base = strrchr(loaded_path, '/');
            snprintf(checkpoint, sizeof checkpoint, "%s", base ? base + 1 : loaded_path);
            snprintf(checkpoint_hash, sizeof checkpoint_hash, "%016llx", (unsigned long long)loaded_hash);
            snprintf(job_hash, sizeof job_hash, "%016llx", (unsigned long long)loaded_material.hash);
        }
    }
    pthread_mutex_unlock(&record_lock);
    if (!ok) {
        if (receiver && managed_review(1)) return;
        recovery_notice("M118 Recovery blocked: saved file or checkpoint selection is missing or changed. Reload the recovery selection.");
        return;
    }
    if (!managed && receiver) {
        if (managed_review(2)) return;
        recovery_notice("M118 Recovery blocked: this legacy checkpoint has no managed job record. Original records were not changed; stock preparation is disabled.");
        return;
    }
    if (managed) {
        if (!receiver || !receiver(1, file, checkpoint, checkpoint_hash, job_hash))
            recovery_notice("M118 Recovery blocked: managed recovery screen is unavailable or refused the selection. No preparation started.");
        else
            logmsg("Managed recovery selection queued; stock preparation suppressed");
        return;
    }
    logmsg("Starting recovery from a verified G-code position checkpoint");
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
#ifndef WMP_RECOVERYFIX_TEST
    char exe[512];
    ssize_t n = readlink("/proc/self/exe", exe, sizeof exe - 1);
    if (n <= 0 || n == sizeof exe - 1) return;
    exe[n] = 0;
    const char *base = strrchr(exe, '/');
    if (strcmp(base ? base + 1 : exe, "client")) return;
#endif
    if (getenv("WMP_RECOVERYFIX_DISABLE")) { logmsg("disabled by WMP_RECOVERYFIX_DISABLE"); return; }
    FILE *f = fopen("/proc/self/exe", "rb");
    if (!f) return;
    const struct profile *p = identify(f);
    int recognized = p && loaded_matches(f, p->writer, 0x15f0) &&
        loaded_matches(f, p->loader, 0x1330) && loaded_matches(f, p->start, p->start_size) &&
        loaded_matches(f, p->send_gcode, 16);
    fclose(f);
    if (!recognized) { logmsg("Patch skipped: unsupported or modified screen client; check firmware compatibility"); return; }
    string_data = dlsym(RTLD_DEFAULT, "_ZNKSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEE5c_strEv");
    string_construct = dlsym(RTLD_DEFAULT, "_ZNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEC1Ev");
    string_assign = dlsym(RTLD_DEFAULT, "_ZNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEaSEPKc");
    string_destroy = dlsym(RTLD_DEFAULT, "_ZNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEED1Ev");
    if (!string_data) { logmsg("Patch skipped: screen string-access function is unavailable"); return; }
    /* This stock global exists only in .symtab, not .dynsym. Resolve it
     * through the exact-ELF profile already verified above, like the hooks. */
    selected_file_string = (void *)p->selected_file;
    active_profile = p;
    uintptr_t delta = p->writer - profiles[0].writer;
    for (size_t i = 0; i < sizeof coordinates / sizeof coordinates[0]; i++)
        coordinates[i].address += delta;
    const uintptr_t entries[] = {p->writer, p->loader, p->start};
    const uintptr_t callbacks[] = {(uintptr_t)save_checkpoint, (uintptr_t)load_checkpoint, (uintptr_t)start_recovery};
    void *tramp = mmap(NULL, 96, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (tramp == MAP_FAILED) { logmsg("Patch skipped: could not allocate memory for the saved entry code"); return; }
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
        munmap(tramp, 96); logmsg("Patch skipped: could not make the saved entry code executable"); return;
    }
    /* These functions share one continuous text range; change it atomically
     * before vendor callback/timer threads start, then restore RX.
     */
    if (protect(p->loader, p->writer + 0x15f0 - p->loader, PROT_READ | PROT_WRITE | PROT_EXEC)) {
        munmap(tramp, 96); logmsg("Patch skipped: could not make screen code writable"); return;
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
        logmsg("Warning: could not restore read/execute memory permissions; inspect the patch log before printing");
    char message[128];
    snprintf(message, sizeof message, "client %s: G-code recovery coordinates and checkpoint verification enabled", p->version);
    logmsg(message);
}

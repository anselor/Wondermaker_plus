/* Preserve physical head configuration on vendor communication faults.
 * The vendor unlock_extruder callback clears UUIDs, installs printer1.cfg,
 * and persists one head. Keep Klipper's shutdown intact; recovery stays manual.
 * GPL-3.0-or-later, like the rest of Wondermaker+.
 */
#define _GNU_SOURCE
#include <elf.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

struct profile { const char *version; off_t size; uint64_t hash; uintptr_t entry; };
static const struct profile profiles[] = {
    {"1.1.08", 61340144, UINT64_C(0x3872f8647e4366ae), 0x633c70},
    {"1.1.12", 61340216, UINT64_C(0xcef6a2287ca04bc8), 0x633fd8},
    {"1.1.13", 61340216, UINT64_C(0x3ed764ac9cdaa82d), 0x633fc4},
};
static const struct profile *active;

static const struct profile *identify(FILE *f)
{
    Elf64_Ehdr eh;
    struct stat st;
    if (fstat(fileno(f), &st) || fread(&eh, sizeof eh, 1, f) != 1 ||
        memcmp(eh.e_ident, ELFMAG, SELFMAG) || eh.e_ident[EI_CLASS] != ELFCLASS64 ||
        eh.e_ident[EI_DATA] != ELFDATA2LSB || eh.e_machine != EM_AARCH64 || eh.e_type != ET_EXEC)
        return NULL;
    rewind(f);
    uint64_t hash = UINT64_C(0xcbf29ce484222325);
    unsigned char data[65536]; size_t n;
    while ((n = fread(data, 1, sizeof data, f)))
        for (size_t i = 0; i < n; i++) hash = (hash ^ data[i]) * UINT64_C(0x100000001b3);
    if (ferror(f)) return NULL;
    for (size_t i = 0; i < sizeof profiles / sizeof profiles[0]; i++)
        if (st.st_size == profiles[i].size && hash == profiles[i].hash) return &profiles[i];
    return NULL;
}

static void logmsg(const char *message)
{
    FILE *f = fopen("/tmp/wmp_head-config-guard.log", "a");
    if (f) { fprintf(f, "[pid %d] %s\n", getpid(), message); fclose(f); }
}

/* No writes to printer state, no motion, no restart, no retry, no error suppression.
 * The original MCU timeout already put Klipper in shutdown before this callback.
 */
static void preserve_heads(void)
{
    logmsg("Communication fault: physical head configuration preserved; resolve the fault and restart Klipper manually");
}

static void write_jump(void *destination, uintptr_t callback)
{
    const uint32_t words[] = {0x58000050U, 0xd61f0200U};
    memcpy(destination, words, 8);
    memcpy((char *)destination + 8, &callback, 8);
}

__attribute__((constructor))
static void initialize(void)
{
    char exe[512]; ssize_t n = readlink("/proc/self/exe", exe, sizeof exe - 1);
    if (n <= 0 || n == sizeof exe - 1) return;
    exe[n] = 0;
    const char *base = strrchr(exe, '/');
    if (strcmp(base ? base + 1 : exe, "client")) return;
    if (getenv("WMP_HEAD_CONFIG_GUARD_DISABLE")) { logmsg("Disabled by WMP_HEAD_CONFIG_GUARD_DISABLE"); return; }
    FILE *f = fopen("/proc/self/exe", "rb");
    if (!f) return;
    const struct profile *p = identify(f);
    unsigned char original[2016];
    int valid = p && !fseeko(f, p->entry - 0x400000, SEEK_SET) &&
        fread(original, 1, sizeof original, f) == sizeof original &&
        !memcmp(original, (const void *)p->entry, sizeof original);
    fclose(f);
    if (!valid) { logmsg("Patch skipped: unsupported or modified screen client"); return; }
    long page_size = sysconf(_SC_PAGESIZE);
    if (page_size <= 0) return;
    uintptr_t start = p->entry & ~((uintptr_t)page_size - 1);
    uintptr_t end = (p->entry + 16 + page_size - 1) & ~((uintptr_t)page_size - 1);
    if (mprotect((void *)start, end - start, PROT_READ | PROT_WRITE | PROT_EXEC)) {
        logmsg("Patch skipped: could not make screen code writable"); return;
    }
    active = p;
    write_jump((void *)p->entry, (uintptr_t)preserve_heads);
    __builtin___clear_cache((char *)p->entry, (char *)p->entry + 16);
    if (mprotect((void *)start, end - start, PROT_READ | PROT_EXEC))
        logmsg("Warning: could not restore executable memory permissions");
    char message[160];
    snprintf(message, sizeof message, "client %s: destructive head reset blocked; communication faults keep Klipper stopped", active->version);
    logmsg(message);
}

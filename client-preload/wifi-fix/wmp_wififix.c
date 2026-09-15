/* Keep wpa_supplicant reconnecting after transient failures.
 * Verified vendor clients: 1.1.04 and 1.1.08 (AArch64, non-PIE).
 * Preserve WRONG_KEY; patch CONN_FAILED/timed out,
 * ASSOC-REJECT, and NETWORK-NOT-FOUND after its existing retry threshold.
 * See client-preload/README.md for corrected branch mapping and evidence.
 */
#define _GNU_SOURCE
#include <elf.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

#define NOP 0xd503201fU
#define CODE_SIZE 2656
#define SITE_COUNT 3

struct site { uintptr_t addr; uint32_t expect; const char *event; };
struct profile {
    const char *version;
    off_t file_size;
    uintptr_t entry;
    uint64_t code_fingerprint;
    uintptr_t wrong_key;
    struct site sites[SITE_COUNT];
};
static const struct profile profiles[] = {
    { "1.1.04", 61336120, 0x65ffcc, UINT64_C(0x82fd051e621b83c1), 0x6605ec,
      {{0x6604d8, 0x940009bd, "CONN_FAILED/timed out"},
       {0x660700, 0x94000933, "ASSOC-REJECT"},
       {0x660850, 0x940008df, "NETWORK-NOT-FOUND"}} },
    { "1.1.08", 61340144, 0x6607a8, UINT64_C(0x42bcde31a6c13e70), 0x660dc8,
      {{0x660cb4, 0x940009bd, "CONN_FAILED/timed out"},
       {0x660edc, 0x94000933, "ASSOC-REJECT"},
       {0x66102c, 0x940008df, "NETWORK-NOT-FOUND"}} },
};

static void logmsg(const char *msg)
{
    FILE *f = fopen("/tmp/wmp_wififix.log", "a");
    if (f) {
        fprintf(f, "[pid %d] %s\n", (int)getpid(), msg);
        fclose(f);
    }
}

/* Fingerprint identifies the reviewed function, not cryptographic authenticity.
 * Validate file architecture/layout before dereferencing fixed runtime addresses.
 */
static const struct profile *identify(FILE *f, unsigned char code[CODE_SIZE])
{
    Elf64_Ehdr eh;
    struct stat st;
    if (fstat(fileno(f), &st) || fread(&eh, sizeof eh, 1, f) != 1 ||
        memcmp(eh.e_ident, ELFMAG, SELFMAG) ||
        eh.e_ident[EI_CLASS] != ELFCLASS64 || eh.e_ident[EI_DATA] != ELFDATA2LSB ||
        eh.e_type != ET_EXEC || eh.e_machine != EM_AARCH64 ||
        eh.e_phentsize != sizeof(Elf64_Phdr) || eh.e_phnum > 128)
        return NULL;
    for (size_t i = 0; i < sizeof profiles / sizeof profiles[0]; i++) {
        const struct profile *p = &profiles[i];
        if (st.st_size != p->file_size) continue;
        for (unsigned j = 0; j < eh.e_phnum; j++) {
            Elf64_Phdr ph;
            if (fseeko(f, eh.e_phoff + j * sizeof ph, SEEK_SET) ||
                fread(&ph, sizeof ph, 1, f) != 1) return NULL;
            if (ph.p_type != PT_LOAD || !(ph.p_flags & PF_X) ||
                p->entry < ph.p_vaddr || ph.p_filesz < CODE_SIZE ||
                p->entry - ph.p_vaddr > ph.p_filesz - CODE_SIZE) continue;
            uint64_t offset = ph.p_offset + p->entry - ph.p_vaddr;
            if (offset > (uint64_t)st.st_size - CODE_SIZE ||
                fseeko(f, offset, SEEK_SET) || fread(code, CODE_SIZE, 1, f) != 1)
                return NULL;
            uint64_t hash = UINT64_C(0xcbf29ce484222325);
            for (size_t k = 0; k < CODE_SIZE; k++)
                hash = (hash ^ code[k]) * UINT64_C(0x100000001b3);
            if (hash == p->code_fingerprint) return p;
        }
    }
    return NULL;
}

/* Check the complete loaded function before changing any site. Accept only
 * the intended NOPs as already-applied edits; WRONG_KEY must remain intact.
 */
static int matches_memory(const struct profile *p, const unsigned char *original,
                          const unsigned char *loaded)
{
    for (size_t offset = 0; offset < CODE_SIZE; offset += 4) {
        uint32_t disk, memory;
        memcpy(&disk, original + offset, 4);
        memcpy(&memory, loaded + offset, 4);
        if (disk == memory) continue;
        int allowed = 0;
        for (size_t i = 0; i < SITE_COUNT; i++)
            if (p->entry + offset == p->sites[i].addr &&
                disk == p->sites[i].expect && memory == NOP) allowed = 1;
        if (!allowed) return 0;
    }
    return 1;
}

#ifndef WMP_WIFIFIX_TEST
__attribute__((constructor))
static void wmp_wififix_init(void)
{
    char exe[512];
    ssize_t n = readlink("/proc/self/exe", exe, sizeof exe - 1);
    if (n <= 0 || n == sizeof exe - 1) return;
    exe[n] = 0;
    const char *base = strrchr(exe, '/');
    if (strcmp(base ? base + 1 : exe, "client")) return;
    if (getenv("WMP_WIFIFIX_DISABLE")) {
        logmsg("disabled by WMP_WIFIFIX_DISABLE");
        return;
    }
    unsigned char code[CODE_SIZE];
    FILE *f = fopen("/proc/self/exe", "rb");
    const struct profile *p = f ? identify(f, code) : NULL;
    if (f) fclose(f);
    if (!p) {
        logmsg("version guard failed: unrecognized client, not patching");
        return;
    }
    if (!matches_memory(p, code, (const unsigned char *)p->entry)) {
        logmsg("version guard failed: loaded function differs, not patching");
        return;
    }
    long page_size = sysconf(_SC_PAGESIZE);
    if (page_size <= 0) return;
    uintptr_t first = p->entry & ~((uintptr_t)page_size - 1);
    uintptr_t end = (p->entry + CODE_SIZE + page_size - 1) & ~((uintptr_t)page_size - 1);
    if (mprotect((void *)first, end - first, PROT_READ | PROT_WRITE | PROT_EXEC)) {
        logmsg("mprotect failed, not patching");
        return;
    }
    for (size_t i = 0; i < SITE_COUNT; i++)
        *(volatile uint32_t *)p->sites[i].addr = NOP;
    __builtin___clear_cache((char *)first, (char *)end);
    if (mprotect((void *)first, end - first, PROT_READ | PROT_EXEC))
        logmsg("warning: could not restore executable page permissions");
    char msg[160];
    snprintf(msg, sizeof msg, "client %s: 3 transient-failure disconnect sites patched; WRONG_KEY preserved", p->version);
    logmsg(msg);
}
#endif

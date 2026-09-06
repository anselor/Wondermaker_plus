/* wmp_wififix: keep wpa_supplicant auto-reconnecting after a failed reconnect.
 *
 * Target: Wondermaker touchscreen `client` 1.1.04 (non-PIE, base 0x400000).
 * WifiManager::processEvent (0x65ffcc) calls WifiManager::disconnect (0x662bcc)
 * on transient failures (CTRL-EVENT-DISCONNECTED / CONN_FAILED / timed out,
 * ASSOC-REJECT, NETWORK-NOT-FOUND). disconnect() sends DISCONNECT to
 * wpa_supplicant, which then stops reconnecting until told otherwise, so one
 * failed reconnect leaves the printer offline until the Wi-Fi page is opened.
 * This library NOPs those three call sites in memory at load. The WRONG_KEY
 * site (0x660850) is left as is. The on-disk binary is not modified.
 *
 * Loaded via LD_PRELOAD into makerbase-client.service (tools/deploy.py install
 * preload). Guards: process name must be `client`; every site must hold the
 * expected `bl` encoding. Log: /tmp/wmp_wififix.log.
 */
#define _GNU_SOURCE
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

#define PROCESSEVENT_ADDR   0x65ffccUL
#define PROCESSEVENT_WORD   0xa9a67bfdU   /* stp x29,x30,[sp,#-0x1a0]! */
#define NOP                 0xd503201fU

static const struct { uintptr_t addr; uint32_t expect; const char *event; } sites[] = {
    { 0x6604d8UL, 0x940009bdU, "DISCONNECTED/CONN_FAILED/timed out" },
    { 0x6605ecUL, 0x94000978U, "ASSOC-REJECT" },
    { 0x660700UL, 0x94000933U, "NETWORK-NOT-FOUND" },
};

static FILE *logf;

static void logmsg(const char *msg)
{
    if (!logf)
        logf = fopen("/tmp/wmp_wififix.log", "a");
    if (logf) {
        fprintf(logf, "[pid %d] %s\n", (int)getpid(), msg);
        fflush(logf);
    }
}

static int is_client(void)
{
    char exe[256];
    ssize_t n = readlink("/proc/self/exe", exe, sizeof exe - 1);
    if (n <= 0)
        return 0;
    exe[n] = 0;
    const char *base = strrchr(exe, '/');
    return strcmp(base ? base + 1 : exe, "client") == 0;
}

static int write_word(uintptr_t addr, uint32_t word)
{
    long pg = sysconf(_SC_PAGESIZE);
    void *page = (void *)(addr & ~(uintptr_t)(pg - 1));
    if (mprotect(page, pg, PROT_READ | PROT_WRITE | PROT_EXEC) != 0)
        return -1;
    *(volatile uint32_t *)addr = word;
    __builtin___clear_cache((char *)addr, (char *)addr + 4);
    mprotect(page, pg, PROT_READ | PROT_EXEC);
    return 0;
}

__attribute__((constructor))
static void wmp_wififix_init(void)
{
    if (!is_client())
        return;
    if (getenv("WMP_WIFIFIX_DISABLE")) {
        logmsg("disabled by WMP_WIFIFIX_DISABLE");
        return;
    }
    if (*(volatile uint32_t *)PROCESSEVENT_ADDR != PROCESSEVENT_WORD) {
        logmsg("version guard failed: processEvent prologue mismatch, not patching");
        return;
    }
    size_t n = sizeof sites / sizeof sites[0];
    for (size_t i = 0; i < n; i++) {
        uint32_t cur = *(volatile uint32_t *)sites[i].addr;
        char buf[160];
        if (cur == NOP) {
            snprintf(buf, sizeof buf, "site %zu (%s) already patched", i, sites[i].event);
        } else if (cur != sites[i].expect) {
            snprintf(buf, sizeof buf, "site %zu (%s) unexpected word 0x%08x, not patching",
                     i, sites[i].event, cur);
        } else if (write_word(sites[i].addr, NOP) != 0) {
            snprintf(buf, sizeof buf, "site %zu (%s) mprotect failed", i, sites[i].event);
        } else {
            snprintf(buf, sizeof buf, "site %zu (%s) patched: bl disconnect -> nop", i, sites[i].event);
        }
        logmsg(buf);
    }
}

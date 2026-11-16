"""Compile the screen bridge and exercise its actual preference forwarding."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'client-preload/case-light/wmp_case_light.c'


@pytest.fixture(scope='module')
def harness(tmp_path_factory):
    if not shutil.which('gcc'):
        pytest.skip('gcc required')
    tmp = tmp_path_factory.mktemp('case-light-bridge')
    source = tmp / 'bridge.c'
    source.write_text('#include "' + str(SOURCE) + '"\n' + r'''
#include <assert.h>
static int low_calls, high_calls, sent, destroyed;
static int wake_calls, brightness_calls, next_preference;
static unsigned char led;
static int raw_value(void) { assert(!"factory getter must not run"); return 0; }
static int wake(void) { wake_calls++; return next_preference; }
static void brightness(unsigned int value) {
    // The button preference must be ready before the backlight is enabled.
    if (value && next_preference >= 0) assert(led == next_preference);
    brightness_calls++;
}
static int direct_calls, direct_value;
static int no_direct(int enabled) { direct_calls++; direct_value=enabled; return 0; }
static int yes_direct(int enabled) { direct_calls++; direct_value=enabled; return 1; }
static char last_command[128];
static int low(void) { low_calls++; return 17; }
static int high(void) { high_calls++; return 23; }
static void construct(void *value) { memset(value, 0, 32); }
static void *assign(void *value, const char *text) { memcpy(value, &text, sizeof text); return value; }
static void destroy(void *value) { (void)value; destroyed++; }
static void sender(void *value) {
    const char *text; memcpy(&text, value, sizeof text);
    snprintf(last_command, sizeof last_command, "%s", text); sent++;
}
int main(int argc, char **argv) {
    if (argc == 2) {
        FILE *f = fopen(argv[1], "rb");
        if (!f) return 2;
        const struct profile *p = identify(f); fclose(f);
        if (!p) return 3;
        printf("%s %lx %lx\n", p->version, (unsigned long)p->low, (unsigned long)p->high);
        return 0;
    }
    original_low = low; original_high = high; run_gcode = sender;
    direct_preference = no_direct;
    string_construct = construct; string_assign = assign; string_destroy = destroy;
    assert(light_low() == 17);
    assert(low_calls == 1 && high_calls == 0 && sent == 1 && destroyed == 1);
    assert(!strcmp(last_command, "SET_PIN PIN=case_light VALUE=0"));
    // Repeated OFF still forwards intent, even if physical GPIO was already off.
    assert(light_low() == 17 && sent == 2);
    assert(light_high() == 23);
    assert(high_calls == 1 && sent == 3 && destroyed == 3);
    assert(!strcmp(last_command, "SET_PIN PIN=case_light VALUE=1"));
    assert(direct_calls == 3 && direct_value == 1);
    direct_preference = yes_direct;
    assert(light_low() == 17 && direct_calls == 4 && direct_value == 0);
    assert(sent == 3); // Successful direct API must not also queue G-code.
    original_get = raw_value; original_brightness = brightness;
    screen_led_on = &led; wake_policy = wake;
    atomic_store(&cached_preference, -1);
    (void)light_value(); // Fallback must never invoke the mutating factory getter.
    atomic_store(&cached_preference, 1);
    assert(light_value() == 1); // Saved ON, even with physical LED asleep.
    atomic_store(&cached_preference, 0);
    assert(light_value() == 0);
    next_preference = 1; screen_brightness(100);
    assert(wake_calls == 1 && brightness_calls == 1 && led == 1);
    next_preference = 0; screen_brightness(50);
    assert(wake_calls == 2 && brightness_calls == 2 && led == 0);
    screen_brightness(0);
    assert(wake_calls == 2 && brightness_calls == 3); // Sleep never enables.
    next_preference = -1; led = 1; screen_brightness(100);
    assert(brightness_calls == 4 && led == 1); // Offline wake still works.
    // Multiple hooks can occupy a single page: all writes must precede RX.
    long page = sysconf(_SC_PAGESIZE);
    void *code = mmap(NULL, page, PROT_READ | PROT_WRITE | PROT_EXEC,
                      MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    assert(code != MAP_FAILED);
    uintptr_t sites[] = {(uintptr_t)code, (uintptr_t)code + 32, (uintptr_t)code + 64};
    uintptr_t targets[] = {123, 456, 789};
    install_jumps(sites, targets, 3);
    for (int i = 0; i < 3; i++) {
        uintptr_t target; memcpy(&target, (void *)(sites[i] + 8), sizeof target);
        assert(target == targets[i]);
    }
    munmap(code, page);
    char path[] = "/tmp/wmp-light-permissions-XXXXXX";
    int fd = mkstemp(path); assert(fd >= 0);
    assert(write(fd, "1\n", 2) == 2); assert(!fchmod(fd, 0440)); close(fd);
    assert(read_light_value(path) == 1);
    assert(!grant_gpio(path, getuid()));
    struct stat metadata; assert(!stat(path, &metadata));
    assert((metadata.st_mode & 0777) == 0640);
    FILE *value = fopen(path, "r"); assert(value && fgetc(value) == '1'); fclose(value);
    char link[128]; snprintf(link, sizeof link, "%s-link", path);
    assert(!symlink(path, link)); assert(!chmod(path, 0440));
    assert(grant_gpio(link, getuid()) == -1);
    assert(read_light_value(link) == 0); // Never follow an unexpected link.
    assert(!stat(path, &metadata) && (metadata.st_mode & 0777) == 0440);
    unlink(link); unlink(path);
    assert(read_light_value(path) == 0);
    assert(access(path, F_OK) == -1); // A missing GPIO is not created/exported.
    int saved_calls = direct_calls, saved_sent = sent, saved_low = low_calls;
    assert(initialize_gpio_output(path) == 17);
    assert(low_calls == saved_low + 1); // Missing GPIO uses vendor initializer.
    FILE *direction = fopen(path, "w"); assert(direction);
    fputs("in\n", direction); fclose(direction);
    assert(initialize_gpio_output(path) == 17);
    assert(low_calls == saved_low + 2); // Recover a partial input-only export.
    direction = fopen(path, "w"); assert(direction);
    fputs("out\n", direction); fclose(direction);
    assert(initialize_gpio_output(path) == 0);
    assert(low_calls == saved_low + 2); // Existing ON/OFF output is untouched.
    direction = fopen(path, "w"); assert(direction);
    fputs("invalid\n", direction); fclose(direction);
    assert(initialize_gpio_output(path) == -1);
    assert(!symlink(path, link));
    assert(initialize_gpio_output(link) == -1);
    assert(low_calls == saved_low + 2);
    assert(direct_calls == saved_calls && sent == saved_sent); // No saved OFF.
    unlink(link); unlink(path);
    // Door wake. Bit n: switch n+1 open. Only closed-to-open is an opening.
    #define DOORS(a, b) "HTTP/1.1 200 OK\r\n\r\n{\"result\": {\"eventtime\": 1.5, \"status\": {" \
        "\"gcode_button Door_button1\": {\"state\": \"" a "\"}, " \
        "\"gcode_button Door_button2\": {\"state\": \"" b "\"}}}}"
    assert(parse_doors(DOORS("PRESSED", "PRESSED")) == 0);
    assert(parse_doors(DOORS("RELEASED", "PRESSED")) == 1);
    assert(parse_doors(DOORS("PRESSED", "RELEASED")) == 2);
    assert(parse_doors(DOORS("RELEASED", "RELEASED")) == 3);
    assert(parse_doors(DOORS("OTHER", "OTHER")) == -1);
    assert(parse_doors("{\"result\": {\"status\": {}}}") == -1); // No door switches.
    assert(parse_doors("{\"result\": {\"status\": {\"gcode_button Door_button2\": "
                       "{\"state\": \"RELEASED\"}}}}") == 2);
    int last = -1;
    assert(!door_opened(3, &last) && last == 3); // Open at startup: baseline only.
    assert(!door_opened(3, &last));              // Still open: nothing further.
    assert(!door_opened(0, &last));              // Closing is not an opening.
    assert(door_opened(3, &last));               // Both switches together: once.
    assert(!door_opened(3, &last));
    assert(!door_opened(1, &last));              // One switch closes.
    assert(door_opened(3, &last));               // It opens again.
    assert(!door_opened(-1, &last) && last == -1); // Klipper unavailable.
    assert(!door_opened(3, &last));              // First reading afterwards.
    assert(!door_opened(0, &last) && door_opened(2, &last));
    char light[] = "/tmp/wmp-backlight-XXXXXX";
    fd = mkstemp(light); assert(fd >= 0);
    assert(write(fd, "0\n", 2) == 2); close(fd);
    assert(backlight_off(light) == 1);
    FILE *lit = fopen(light, "w"); assert(lit); fputs("255\n", lit); fclose(lit);
    assert(backlight_off(light) == 0);
    lit = fopen(light, "w"); assert(lit); fputs("0", lit); fclose(lit);
    assert(backlight_off(light) == 1);
    unlink(light);
    assert(backlight_off(light) == 0); // Unknown brightness never sends a touch.
    char device[] = "/tmp/wmp-touch-XXXXXX";
    fd = mkstemp(device); assert(fd >= 0); close(fd);
    assert(!touch_corner(device));
    struct input_event events[16];
    fd = open(device, O_RDONLY); assert(fd >= 0);
    assert(read(fd, events, sizeof events) == (ssize_t)sizeof events);
    char extra; assert(read(fd, &extra, 1) == 0); close(fd);
    assert(events[2].type == EV_SYN && events[11].type == EV_SYN && events[15].type == EV_SYN);
    assert(events[5].code == ABS_MT_POSITION_X && events[5].value == WAKE_X);
    assert(events[6].code == ABS_MT_POSITION_Y && events[6].value == WAKE_Y);
    assert(events[8].type == EV_KEY && events[8].code == BTN_TOUCH && events[8].value == 1);
    assert(events[13].code == ABS_MT_TRACKING_ID && events[13].value == -1);
    assert(events[14].code == BTN_TOUCH && events[14].value == 0); // Always released.
    unlink(device);
    assert(touch_corner(device) == -1); // A missing device is never created.
    assert(access(device, F_OK) == -1);
    door_wake_enabled = 0; door_wake_poll(); // Disabled: no request, no touch.
    return 0;
}
''')
    binary = tmp / 'bridge-test'
    for args in [
        ['gcc', '-O2', '-Wall', '-Wextra', '-Werror', '-pthread', str(source), '-ldl', '-o', str(binary)],
        ['gcc', '-shared', '-fPIC', '-O2', '-Wall', '-Wextra', '-Werror', '-pthread', str(SOURCE), '-ldl', '-o', str(tmp / 'bridge.so')],
    ]:
        subprocess.run(args, check=True, capture_output=True, text=True)
    return binary


def test_manual_choices_forward_to_saved_preference_and_preserve_vendor_setter(harness):
    subprocess.run([str(harness)], check=True)


def test_unknown_binary_is_rejected(harness):
    assert subprocess.run([str(harness), str(harness)]).returncode == 3


@pytest.mark.parametrize('version,low,high,get_value,brightness', [
    ('1.1.08', 0x624bd0, 0x624d94, 0x624f58, 0x552f8c),
    ('1.1.12', 0x624f28, 0x6250ec, 0x6252b0, 0x55307c),
    ('1.1.13', 0x624f14, 0x6250d8, 0x62529c, 0x553068),
])
def test_real_stock_setter_guards_and_position_independent_prologues(harness, tmp_path, version, low, high, get_value, brightness):
    vendor = Path(os.environ.get('WMP_VENDOR_ROOT', str(ROOT / 'analysis')))
    elf = vendor / f'fw_{version}_payload/root/home/t13dp/TM_T1/bin/client'
    if not elf.exists():
        pytest.skip('local vendor binary required')
    result = subprocess.check_output([str(harness), str(elf)], text=True)
    assert result.strip() == f'{version} {low:x} {high:x}'
    with elf.open('rb') as stream:
        for address in (low, high):
            stream.seek(address - 0x400000)
            # stp frame; mov frame; str x19; mov w1,0 -- safe in a trampoline.
            assert stream.read(16).hex() == 'fd7bbda9fd030091f30b00f901008052'
        for address, expected in [
            (get_value, 'fd7bb9a9fd030091f30b00f900008012'),
            (brightness, 'ff030bd1fd7b00a9fd030091f30b00f9'),
        ]:
            stream.seek(address - 0x400000)
            assert stream.read(16).hex() == expected
    symbols = subprocess.check_output(['nm', str(elf)], text=True)
    assert '000000000386ce2c B led_on' in symbols
    changed = tmp_path / 'modified-client'
    shutil.copyfile(elf, changed)
    with changed.open('r+b') as stream:
        stream.seek(low - 0x400000)
        stream.write(b'\0')
    assert subprocess.run([str(harness), str(changed)]).returncode == 3

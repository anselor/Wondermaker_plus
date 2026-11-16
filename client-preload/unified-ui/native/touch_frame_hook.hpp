// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// Interior hook for the hash-bound 1.1.13 evdev_read loop at 0x73ca58.
// Entered by a jump with the factory stack frame intact, never by a C call.
// Keep the factory parser, coordinate clamping and keypad behavior. For pointer
// SYN_REPORT only, publish the complete frame and tell LVGL to read again after
// processing it. Otherwise a queued press+release collapses to released and the
// tap disappears. The pinned _lv_indev_read zeros all 24 output bytes per read;
// lv_indev_read_timer_cb consumes continue_reading at offset 20 after dispatch.
#if defined(__aarch64__)
extern "C" void unified_evdev_frame();
__asm__(
 ".pushsection .text\n"
 ".balign 4\n"
 ".global unified_evdev_frame\n"
 ".hidden unified_evdev_frame\n"
 ".type unified_evdev_frame, %function\n"
 "unified_evdev_frame:\n"
 "ldrh w0, [sp, #0x38]\n" // input_event.type
 "cbnz w0, .Lwmp_touch_original\n"
 "ldrh w1, [sp, #0x3a]\n" // SYN_REPORT == 0
 "cbnz w1, .Lwmp_touch_original\n"
 "ldr x1, [sp, #0x18]\n" // lv_indev_drv_t*
 "ldr w1, [x1]\n"
 "cmp w1, #1\n" // LV_INDEV_TYPE_POINTER
 "b.ne .Lwmp_touch_original\n"
 "ldr x1, [sp, #0x10]\n" // lv_indev_data_t*
 "mov w0, #1\n"
 "strb w0, [x1, #20]\n"
 "ldr x16, .Lwmp_touch_finish\n"
 "br x16\n"
 ".Lwmp_touch_original:\n"
 // Reproduce the four displaced instructions, relocating their conditional
 // branch. No stack/register preservation is lost on either continuation.
 "ldrh w0, [sp, #0x38]\n"
 "cmp w0, #2\n"
 "b.ne .Lwmp_touch_nonrelative\n"
 "ldrh w0, [sp, #0x3a]\n"
 "ldr x16, .Lwmp_touch_relative\n"
 "br x16\n"
 ".Lwmp_touch_nonrelative:\n"
 "ldr x16, .Lwmp_touch_absolute\n"
 "br x16\n"
 ".balign 8\n"
 ".Lwmp_touch_finish: .quad 0x73cdac\n"
 ".Lwmp_touch_relative: .quad 0x73ca68\n"
 ".Lwmp_touch_absolute: .quad 0x73cac4\n"
 ".size unified_evdev_frame, .-unified_evdev_frame\n"
 ".popsection\n"
);
#else
// Host bootstrap tests never execute ARM interior hooks.
extern "C" inline void unified_evdev_frame() {}
#endif

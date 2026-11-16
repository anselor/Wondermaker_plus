#!/usr/bin/env python3
"""Generate reviewed 1.1.13 native entry windows from the known stock ELF."""
import hashlib
from pathlib import Path
import subprocess
import sys
import json
CLIENT_SHA='b60c96c5caf980a127a3d284e5ac98e799dfd79691cb1a52aafd06fd818c4715'
NAMES='''lv_font_montserrat_14 lv_obj_set_width lv_img_get_src lv_img_src_get_type lv_img_decoder_get_info lv_obj_check_type lv_img_class lv_obj_get_width lv_obj_get_height lv_textarea_add_text lv_textarea_del_char lv_async_call lv_obj_get_event_user_data lv_obj_remove_event_cb lv_textarea_set_text lv_textarea_get_text lv_obj_add_style lv_obj_clear_state lv_dropdown_create lv_dropdown_set_options lv_dropdown_set_selected lv_dropdown_get_selected lv_dropdown_is_open lv_dropdown_get_list lv_dropdown_close lv_imgbtn_set_src lv_img_create lv_img_set_src lv_img_set_zoom lv_img_set_pivot lv_obj_create lv_btn_create lv_label_create lv_label_set_text lv_label_set_long_mode
lv_obj_align lv_obj_get_content_width lv_obj_get_content_height lv_obj_set_pos lv_obj_set_size lv_obj_add_flag lv_obj_clear_flag lv_obj_add_state lv_obj_clear_state
lv_obj_set_scroll_dir lv_obj_set_scrollbar_mode lv_obj_get_scroll_y lv_obj_scroll_to_y
lv_obj_get_parent lv_obj_get_child lv_obj_get_child_cnt lv_obj_is_valid lv_obj_has_flag lv_obj_has_state
lv_obj_move_to_index lv_obj_del lv_obj_clean lv_obj_add_event_cb lv_event_get_code
lv_event_get_user_data lv_event_get_target lv_event_send lv_indev_get_act lv_indev_get_scroll_obj
lv_disp_get_default lv_disp_get_scr_act lv_disp_get_layer_top lv_disp_get_layer_sys lv_obj_get_coords lv_obj_get_content_coords
lv_obj_set_style_img_recolor lv_obj_set_style_img_recolor_opa lv_obj_remove_style lv_obj_set_style_bg_color lv_obj_set_style_bg_opa
lv_obj_set_style_text_color lv_obj_set_style_text_font lv_obj_set_style_text_align lv_obj_set_style_text_opa
lv_obj_set_style_radius lv_obj_set_style_border_width lv_obj_set_style_border_color
lv_obj_set_style_pad_top lv_obj_set_style_pad_bottom lv_obj_set_style_pad_left lv_obj_set_style_pad_right
lv_obj_set_style_outline_width lv_obj_set_style_opa lv_obj_update_layout
'''.split()
def main():
 path=Path(sys.argv[1]);data=path.read_bytes()
 if hashlib.sha256(data).hexdigest()!=CLIENT_SHA:raise SystemExit('Unsupported client; refusing to regenerate profile')
 symbols={}
 for line in subprocess.check_output(['nm','-n',str(path)],text=True).splitlines():
  fields=line.split()
  if len(fields)==3 and fields[2] in NAMES:symbols[fields[2]]=int(fields[0],16)
 if set(NAMES)!=set(symbols):raise SystemExit('Missing symbols: '+str(set(NAMES)-set(symbols)))
 symbols.update({"popup_build":0x532da8,"popup_event":0x5303e4,"resume_prepare":0x51a7b4,"runout_purge":0x5328b4,"resume_check":0x61b2c4,"draw_pop":0x5352e0})
 symbols.update({"setup_calibration":0x4b6470,"command_sender":0x614338,"pid_tool_sender_call":0x4b7cb4,"maintenance_event":0x4b4768,"nozzle_flow_event":0x529218,"setup_about":0x4b0510,"filament_guide_event":0x50c9bc,"setup_filament_guide":0x50d044,"guide_load_worker":0x50e83c,"guide_retry_worker":0x50ecf0,"text_key_user_data":0x54d890,"draw_text_keyboard":0x54ec48,"create_text_keys":0x54e654,"text_key_event":0x54db20,"schedule_preview_metadata":0x539474,"loading_popup":0x535958,"preview_metadata":0x538c7c,"preview_event":0x536958,"preview_refresh_event":0x5376d0,"draw_colour_picker":0x4f82a8,"draw_number_keyboard":0x52e418,"number_key_event":0x52da0c,"number_text_event":0x52db58,"main_event":0x519a34,"page_to":0x553b6c,"draw_preview":0x537710,"setup_filament":0x4f6dec,"filament_event":0x4f667c,"material_pick":0x4f86b8,"colour_pick":0x4f8020})
 symbols.update({"calibration_sender_0":0x4b7824,"calibration_sender_1":0x4b7a18,"calibration_sender_2":0x4b7a68,"calibration_sender_3":0x4b7bc8,"calibration_sender_4":0x4b7c04,"calibration_sender_5":0x4b7c40,"calibration_sender_6":0x4b7cb4,"calibration_sender_7":0x4b7cf0,"calibration_sender_8":0x4b7d8c,"calibration_sender_9":0x4b7df4,"calibration_sender_10":0x4b7fb8,"calibration_sender_11":0x4b80b4,"calibration_sender_12":0x4b82e0,"calibration_sender_13":0x4b8428,"calibration_sender_14":0x4b8478,"calibration_sender_15":0x4b8698})
 symbols.update({'guide_calibration_sender_0': 5283764, 'guide_calibration_sender_1': 5283940, 'guide_calibration_sender_2': 5284816, 'guide_calibration_sender_3': 5284932, 'guide_calibration_sender_4': 5285108, 'guide_calibration_sender_5': 5285996, 'guide_calibration_sender_6': 5286056, 'guide_calibration_sender_7': 5286144, 'guide_calibration_sender_8': 5286244, 'guide_calibration_sender_9': 5286308, 'guide_calibration_sender_10': 5286464, 'guide_calibration_sender_11': 5286616, 'guide_calibration_sender_12': 5286792, 'guide_calibration_sender_13': 5287796, 'guide_calibration_sender_14': 5288132, 'guide_calibration_sender_15': 5288240})
 symbols.update({'identification_tool_sender_call':0x510958, 'setup_identification':0x52a4cc, 'identification_event':0x52a1e4, 'identification_worker':0x510350, 'setup_guide_identification':0x50fb98, 'guide_identification_refresh':0x5100c8})
 symbols.update({"startup_shell":0x64fc84,"startup_restart_argument":0x44a434,"startup_restart_call":0x44a450})
 symbols.update({"startup_discovery_argument":0x44a284})
 symbols.update({"exclude_object":0x545924,"is_last_remaining_object":0x545598,"exclude_stop_call":0x545a94})
 symbols.update({"knife_event":0x4c6490,"factory_reset":0x548078,"factory_event":0x4c41a4,"factory_probe_event":0x4c76dc,"maintenance_probe_event":0x53d150})
 symbols.update({"evdev_frame_dispatch":0x73ca58,"evdev_frame_finish":0x73cdac,
                 "indev_read_zero":0x6c4398,"indev_continue_capture":0x698f90,
                 "indev_continue_loop":0x699124})
 symbols.update({'maintenance_calibration_worker':0x4b7558})
 rows=[];header=['// Generated from verified stock 1.1.13 ELF. SPDX-License-Identifier: GPL-3.0-or-later','#pragma once','#include <cstdint>','namespace wmp_ui { namespace native {','struct Window {std::uintptr_t address;unsigned char bytes[32];};']
 for name,address in symbols.items():
  raw=data[address-0x400000:address-0x400000+32];rows.append({'name':name,'address':hex(address),'bytes':raw.hex()})
  header.append('constexpr std::uintptr_t '+name+' = '+hex(address)+';')
 header.append('static const Window windows[] = {')
 for row in rows:header.append('{'+row['address']+', {'+','.join('0x'+row['bytes'][i:i+2] for i in range(0,64,2))+'}},')
 header.extend(['};','}}'])
 root=Path(__file__).resolve().parent
 (root/'profile1113.hpp').write_text('\n'.join(header)+'\n')
 (root/'profile1113.json').write_text(json.dumps({'client_sha256':CLIENT_SHA,'functions':rows},indent=2)+'\n')
if __name__=='__main__':main()

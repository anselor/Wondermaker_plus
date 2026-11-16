"""Host checks for the shared C++ UI; no printer or native activation."""
from pathlib import Path
import json
import subprocess
import shutil
import pytest
ROOT = Path(__file__).resolve().parents[1]
UI = ROOT/'client-preload/unified-ui'
VENDOR = ROOT/'client-preload/openace-compat/screen1113/source/vendor'


def test_browser_preview_retains_controls_on_data_sync():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js is required for the browser preview DOM model')
    subprocess.run([node, str(ROOT/'tests/unified_ui/preview_dom.cjs'),
                    str(UI/'preview.html')], check=True, timeout=15)


def compile_cpp(source, destination, includes=()):
    subprocess.run(['g++', '-std=c++11', '-Wall', '-Wextra', '-Werror', '-pthread', '-I'+str(UI), '-I'+str(VENDOR), *('-I'+str(path) for path in includes), str(source), '-o', str(destination)], check=True)


def test_setup_completion_durability(tmp_path):
    executable = tmp_path/'setup-completion'
    compile_cpp(ROOT/'tests/unified_ui/setup_completion.cpp', executable)
    subprocess.run([str(executable), str(tmp_path)], check=True, timeout=15)


def test_recovery_retirement_review_and_readback(tmp_path):
    executable = tmp_path/'recovery-retirement'
    compile_cpp(ROOT/'tests/unified_ui/recovery_retirement.cpp', executable)
    subprocess.run([str(executable)], check=True, timeout=15)


def test_legacy_overlay_sync_preserves_widgets_and_press_identity(tmp_path):
    executable = tmp_path/'legacy-sync'
    subprocess.run(['g++', '-std=c++11', '-Wall', '-Wextra', '-Werror',
                    '-I'+str(VENDOR),
                    '-I'+str(ROOT/'client-preload/openace-compat/screen1113/source/client'),
                    str(ROOT/'tests/unified_ui/legacy_sync.cpp'), '-o', str(executable)], check=True)
    subprocess.run([str(executable)], check=True, timeout=15)


def test_controller_boundaries(tmp_path):
    executable=tmp_path/'controller'
    compile_cpp(ROOT/'tests/unified_ui/controller.cpp', executable)
    subprocess.run([str(executable), str(UI/'fixture.json')], check=True)


def test_usb_copy_reservation_and_result_binding(tmp_path):
    executable = tmp_path/'usb-import'
    compile_cpp(ROOT/'tests/unified_ui/usb_import.cpp', executable)
    subprocess.run([str(executable)], check=True)


def test_usb_copy_worker_does_not_block_ui_or_reuse_origin(tmp_path):
    executable = tmp_path/'usb-copy-worker'
    compile_cpp(ROOT/'tests/unified_ui/usb_copy_worker.cpp', executable)
    subprocess.run([str(executable)], check=True, timeout=15)


@pytest.fixture(scope='module')
def host(tmp_path_factory):
    executable=tmp_path_factory.mktemp('unified-ui')/'host'
    compile_cpp(UI/'host.cpp', executable)
    return executable


def run_flow(host, events, fixture=None):
    requests=[{'snapshot':fixture or json.loads((UI/'fixture.json').read_text())}]
    requests += [{'event':e} for e in events]
    result=subprocess.run([str(host)], input=''.join(json.dumps(r)+'\n' for r in requests), text=True, capture_output=True, check=True)
    frames=[json.loads(line) for line in result.stdout.splitlines()]
    assert all('error' not in frame for frame in frames), frames
    return frames


def test_standalone_filaments_are_four_equal_external_cards(host):
    fixture=json.loads((UI/'fixture.json').read_text())
    fixture['owner']='standalone'
    # Keep stale ACE records to ensure presentation is gated by ownership, not
    # merely by whether a cached unit/discovery array happens to be empty.
    frames=run_flow(host,['nav:filaments','edit:external:h2','back','nav:tools'],fixture)
    view=frames[1]
    widgets={w['id']:w for w in view['widgets']}
    assert widgets['title']['text']=='Filaments'
    assert 'nav:adopt' not in widgets
    assert not any(key.startswith(('head:', 'unit:', 'edit:ace-')) for key in widgets)
    cards=[widgets[f'edit:external:h{i}'] for i in range(4)]
    assert [w['x'] for w in cards]==[100,269,438,607]
    assert all(w['y']==166 and w['h']==236 and not w['faded'] and w['enabled'] for w in cards)
    assert frames[2]['page']=='identity'
    assert frames[3]['page']=='filaments'
    assert next(w for w in frames[4]['widgets'] if w['id']=='nav:filaments' and w['y']==431)['text']=='Filaments'


@pytest.mark.parametrize('events,page,modal', [
    (['home-head:h1'],'tools',''),
    (['nav:filaments','unit:ace-1','assign:ace-1:0'],'unit','assign'),
    (['nav:filaments','unit:ace-1','unit-name'],'unit','keyboard'),
    (['nav:filaments','edit:ace-1:0'],'identity',''),
    (['nav:filaments','nav:adopt','adopt:usb-new-3'],'adopt','adopt'),
    (['nav:filaments','unit:ace-1','remove'],'unit','remove'),
    (['nav:filaments','nav:import','import-usb'],'import','import-file'),
    (['nav:tools','head:h1','load'],'tools','load-source'),
    (['nav:tools','head:h1','load','load-source:external:h1'],'tools','external-load'),
    (['nav:tools','unload'],'tools','procedure'),
    (['nav:tools','temperature'],'tools','keypad'),
    (['nav:files','file:demo-file','map:0'],'preview','sources'),
    (['nav:files','file:demo-file','thumbnail'],'preview','thumbnail'),
    (['nav:filaments','settings:XYZ'],'retained',''),
])
def test_all_screen_entry_paths(host,events,page,modal):
    frame=run_flow(host,events)[-1]
    assert (frame['page'],frame['modal'])==(page,modal)
    for w in frame['widgets']:
        assert 0 <= w['x'] < w['x']+w['w'] <= 800
        assert 0 <= w['y'] < w['y']+w['h']
        if not w.get('parent'): assert w['y']+w['h'] <= 480


def test_disabled_actions_cannot_be_dispatched(host):
    frames=run_flow(host,['nav:tools','extrude','retract','off'])
    for frame in frames[1:]:
        assert frame['page']=='tools' and frame['modal']==''
        assert not any(w['busy'] for w in frame['widgets'])


def test_paused_recovery_origin_and_stub(host):
    fixture=json.loads((UI/'fixture.json').read_text());fixture['job']['state']='paused'
    frame=run_flow(host,['nav:job','recovery','prepare'],fixture)[-1]
    assert frame['page']=='recovery'
    assert next(w for w in frame['widgets'] if w['id']=='prepare')['enabled'] is False


def test_modal_prevents_background_navigation(host):
    frame=run_flow(host,['nav:filaments','unit:ace-1','quick-all','nav:home','nav:files'])[-1]
    assert (frame['page'],frame['modal'])==('unit','discard')


def test_openace_typed_adapter(tmp_path):
    executable=tmp_path/'backend'
    compile_cpp(ROOT/'tests/unified_ui/backend.cpp', executable)
    subprocess.run([str(executable), str(ROOT/'client-preload/openace-compat/screen1113/fixtures/management_structured1080.json')], check=True)


def test_ace_list_is_native_scroll_container_not_pagination(host):
    frame=run_flow(host,['nav:filaments'])[-1]
    widgets=frame['widgets']
    assert next(w for w in widgets if w['id']=='source-scroll')['kind']=='scroll'
    assert not any(w['id'] in ('scroll-next','scroll-prev') for w in widgets)
    for unit in ('ace-1','ace-2'):
        assert next(w for w in widgets if w['id']=='unit:'+unit)['parent']=='source-scroll'
        assert next(w for w in widgets if w['id']=='edit:'+unit+':3')['parent']=='source-scroll'


def test_native_runtime_compiles(tmp_path):
    source=tmp_path/'native.cpp'
    source.write_text('#include "native/runtime.hpp"\nint main(){return 0;}\n')
    compile_cpp(source,tmp_path/'native')


def test_profile_matches_stock_binary_when_available():
    import hashlib
    binary=ROOT/'analysis/fw_1.1.13_payload/root/home/t13dp/TM_T1/bin/client'
    if not binary.exists(): pytest.skip('local firmware analysis file is not distributed')
    data=binary.read_bytes()
    profile=json.loads((UI/'native/profile1113.json').read_text())
    assert hashlib.sha256(data).hexdigest()==profile['client_sha256']
    for row in profile['functions']:
        offset=int(row['address'],16)-0x400000
        assert data[offset:offset+32].hex()==row['bytes']


def test_real_status_projection(tmp_path):
    executable=tmp_path/'projection'
    compile_cpp(ROOT/'tests/unified_ui/projection.cpp', executable)
    subprocess.run([str(executable), str(ROOT/'client-preload/openace-compat/screen1113/fixtures/management_structured1080.json')], check=True)


def test_native_lvgl_lifetimes_and_scroll(tmp_path):
    executable=tmp_path/'native-lifecycle'
    compile_cpp(ROOT/'tests/unified_ui/native_lifecycle.cpp', executable, includes=(VENDOR.parent/'client',))
    subprocess.run([str(executable), str(UI/'fixture.json'), str(ROOT/'client-preload/openace-compat/screen1113/fixtures/management_structured1080.json')], check=True)


def test_standalone_heater_delivery_and_readback(tmp_path):
    executable=tmp_path/'standalone'
    compile_cpp(ROOT/'tests/unified_ui/standalone.cpp', executable)
    subprocess.run([str(executable)], check=True)


def test_native_file_metadata_preview(tmp_path):
    executable=tmp_path/'preview'
    compile_cpp(ROOT/'tests/unified_ui/preview.cpp', executable)
    subprocess.run([str(executable)], check=True)


def test_native_thumbnail_bounds_and_cache(tmp_path):
    import base64
    root=tmp_path/'gcodes'
    thumbs=root/'folder/.thumbs'
    thumbs.mkdir(parents=True)
    png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aKx8AAAAASUVORK5CYII=')
    (thumbs/'image.png').write_bytes(png)
    outside=tmp_path/'outside.png'
    outside.write_bytes(png)
    (thumbs/'escape.png').symlink_to(outside)
    huge=bytearray(png)
    huge[16:20]=(100000).to_bytes(4,'big')
    (thumbs/'oversized.png').write_bytes(huge)
    (thumbs/'bad.png').write_bytes(b'not an image'*10)
    executable=tmp_path/'thumbnail'
    compile_cpp(ROOT/'tests/unified_ui/thumbnail.cpp', executable)
    subprocess.run([str(executable), str(root)], check=True)


def test_native_filament_procedure_review(tmp_path):
    executable = tmp_path / 'filament-procedure-review'
    compile_cpp(ROOT / 'tests/unified_ui/filament_procedure_review.cpp', executable)
    subprocess.run([str(executable)], check=True)


def test_recovery_retained_without_legacy_setup(tmp_path):
    executable = tmp_path/'recovery-ownership'
    client = ROOT/'client-preload/openace-compat/screen1113/source/client'
    subprocess.run(['g++', '-std=c++11', '-Wall', '-Wextra', '-Werror', '-pthread',
                    '-I'+str(client), '-I'+str(VENDOR),
                    str(ROOT/'tests/unified_ui/recovery_ownership.cpp'),
                    '-o', str(executable)], check=True)
    subprocess.run([str(executable)], check=True)


def test_real_loopback_transport_allows_only_explicit_cancel_route(tmp_path):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    import time
    executable = tmp_path/'loopback-cancel'
    compile_cpp(ROOT/'tests/unified_ui/loopback_cancel.cpp', executable)
    received = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self):
            if self.path == '/server/files/roots':
                self.send_response(503)
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            time.sleep(1.15 if self.path.endswith('?webhooks') else 2.1)
            payload = b'{"result":"ok"}'
            try:
                self.send_response(200)
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                pass  # Expected when the bounded client has already timed out.
        def do_POST(self):
            data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            received.append((self.path, data))
            if self.path == '/server/jsonrpc':
                assert data['jsonrpc'] == '2.0'
                assert data['method'] == 'printer.gcode.script'
                script = data['params']['script']
                if script == 'DROP':
                    self.close_connection = True
                    return
                status, reply = 200, {'jsonrpc': '2.0', 'id': 1, 'result': 'ok'}
                if script == 'ERROR':
                    reply = {'jsonrpc': '2.0', 'id': 1, 'error': {'code': 400, 'message': 'Heat the selected nozzle\n'}}
                elif script == 'WRONG_ID':
                    reply['id'] = 2
                elif script == 'BOTH':
                    reply['error'] = {'code': 400, 'message': 'bad'}
                elif script == 'BAD_ERROR':
                    reply = {'jsonrpc': '2.0', 'id': 1, 'error': 'bad'}
            elif data:
                status, reply = 200, {'result': {**data, 'state': 'requested'}}
            else:
                status, reply = 400, {'error': {'message': 'Filament operation changed'}}
            payload = json.dumps(reply).encode()
            self.send_response(status)
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
    with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            subprocess.run([str(executable), str(server.server_port)], check=True, timeout=20)
        finally:
            server.shutdown()
            thread.join()
    assert received == [
        ('/printer/wmp/recovery/review', {'id': 'running-1', 'session': 'session-1', 'head': 'h2'}),
        ('/printer/wmp/recovery/resolve_review', {'id': 'running-1', 'session': 'session-1', 'head': 'h2'}),
        ('/printer/wmp/recovery/retire_review', {'id': 'running-1', 'session': 'session-1', 'head': 'h2'}),
        ('/printer/wmp/recovery/retire_result', {'id': 'running-1', 'session': 'session-1', 'head': 'h2'}),
        ('/printer/wmp/recovery/stop', {'id': 'running-1', 'session': 'session-1', 'head': 'h2'}),
        ('/printer/wmp/print/cancel_review', {'id': 'running-1', 'session': 'session-1', 'head': 'h2'}),
        ('/printer/wmp/print/cancel', {'id': 'running-1', 'session': 'session-1', 'head': 'h2'}),
        ('/printer/wmp/print/cancel_resolve_review', {'id': 'running-1', 'session': 'session-1', 'head': 'h2'}),
        ('/printer/wmp/filament/cancel', {'id': 'running-1', 'session': 'session-1', 'head': 'h2'}),
        ('/printer/wmp/filament/cancel', {}),
        ('/printer/wmp/probe_editor/stop', {'session': 'session-1', 'request': 'probe-1'}),
        ('/printer/wmp/probe_editor/stop', {}),
    ] + [('/server/jsonrpc', {'jsonrpc': '2.0', 'method': 'printer.gcode.script',
                            'params': {'script': script}, 'id': 1})
         for script in ['M105', 'ERROR', 'WMP_RECOVERY_CONTINUE REQUEST=' + 'a' * 2200, 'WMP_RETIRE_RECOVERY REQUEST=' + 'a' * 2200, 'WRONG_ID', 'BOTH', 'BAD_ERROR', 'DROP']]


def test_recovery_request_retains_native_selection_and_execution_binding(tmp_path):
    executable = tmp_path / 'recovery-request'
    compile_cpp(ROOT/'tests/unified_ui/recovery_request.cpp', executable)
    subprocess.run([str(executable)], check=True, timeout=15)


def test_recovery_worker_keeps_status_and_stop_available_during_command_wait(tmp_path):
    executable = tmp_path / 'recovery-worker'
    compile_cpp(ROOT/'tests/unified_ui/recovery_worker.cpp', executable)
    subprocess.run([str(executable)], check=True, timeout=15)


def test_recovery_resolution_requires_separate_review_and_confirmation(tmp_path):
    executable = tmp_path/'recovery-resolution'
    compile_cpp(ROOT/'tests/unified_ui/recovery_resolution.cpp', executable)
    subprocess.run([str(executable)], check=True, timeout=15)


def test_print_cancel_worker_uses_independent_reviewed_intent_and_authoritative_receipts(tmp_path):
    executable = tmp_path/'print-cancel-worker'
    compile_cpp(ROOT/'tests/unified_ui/print_cancel_worker.cpp', executable)
    subprocess.run([str(executable)], check=True, timeout=15)


def test_print_cancel_resolution_requires_review_and_retains_bound_receipts(tmp_path):
    executable = tmp_path/'print-cancel-resolution'
    compile_cpp(ROOT/'tests/unified_ui/print_cancel_resolution.cpp', executable)
    subprocess.run([str(executable)], check=True)


def test_stock_remote_start_mapping_backup_boundary(tmp_path):
    import hashlib
    client = ROOT/'analysis/fw_1.1.13_payload/root/home/t13dp/TM_T1/bin/client'
    if not client.exists():
        pytest.skip('local firmware analysis file is not distributed')
    binary = client.read_bytes()
    assert hashlib.sha256(binary).hexdigest() == 'b60c96c5caf980a127a3d284e5ac98e799dfd79691cb1a52aafd06fd818c4715'
    # The sole sender call in the reviewed remote-start loop, with return PC.
    address = 0x63dc1c
    word = int.from_bytes(binary[address-0x400000:address-0x400000+4], 'little')
    assert word >> 26 == 0b100101
    offset = word & 0x3ffffff
    if offset & 0x2000000:
        offset -= 0x4000000
    assert address + offset*4 == 0x614338
    executable = tmp_path/'mapping-backup'
    compile_cpp(ROOT/'tests/unified_ui/stock_mapping_backup.cpp', executable)
    subprocess.run([str(executable)], check=True, timeout=15)

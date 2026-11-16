#!/usr/bin/env python3
"""Local-only preview of the actual C++ screen controller. No printer connection."""
import argparse
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import subprocess
import signal
import tempfile
ROOT = Path(__file__).resolve().parent
VENDOR = ROOT.parent / 'openace-compat/screen1113/source/vendor'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8766)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='wmp-ui-') as work:
        binary = Path(work) / 'ui'
        subprocess.run(['g++', '-std=c++11', '-Wall', '-Wextra', '-I'+str(VENDOR), str(ROOT/'host.cpp'), '-o', str(binary)], check=True)
        process = subprocess.Popen([str(binary)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        def exchange(request):
            process.stdin.write(json.dumps(request)+'\n')
            process.stdin.flush()
            return process.stdout.readline().encode()
        fixture = json.loads((ROOT/'fixture.json').read_text())
        exchange({'snapshot': fixture})
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def send(self, body, content_type):
                self.send_response(200)
                self.send_header('Content-Type', content_type)
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(body)
            def do_GET(self):
                if self.path == '/': self.send((ROOT/'preview.html').read_bytes(), 'text/html; charset=utf-8')
                elif self.path == '/state': self.send(exchange({}), 'application/json')
                else: self.send_error(404)
            def do_POST(self):
                nonlocal process
                if self.path != '/event': return self.send_error(404)
                # Loopback is not authentication: require same-origin requests.
                if self.headers.get('Origin') != f'http://127.0.0.1:{args.port}': return self.send_error(403)
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 2048: return self.send_error(400)
                try:
                    request = json.loads(self.rfile.read(length))
                    if 'scenario' in request:
                        current = json.loads(json.dumps(fixture))
                        scenario = request['scenario']
                        if scenario == 'standalone':
                            current['owner']='standalone';current['units']=[];current['candidates']=[]
                            current['sources']=[s for s in current['sources'] if s['kind']=='external']
                            for h in current['heads']: h['loaded']={'state':'empty'}
                            current['routes']=[]
                        elif scenario == 'zero':
                            current['units']=[];current['candidates']=[]
                            current['sources']=[s for s in current['sources'] if s['kind']=='external']
                            current['routes']=[]
                            for h in current['heads']: h['loaded']={'state':'empty'}
                        elif scenario == 'stale': current['fresh']=False
                        elif scenario == 'paused': current['job']['state']='paused'
                        elif scenario == 'disconnected':
                            for u in current['units']: u['connected']=False
                            for s in current['sources']: s['available']=False
                        elif scenario != 'openace': return self.send_error(400)
                        # A scenario switch represents another printer: reset the UI.
                        process.stdin.close();process.terminate();process.wait()
                        process = subprocess.Popen([str(binary)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
                        body=exchange({'snapshot':current})
                    else: body=exchange({'event':request.get('event','')})
                    self.send(body, 'application/json')
                except (ValueError, KeyError): self.send_error(400)
        server = HTTPServer(('127.0.0.1', args.port), Handler)
        print(f'WM+ C++ screen preview: http://127.0.0.1:{args.port} (fixture data; no printer connection)', flush=True)
        def stop(signum, frame):
            raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, stop)
        try: server.serve_forever()
        except KeyboardInterrupt: pass
        finally:
            server.server_close();process.terminate();process.wait()

if __name__ == '__main__': main()

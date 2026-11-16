from pathlib import Path
import json,subprocess,socketserver,threading,time
import pytest
ROOT=Path(__file__).resolve().parents[1]
@pytest.fixture(scope='module')
def binary():
 out=ROOT/'build/http-worker'
 subprocess.run(['g++','-std=c++11','-Wall','-Wextra','-Werror','-O1','-pthread','-I'+str(ROOT/'source/client'),'-I'+str(ROOT/'source/vendor'),str(ROOT/'tests/http_worker.cpp'),'-o',str(out)],check=True)
 return out
@pytest.mark.parametrize('mode',['normal','absent','malformed','oversized','drip','post_unknown'])
def test_local_worker_http_is_bounded_selective_and_never_replays(binary,mode):
 observed=[]
 status=json.loads((ROOT/'fixtures/pending_compact.json').read_text())
 selected={k:status[k] for k in ('session_id','material_change_prompt','loaded')}
 class Handler(socketserver.StreamRequestHandler):
  def handle(self):
   line=self.rfile.readline().decode();headers={}
   while True:
    row=self.rfile.readline().decode()
    if row in ('\r\n',''):break
    k,v=row.split(':',1);headers[k.lower()]=v.strip()
   body=self.rfile.read(int(headers.get('content-length',0)))
   observed.append((line,body))
   if line.startswith('GET '):
    assert line=='GET /printer/objects/query?openace=session_id,material_change_prompt,loaded,manual_flow HTTP/1.0\r\n'
    payload=json.dumps({'result':{'status':{} if mode=='absent' else {'openace':selected}}}).encode()
    if mode=='malformed':payload=b'{broken'
    if mode=='oversized':payload=b'x'*262145
    if mode=='drip':
     try:
      self.wfile.write(b'HTTP/1.0 200 OK\r\nContent-Length: 100\r\n\r\n');self.wfile.flush()
      for _ in range(12):self.wfile.write(b'x');self.wfile.flush();time.sleep(.025)
     except (BrokenPipeError,ConnectionResetError):pass
     return
   else:
    assert line=='POST /printer/gcode/script HTTP/1.0\r\n'
    command=json.loads(body)['script']
    assert command=='OPENACE_CONFIRM_CHANGE TOOL=0 CONFIRM=1 EXPECT_CONTEXT='+status['material_change_prompt']['confirmation']['context']
    if mode=='post_unknown':return
    payload=b'{"result":"ok"}'
   self.wfile.write(b'HTTP/1.0 200 OK\r\nContent-Length: '+str(len(payload)).encode()+b'\r\n\r\n'+payload)
 class Server(socketserver.ThreadingTCPServer):daemon_threads=True;allow_reuse_address=True
 with Server(('127.0.0.1',0),Handler) as server:
  thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  start=time.monotonic()
  result=json.loads(subprocess.check_output([str(binary),str(server.server_address[1]),'confirm'],text=True,timeout=2))
  elapsed=time.monotonic()-start;server.shutdown();thread.join()
 assert elapsed<1,elapsed
 posts=[x for x in observed if x[0].startswith('POST')]
 if mode in ('normal','post_unknown'):
  assert len(posts)==1 and result['visible'] and not result['approved'] and not result['confirm_enabled']
 else:assert not posts and not result['confirm_enabled']
 if mode in ('malformed','oversized','drip','post_unknown'):assert not result['current']
 if mode=='absent':assert not result['visible']

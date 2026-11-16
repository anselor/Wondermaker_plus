from pathlib import Path
import subprocess,json,socketserver,threading
ROOT=Path(__file__).resolve().parents[1]
def build(name):
 out=ROOT/('build/'+name)
 subprocess.run(['g++','-std=c++11','-Wall','-Wextra','-Werror','-pthread','-I'+str(ROOT/'source/client'),'-I'+str(ROOT/'source/vendor'),str(ROOT/('tests/'+name+'.cpp')),'-o',str(out)],check=True)
 return out

def test_unchanged_root_error_and_actual_native_visible_literal_reason():
 fixture=ROOT/'fixtures/management_zero1078.json'
 subprocess.run([str(build('root_management_error')),str(fixture)],check=True)
 subprocess.run([str(build('management_errors')),str(fixture)],check=True)

def test_actual_loopback_http400_preserves_bounded_backend_reason():
 binary=build('management_errors');status=json.loads((ROOT/'fixtures/management_zero1078.json').read_text());posts=[]
 class Handler(socketserver.StreamRequestHandler):
  def handle(self):
   line=self.rfile.readline();headers={}
   while True:
    row=self.rfile.readline()
    if row in (b'\r\n',b''):break
    k,v=row.split(b':',1);headers[k.lower()]=v.strip()
   self.rfile.read(int(headers.get(b'content-length',b'0')))
   if line.startswith(b'GET '):payload=json.dumps({'result':{'status':{'openace':status}}}).encode();code=b'200 OK'
   else:posts.append(line);payload=json.dumps({'error':{'message':'head h0 is busy: qualification trial'}}).encode();code=b'400 Bad Request'
   self.wfile.write(b'HTTP/1.0 '+code+b'\r\nContent-Length: '+str(len(payload)).encode()+b'\r\n\r\n'+payload)
 class Server(socketserver.ThreadingTCPServer):allow_reuse_address=True;daemon_threads=True
 with Server(('127.0.0.1',0),Handler) as server:
  thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  text=subprocess.check_output([str(binary),'http',str(server.server_address[1])],text=True,timeout=3)
  server.shutdown();thread.join()
 assert 'qualification trial' in text and len(posts)==1

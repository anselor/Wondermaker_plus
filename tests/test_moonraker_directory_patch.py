import ast,asyncio,pathlib,os,shutil,json,types
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from moonraker_directory_patch import candidate, legacy_candidate
SOURCE = (Path(__file__).parent / 'fixtures/moonraker_directory_compat.py').read_text()
class Server:
 def error(self,message,*args):return ValueError(message)
class Request:
 def __init__(self,path,extended=False):self.path=path;self.extended=extended
 def get_str(self,*a):return self.path
 def get_boolean(self,*a):return self.extended
 def get_request_type(self):return 'GET'
def instance(source,root):
 tree=ast.parse(source);cls=next(x for x in tree.body if isinstance(x,ast.ClassDef) and x.name=='FileManager')
 names={'_handle_directory_request','_list_directory','_list_directory_async','_list_directory_chunks','get_path_info','check_reserved_path','list_dir'}
 cls.body=[x for x in cls.body if isinstance(x,(ast.FunctionDef,ast.AsyncFunctionDef)) and x.name in names]
 tree.body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),cls]
 ns=dict(os=os,shutil=shutil,pathlib=pathlib,asyncio=asyncio,RequestType=types.SimpleNamespace(GET='GET'),VALID_GCODE_EXTS={'.gcode'})
 exec(compile(ast.fix_missing_locations(tree),'file-manager-under-test','exec'),ns)
 obj=ns['FileManager']();obj.server=Server();obj.full_access_roots={'config','gcodes'};obj.file_paths={'config':str(root),'gcodes':str(root)}
 obj.reserved_paths={'hidden':(root/'secret',False),'readonly':(root/'readonly',True)}
 obj.gcode_metadata={'part.gcode':{'estimated_time':123,'filament_total':456}}
 obj.get_relative_path=lambda root,path:Path(path).name
 obj._convert_request_path=lambda path:('config',str(root))
 return obj
async def check_compatibility():
 import tempfile
 with tempfile.TemporaryDirectory() as d:
  root=Path(d);(root/'secret').mkdir();(root/'readonly').mkdir();(root/'.git').mkdir()
  for name in ['part.gcode','normal.txt','secret/private.txt','readonly/public.txt','.git/config']:(root/name).write_text('example')
  (root/'link.txt').symlink_to(root/'normal.txt');(root/'secret-link').symlink_to(root/'secret')
  old=instance(SOURCE,root)
  new=instance(candidate(SOURCE),root)
  count=0
  for r in ['config','gcodes','read_only_root']:
   for ext in [False,True]:
    a=old._list_directory(str(root),r,ext);b=await new._list_directory_async(str(root),r,ext)
    a.pop('disk_usage');b.pop('disk_usage');assert a==b;count+=1
  for path in [root,root/'normal.txt',root/'link.txt',root/'secret/private.txt',root/'readonly/public.txt',root/'.git/config',root/'missing']:
   for raise_error in [False,True]:
    results=[]
    for obj in [old,new]:
     try:results.append(obj.get_path_info(path,'config',raise_error))
     except Exception as e:results.append((type(e).__name__,str(e)))
    assert results[0]==results[1];count+=1
  for path in [root/'secret',root/'.git',root/'missing']:
   outcomes=[]
   for obj in [old,new]:
    try:
     if obj is old:obj._list_directory(str(path),'config')
     else:await obj._list_directory_async(str(path),'config')
    except Exception as e:outcomes.append((type(e).__name__,str(e)))
   assert len(outcomes)==2 and outcomes[0]==outcomes[1];count+=1
  for simple in [False,True]:
   a=old.list_dir('gcodes',simple);b=new.list_dir('gcodes',simple)
   if not simple:a.pop('disk_usage');b.pop('disk_usage')
   assert a==b;count+=1
  a=await old._handle_directory_request(Request('config'));b=await new._handle_directory_request(Request('config'))
  a.pop('disk_usage');b.pop('disk_usage');assert a==b;count+=1
  task=asyncio.create_task(new._list_directory_async(str(root),'config'));await asyncio.sleep(0);task.cancel()
  try:await task;raise AssertionError('Cancellation was ignored')
  except asyncio.CancelledError:count+=1
  assert count == 27

def test_directory_semantics_and_cancellation():
 asyncio.run(check_compatibility())

def test_patch_refuses_unknown_or_already_patched_source():
 import pytest
 with pytest.raises(ValueError):candidate(SOURCE.replace("permissions = \"rw\"", "permissions = \"r\""))
 with pytest.raises(ValueError):candidate(candidate(SOURCE))

def test_http_directory_listing_services_other_tasks_before_completion(tmp_path):
 for i in range(64): (tmp_path / str(i)).touch()
 async def measure(source):
  obj=instance(source,tmp_path);ticks=0;observed=[];done=False
  async def heartbeat():
   nonlocal ticks
   while not done:
    ticks+=1
    await asyncio.sleep(0)
  task=asyncio.create_task(heartbeat());await asyncio.sleep(0)
  get_info=obj.get_path_info
  def sample(*args):
   observed.append(ticks)
   return get_info(*args)
  obj.get_path_info=sample
  try:
   result=await obj._handle_directory_request(Request('config'))
   assert len(result['files'])==64
  finally:
   done=True
   await task
  return max(observed)-min(observed)
 assert asyncio.run(measure(SOURCE))==0
 assert asyncio.run(measure(candidate(SOURCE)))>0


def test_overlapping_scans_bound_work_between_status_callbacks(tmp_path):
 """Exercise real patched HTTP handlers, not just a lock helper.

 A per-entry cooperative scan is insufficient if every outstanding directory
 request performs an expensive entry before the next status callback runs.
 """
 import time
 for i in range(24):(tmp_path/str(i)).touch()
 async def measure(serialized):
  obj=instance(candidate(SOURCE),tmp_path)
  if not serialized:
   async def previous(path,root,is_extended=False):
    chunks=obj._list_directory_chunks(path,root,is_extended)
    while True:
     try:next(chunks)
     except StopIteration as result:return result.value
     await asyncio.sleep(0)
   obj._list_directory_async=previous
  count=0;previous_count=0;work=[];gaps=[];done=False
  original=obj.get_path_info
  def costly(*args):
   nonlocal count
   deadline=time.monotonic()+.002
   while time.monotonic()<deadline:pass
   count+=1
   return original(*args)
  obj.get_path_info=costly
  async def status_callback():
   nonlocal previous_count
   last=time.monotonic()
   while not done:
    await asyncio.sleep(.005)
    now=time.monotonic();gaps.append(now-last);last=now
    work.append(count-previous_count);previous_count=count
  timer=asyncio.create_task(status_callback())
  results=await asyncio.gather(*(obj._handle_directory_request(Request('config')) for _ in range(12)))
  done=True;await timer
  assert all(len(result['files'])==24 for result in results)
  # Median timer delay avoids treating an unrelated CI scheduler preemption
  # as directory work; the maximum work-count bound above is deterministic.
  return max(work),sorted(gaps)[len(gaps)//2]
 previous_work,previous_gap=asyncio.run(measure(False))
 current_work,current_gap=asyncio.run(measure(True))
 # Structural bound survives a slow CI host: less than one concurrent batch
 # of entry work can run between actual scheduled status callbacks.
 assert previous_work>=12 and current_work<12
 assert current_gap<previous_gap


def test_waiting_scan_reads_current_directory_and_distinct_result(tmp_path):
 (tmp_path/'original.txt').touch()
 async def run():
  obj=instance(candidate(SOURCE),tmp_path)
  lock=asyncio.Lock();obj._wmp_directory_scan_lock=lock
  await lock.acquire()
  pending=asyncio.create_task(obj._handle_directory_request(Request('config')))
  await asyncio.sleep(0)
  (tmp_path/'created-while-waiting.txt').write_text('new')
  lock.release()
  first=await pending
  assert {f['filename'] for f in first['files']}=={'original.txt','created-while-waiting.txt'}
  first['files'].clear()
  second=await obj._handle_directory_request(Request('config'))
  assert len(second['files'])==2
  assert not lock.locked()
 asyncio.run(run())


def test_scan_lock_releases_on_exception_owner_and_waiter_cancellation(tmp_path):
 import pytest
 for i in range(4):(tmp_path/str(i)).touch()
 async def run():
  obj=instance(candidate(SOURCE),tmp_path)
  original=obj.get_path_info
  def fail(*args):raise OSError('controlled metadata failure')
  obj.get_path_info=fail
  with pytest.raises(OSError,match='controlled metadata failure'):
   await obj._handle_directory_request(Request('config'))
  lock=obj._wmp_directory_scan_lock;assert not lock.locked()
  obj.get_path_info=original
  owner=asyncio.create_task(obj._handle_directory_request(Request('config')))
  await asyncio.sleep(0);assert lock.locked()
  waiter=asyncio.create_task(obj._handle_directory_request(Request('config')))
  await asyncio.sleep(0)
  waiter.cancel()
  with pytest.raises(asyncio.CancelledError):await waiter
  owner.cancel()
  with pytest.raises(asyncio.CancelledError):await owner
  assert not lock.locked()
  result=await obj._handle_directory_request(Request('config'))
  assert len(result['files'])==4 and not lock.locked()
 asyncio.run(run())


def test_exact_previous_recipe_remains_validatable():
 import hashlib
 assert hashlib.sha256(legacy_candidate(SOURCE).encode()).hexdigest()=='bcb401509e2b0c6ac24a2e03b3ff016ee7b2995f5e2fffb81c71acd9d678bfb9'
 assert legacy_candidate(SOURCE)!=candidate(SOURCE)

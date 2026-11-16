from pathlib import Path
import subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
def test_unknown_host_profile_does_not_start_worker_or_touch_native_objects():
 out=ROOT/'build/libscreen-host-guard-only.so'
 subprocess.run(['g++','-std=c++11','-shared','-fPIC','-O2','-Wall','-Wextra','-Werror','-pthread','-Wl,-z,nodelete','-I'+str(ROOT/'source/client'),'-I'+str(ROOT/'source/vendor'),str(ROOT/'source/client/native_bootstrap.cpp'),'-o',str(out)],check=True)
 script='''import ctypes,os,sys,time
threads=set(os.listdir('/proc/self/task'));fds=set(os.listdir('/proc/self/fd'))
library=ctypes.CDLL(sys.argv[1]);library.wmp_openace_screen_initialize()
time.sleep(.1)
assert set(os.listdir('/proc/self/task'))==threads
assert set(os.listdir('/proc/self/fd'))==fds
print('unknown architecture/profile: no worker or sockets')
'''
 subprocess.run([sys.executable,'-c',script,str(out)],check=True)

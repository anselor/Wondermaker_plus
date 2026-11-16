#pragma once
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cerrno>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

namespace wmp_openace {
// Diagnostic values only. Never read by admission, rendering or command policy.
struct DiagnosticBootstrap {enum {Initial,Started,ProfileRejected,TimerMismatch,RefreshMismatch,
 MmapFailed,TrampolineProtectFailed,PageFailed,EntryProtectFailed,HookReady,WorkerFailed,Running,Exception};};
struct DiagnosticRenderer {enum {Initial,Profile,Session,Frame,Protection,Foreign,Viewport,Stop,
 Region,Create,RootRect,BadgeRect,Text,Visible,Exception};};
struct DiagnosticWidget {
 std::atomic<int> geometry[4];
 std::atomic<int> hidden{-1},visible{-1},opacity{-1},recursive_opacity{-1};
 std::atomic<int> background_opacity{-1},text_opacity{-1},font_present{-1};
 DiagnosticWidget(){clear();}
 void clear()noexcept{
  for(auto&v:geometry)v.store(-1,std::memory_order_relaxed);
  hidden.store(-1,std::memory_order_relaxed);visible.store(-1,std::memory_order_relaxed);
  opacity.store(-1,std::memory_order_relaxed);recursive_opacity.store(-1,std::memory_order_relaxed);
  background_opacity.store(-1,std::memory_order_relaxed);text_opacity.store(-1,std::memory_order_relaxed);
  font_present.store(-1,std::memory_order_relaxed);
 }
};
struct ScreenDiagnosticFacts {
 std::atomic<int> bootstrap{DiagnosticBootstrap::Initial},error{0},address{0};
 std::atomic<unsigned> timer_calls{0},timer_matches{0},refresh_calls{0},gui_calls{0};
 std::atomic<unsigned> worker_calls{0};
 // Poll stages: 1 discovery, 2 query, 3 decode/projection, 4 enrichment,
 // 5 legacy delivery, 6 standalone delivery. Never used for admission.
 std::atomic<unsigned> status_polls{0},status_failures{0};
 std::atomic<int> status_failure_stage{0},status_failure_kind{0};
 std::atomic<long long> status_failure_poll_ms{0};
 std::atomic<long long> status_failure_at{-1},status_received_at{-1},status_query_max_ms{0},status_gap_max_ms{0};
 std::atomic<unsigned> navigation_requests{0},navigation_stale{0},navigation_owner{0};
 std::atomic<int> navigation_page{-1};
 std::atomic<long long> navigation_at{-1},gui_gap_max_ms{0},gui_duration_max_ms{0};
 std::atomic<int> worker_flags{0};
 std::atomic<long long> worker_session{-1};
 std::atomic<int> snapshot{0},view_flags{0},mode{0},frame{0},layout_bits{0},renderer{0},renderer_exception{0};
 std::atomic<long long> session{-1};
 // viewport, Print, Stop, group, protected region; each x1,y1,x2,y2.
 std::atomic<int> geometry[20];
 // Owned root, first button (badge), its label, and the root's actual top parent.
 // Each record: coordinates, hidden, native visible, local/recursive/background/text opacity, font nonnull.
 DiagnosticWidget widgets[4];
 ScreenDiagnosticFacts(){for(auto&v:geometry)v.store(0,std::memory_order_relaxed);}
};
static_assert(ATOMIC_INT_LOCK_FREE==2 && ATOMIC_LLONG_LOCK_FREE==2,
              "GUI diagnostics require lock-free scalar stores");
inline ScreenDiagnosticFacts&screen_diagnostics(){static ScreenDiagnosticFacts value;return value;}
// Called only on the GUI thread. These are refresh callback measurements,
// not input-reader timing; no I/O or allocation is performed here.
inline void record_gui_timing(std::int64_t previous,std::int64_t start,std::int64_t end)noexcept{
 auto&d=screen_diagnostics();
 if(previous>=0&&start>=previous&&start-previous>d.gui_gap_max_ms.load())d.gui_gap_max_ms.store(start-previous);
 if(start>=0&&end>=start&&end-start>d.gui_duration_max_ms.load())d.gui_duration_max_ms.store(end-start);
}

// Open/emit ONLY from bootstrap or the existing background worker. No arbitrary
// path, environment option, labels, commands or backend payload reaches this file.
class ScreenDiagnosticLog {
public:
 bool open_process_file()noexcept {
  if(fd_>=0)return true;
  char path[96];const int n=std::snprintf(path,sizeof(path),"/tmp/wmp_openace_screen_%ld.log",long(getpid()));
  if(n<=0||std::size_t(n)>=sizeof(path))return false;
  int fd=::open(path,O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0644);
  if(fd<0)return false;
  struct stat s{};
  if(::fstat(fd,&s)||!S_ISREG(s.st_mode)||s.st_uid!=geteuid()||s.st_nlink!=1||::fchmod(fd,0644)){
   ::close(fd);return false;
  }
  fd_=fd;return true;
 }
 unsigned lines()const noexcept{return lines_;}
 void emit(std::int64_t now_ms)noexcept {
  auto&facts=screen_diagnostics();
  const unsigned navigation=facts.navigation_requests.load();
  const unsigned failures=facts.status_failures.load();
  const bool late_navigation=lines_>=60&&(navigation!=last_navigation_||failures!=last_status_failures_)&&extra_lines_<60;
  if(fd_<0||(lines_>=60&&!late_navigation)||now_ms<0||(last_ms_>=0&&now_ms-last_ms_<5000))return;
  auto&d=screen_diagnostics();int g[20];
  for(unsigned i=0;i<20;++i)g[i]=d.geometry[i].load(std::memory_order_relaxed);
  char widget[4][192];
  for(unsigned i=0;i<4;++i){const auto&w=d.widgets[i];
   std::snprintf(widget[i],sizeof(widget[i]),"%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d",
    w.geometry[0].load(),w.geometry[1].load(),w.geometry[2].load(),w.geometry[3].load(),
    w.hidden.load(),w.visible.load(),w.opacity.load(),w.recursive_opacity.load(),
    w.background_opacity.load(),w.text_opacity.load(),w.font_present.load());
  }
  char line[1536];
  const int n=std::snprintf(line,sizeof(line),
   "bootstrap=%d errno_or_rc=%d address=%x timer_calls=%u timer_matches=%u refresh=%u gui=%u "
   "worker=%u worker_session=%lld worker_flags=%d snapshot=%d session=%lld view_flags=%d mode=%d frame=%d layout_bits=%x renderer=%d renderer_exception=%d "
   "viewport=%d,%d,%d,%d print=%d,%d,%d,%d stop=%d,%d,%d,%d group=%d,%d,%d,%d protected=%d,%d,%d,%d owned_root=%s owned_badge=%s owned_label=%s owned_top=%s "
   "at_ms=%lld nav=%u nav_page=%d nav_at=%lld nav_stale=%u nav_owner=%u gui_gap_max_ms=%lld gui_duration_max_ms=%lld "
   "status_polls=%u status_failures=%u status_failure_stage=%d status_failure_at=%lld status_received_at=%lld status_query_max_ms=%lld status_gap_max_ms=%lld status_failure_kind=%d status_failure_poll_ms=%lld\n",
   d.bootstrap.load(),d.error.load(),d.address.load(),d.timer_calls.load(),d.timer_matches.load(),
   d.refresh_calls.load(),d.gui_calls.load(),d.worker_calls.load(),d.worker_session.load(),d.worker_flags.load(),
   d.snapshot.load(),d.session.load(),d.view_flags.load(),
   d.mode.load(),d.frame.load(),d.layout_bits.load(),d.renderer.load(),d.renderer_exception.load(),
   g[0],g[1],g[2],g[3],g[4],g[5],g[6],g[7],g[8],g[9],g[10],g[11],g[12],g[13],g[14],g[15],g[16],g[17],g[18],g[19],widget[0],widget[1],widget[2],widget[3],
   static_cast<long long>(now_ms),navigation,d.navigation_page.load(),d.navigation_at.load(),d.navigation_stale.load(),d.navigation_owner.load(),d.gui_gap_max_ms.load(),d.gui_duration_max_ms.load(),
   d.status_polls.load(),d.status_failures.load(),d.status_failure_stage.load(),d.status_failure_at.load(),d.status_received_at.load(),d.status_query_max_ms.load(),d.status_gap_max_ms.load(),d.status_failure_kind.load(),d.status_failure_poll_ms.load());
  if(n<=0||std::size_t(n)>=sizeof(line))return;
  // Bounded attempts, including EINTR/short writes; regular-file I/O never runs
  // on the GUI. Mixed adjacent GUI samples are diagnostic, never a snapshot grant.
  if(late_navigation)++extra_lines_;
  ++lines_;last_navigation_=navigation;last_status_failures_=failures;last_ms_=now_ms;std::size_t done=0;
  for(unsigned attempt=0;done<std::size_t(n)&&attempt<8;++attempt){
   const auto written=::write(fd_,line+done,std::size_t(n)-done);
   if(written>0)done+=std::size_t(written);
   else if(written<0&&errno==EINTR)continue;
   else break;
  }
 }
private:
 int fd_=-1;unsigned lines_=0,extra_lines_=0,last_navigation_=0,last_status_failures_=0;std::int64_t last_ms_=-1;
};
}

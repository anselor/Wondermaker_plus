// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "../model.hpp"
#include <algorithm>
#include <deque>
#include <vector>
namespace wmp_ui { namespace native {
enum class ScrubState { Idle, Prepare, StockChecks, ReturnPrompt, Mounting, Heating,
                        Scrub, Cooled, Cancelling, Failed, Calibrate, Finished, Recheck, Remeasure };
enum class ScrubChoice { Clean, Save };          // the two Recheck options
enum class ScrubOutcome { None, Proceed, Skip };  // Skip: withhold the probing and park sends
// Why the flow is in Failed. Backend: the backend gave a sentence (ScrubFacts::error).
enum class ScrubStop { None, Backend, Stopped, Restarted, StatusLost, NotStarted };
// Mark of a head's touch readings: Measuring while the head is measured,
// Passed once measured without a flag, Flagged as soon as it is flagged.
enum class ScrubMark { None, Measuring, Passed, Flagged };
// Readings of one head: the mark and, once the head has a measured centre,
// its centre span in mm (span_known).
struct ScrubReading { ScrubMark mark; bool span_known; double span; };
// What the flow knows, for nozzle_scrub_view.hpp to turn into screen text.
struct ScrubFacts {
 ScrubState state; unsigned head, heads;           // head is 0-based
 bool brush, confirm_enabled;
 ScrubStop stop; std::string error;                // Failed only
 bool hot;                                         // Failed: a nozzle may still be hot
 double actual, target;                            // Heating only
 std::string progress_phase;                       // Calibrate and Remeasure, with the two heads below
 int progress_head, known_progress_head;
 // Recheck: heads whose touches disagreed (0-based, ascending) and the
 // selected option. revisit: the heads of the repeat scrub, empty in the
 // first pass.
 std::vector<unsigned> flagged, revisit;
 ScrubChoice choice;
 bool restored_requested;                          // Cancel queued _WMP_OFFSETS_RESTORE
 bool saved_anyway;                                // released by Save anyway
 // Cancelling and Finished: a head was mounted when the cancel began; the
 // stored offsets are as before the run (none written yet, or restore queued).
 bool cancel_mounted, offsets_unchanged;
 // One per head of the run, from the latest fresh status for the bound request.
 std::vector<ScrubReading> readings;
};
// Guided nozzle scrub state machine. Inputs are user actions, projected status
// snapshots and a clock; outputs are the facts for the view and inner scrub
// commands for the held vendor worker to send. Holds no locks and calls
// nothing outside itself.
//
// Commands are queued per transition and handed out once by next_command, so
// a repeated tap in one state cannot queue a second command. The worker stays
// held until the queue is empty and the flow is in a state that needs no more
// scrub commands.
//
// A run is bound to one calibration request (bind). The backend's scrub and
// progress status carry the request of the attempt they belong to, and the
// attempt status carries its own. Only status for the bound request is
// evidence: status of another attempt, such as the previous one's failure
// before the backend has admitted this run, changes nothing.
//
// Attention signal: requested on entry to ReturnPrompt, Scrub, Cooled and
// Recheck. While it is on, a screen touch after it started (touched) or
// either door going from closed to open in fresh status releases it; it is
// not requested again until the next such entry.
//
// Re-check: when the worker reaches its park send (park_reached) on a brush
// run and fresh status for the bound request flags heads, the worker stays
// held in Recheck. Clean again scrubs the flagged heads (revisit) in the head
// states, then Remeasure sends one RAPID_MODE at a time and evaluates the
// flags again. Save anyway releases the worker. Cancel restores the offsets
// stored at the start of the attempt, then ends the scrub.
class NozzleScrubFlow {
 static constexpr double kScrubReady = 157.5;      // Heating -> Scrub, degrees C
 static constexpr double kUnattended = 600;        // Scrub -> Cooled, seconds
 // Held with stale status, or held without ever seeing status for the bound
 // request -> Cancelling, seconds.
 static constexpr double kStale = 120;
 // Cancelling without "ended" -> Failed. The idle bound counts only time in
 // which the backend is not known to be executing a calibration command:
 // status is stale, or fresh with calibration_active false. The cap counts
 // all time in Cancelling. Seconds.
 static constexpr double kCancellingIdle = 60;
 static constexpr double kCancellingCap = 300;
 static constexpr const char* kEnd = "_WMP_SCRUB_END";
 static constexpr const char* kRestore = "_WMP_OFFSETS_RESTORE";
 ScrubState state_ = ScrubState::Idle;
 ScrubOutcome outcome_ = ScrubOutcome::None;
 ScrubStop stop_ = ScrubStop::None;
 unsigned heads_ = 0, head_ = 0;
 bool combined_ = false, brush_ = true, fresh_ = false, attention_ = false;
 double attention_since_ = 0;                      // the signal was last requested
 int doors_ = -1;                                  // open doors in the latest fresh status that had them; -1 none yet
 // Heat for head_ confirmed by the backend; only then is a zero target a clear.
 bool heat_acked_ = false, reheat_sent_ = false;
 std::string session_, latest_session_, request_, reheat_command_, error_;
 std::deque<std::string> queue_;
 double scrub_since_ = 0, actual_ = 0, target_ = 0;
 bool stale_ = false;                              // status has been stale since stale_since_
 // A scrub command was handed out; a failure from then on may leave a hot nozzle.
 bool started_ = false, hot_ = false;
 double stale_since_ = 0, held_since_ = 0;
 // Cancelling: entered at cancelling_since_, last observed at cancelling_at_,
 // of which cancelling_busy_ seconds had the backend executing.
 double cancelling_since_ = 0, cancelling_at_ = 0, cancelling_busy_ = 0;
 bool seen_ = false;                               // scrub status for the bound request was observed
 int progress_head_ = -1, known_progress_head_ = -1;
 std::string progress_phase_ = "unavailable";
 // Flags in the latest fresh status for the bound request; flagged_: the
 // flags Recheck was entered with.
 std::vector<unsigned> touch_, flagged_, revisit_;
 ScrubChoice choice_ = ScrubChoice::Clean;
 // repeat_: a Clean again was chosen; from then on a cancel restores.
 bool repeat_ = false, restored_requested_ = false, saved_anyway_ = false;
 // Remeasure: heads to measure and the next one's index. rapid_command_ is
 // the RAPID_MODE in flight: queued, then handed out (rapid_sent_), then seen
 // started (rapid_started_). cancel_wanted_: a cancel waits for it.
 std::vector<unsigned> measure_;
 std::size_t measure_next_ = 0;
 std::string rapid_command_;
 bool rapid_sent_ = false, rapid_started_ = false, cancel_wanted_ = false;
 // A repeat mount is acknowledged only by scrub status about this mount: the
 // status left by the previous scrub of the same head shows it heating.
 bool mount_acked_ = true;
 // restore_sent_: the restore was handed out. written_: status for this run
 // showed a measurement, so stored offsets may differ from before the run.
 bool restore_sent_ = false, written_ = false, cancel_mounted_ = false, cancel_unchanged_ = false;
 // At the park send, waiting for status in which the heads of this pass are
 // measured and no measurement runs (the flags are final), since deciding_since_.
 bool deciding_ = false;
 double deciding_since_ = 0;
 bool touch_present_ = false;                      // latest fresh status has nozzle_touch for this run
 Json last_progress_ = Json::object();             // calibration_progress of the latest fresh status for this run
 Json touch_heads_ = Json::array();                // nozzle_touch heads of the latest fresh status for this run

 static std::string number(unsigned value) { return std::to_string(value); }
 void queue(const std::string& command) { queue_.push_back(command); }
 void set_attention(bool on, double now) {
  if (on == attention_) return;
  attention_ = on;
  if (on) attention_since_ = now;
  queue(std::string("_WMP_SCRUB_ATTENTION VALUE=") + (on ? "1" : "0"));
 }
 // Bit n set while door n+1 is open. A door that opens releases the signal;
 // one already open when it started does not.
 void observe_doors(const Json& snapshot, double now) {
  const int doors = integer(snapshot, "doors", -1);
  if (doors < 0 || doors > 3) return;
  if (doors_ >= 0 && (doors & ~doors_)) set_attention(false, now);
  doors_ = doors;
 }
 void begin_cancelling(double now) {
  if (state_ != ScrubState::Cancelling) {
   switch (state_) {
    case ScrubState::ReturnPrompt: case ScrubState::Mounting: case ScrubState::Heating:
    case ScrubState::Scrub: case ScrubState::Cooled: cancel_mounted_ = true; break;
    case ScrubState::Calibrate: cancel_mounted_ = !written_; break;  // the last scrubbed head, before measurement
    default: cancel_mounted_ = false;
   }
  }
  cancel_unchanged_ = !written_ || restored_requested_;
  state_ = ScrubState::Cancelling;
  cancelling_since_ = cancelling_at_ = now;
  cancelling_busy_ = 0;
  outcome_ = ScrubOutcome::Skip;
 }
 void mount(unsigned head) {
  head_ = head;
  heat_acked_ = reheat_sent_ = false;
  mount_acked_ = !repeat_;
  reheat_command_.clear();
  state_ = ScrubState::Mounting;
  queue("_WMP_SCRUB_HEAD T=" + number(head));
 }
 // Unattended timeout or a target cleared elsewhere: every heater this scrub
 // turned on is switched off and the user is asked to reheat.
 void cool(double now) {
  queue("_WMP_SCRUB_COOL");
  state_ = ScrubState::Cooled;
  set_attention(true, now);
 }
 // A failed, refused or replaced attempt refuses further commands; drop what
 // is queued.
 void fail(ScrubStop stop, const std::string& error = std::string()) {
  queue_.clear();
  attention_ = false;
  stop_ = stop;
  error_ = error;
  hot_ = started_;
  state_ = ScrubState::Failed;
  outcome_ = ScrubOutcome::Skip;
 }
 bool held() const {
  switch (state_) {
   case ScrubState::ReturnPrompt: case ScrubState::Mounting: case ScrubState::Heating:
   case ScrubState::Scrub: case ScrubState::Cooled: case ScrubState::Cancelling:
   case ScrubState::Recheck: case ScrubState::Remeasure: return true;
   default: return false;
  }
 }
 bool confirm_enabled() const {
  return fresh_ && (state_ == ScrubState::Prepare || state_ == ScrubState::ReturnPrompt ||
                    state_ == ScrubState::Scrub || state_ == ScrubState::Cooled || state_ == ScrubState::Recheck);
 }
 // The head scrubbed after head_, or -1: every head in the first pass, the
 // flagged heads in a repeat.
 int next_head() const {
  if (!repeat_) return head_ + 1 < heads_ ? int(head_ + 1) : -1;
  for (std::size_t i = 0; i + 1 < revisit_.size(); ++i)
   if (revisit_[i] == head_) return int(revisit_[i + 1]);
  return -1;
 }
 static bool contains(const std::vector<unsigned>& heads, unsigned head) {
  return std::find(heads.begin(), heads.end(), head) != heads.end();
 }
 // Heads as projected (ascending integers 0..3); anything else is no head.
 static std::vector<unsigned> head_list(const Json& object, const char* key) {
  std::vector<unsigned> out;
  if (object.is_object() && object.contains(key) && object[key].is_array())
   for (const auto& head : object[key])
    if (head.is_number_integer() && head.get<int>() >= 0 && head.get<int>() < 4) out.push_back(unsigned(head.get<int>()));
  return out;
 }
 // Cancel path: nothing mounts, heats or measures once queued; the offsets
 // are restored first when restore is set.
 void end_scrub(double now, bool restore) {
  for (auto it = queue_.begin(); it != queue_.end();)
   it = it->compare(0, 16, "_WMP_SCRUB_HEAD ") == 0 || it->compare(0, 16, "_WMP_SCRUB_HEAT ") == 0 ||
        it->compare(0, 11, "RAPID_MODE ") == 0 ? queue_.erase(it) : it + 1;
  rapid_command_.clear();
  rapid_sent_ = rapid_started_ = cancel_wanted_ = false;
  set_attention(false, now);
  if (restore) { queue(kRestore); restored_requested_ = true; }
  queue(kEnd);
  begin_cancelling(now);
 }
 // True when the latest progress status shows every head of this pass
 // measured (the first pass: every head; a repeat: the heads re-measured) and
 // no measurement running. The flags are final then.
 bool pass_measured() const {
  if (flag(last_progress_, "measuring")) return false;
  const auto measured = head_list(last_progress_, "measured");
  if (repeat_) {
   for (unsigned h : measure_) if (!contains(measured, h)) return false;
  } else for (unsigned h = 0; h < heads_; ++h) if (!contains(measured, h)) return false;
  return true;
 }
 // Recheck when the run reached Calibrate on a brush run, the attempt has not
 // stopped, the latest status is fresh, carries nozzle touch status for this
 // request and flags heads. Status from before the flags are final is not
 // decided on: the worker stays held (deciding_) until it is.
 void recheck(double now) {
  if (state_ != ScrubState::Calibrate || !brush_ || !fresh_ || outcome_ != ScrubOutcome::Proceed || saved_anyway_ || !touch_present_) {
   deciding_ = false;
   return;
  }
  if (!pass_measured()) {
   if (!deciding_) deciding_since_ = now;
   deciding_ = true;
   return;
  }
  deciding_ = false;
  std::vector<unsigned> flagged;
  for (unsigned h : touch_) if (h < heads_) flagged.push_back(h);  // a head of this run
  if (flagged.empty()) return;
  flagged_ = flagged;
  choice_ = ScrubChoice::Clean;
  state_ = ScrubState::Recheck;
  set_attention(true, now);
 }
 // Head 1 is the reference of every other head: when it is flagged every head
 // is measured again, in the stock order.
 void remeasure(double now) {
  progress_head_ = known_progress_head_ = -1;
  progress_phase_ = "unavailable";
  measure_.clear();
  if (contains(flagged_, 0)) for (unsigned h = 0; h < heads_; ++h) measure_.push_back(h);
  else measure_ = flagged_;
  measure_next_ = 0;
  state_ = ScrubState::Remeasure;
  measure_head(now);
 }
 void measure_head(double now) {
  if (measure_next_ >= measure_.size()) {
   state_ = ScrubState::Calibrate;
   return recheck(now);
  }
  rapid_command_ = "RAPID_MODE T=" + number(measure_[measure_next_++]);
  rapid_sent_ = rapid_started_ = false;
  queue(rapid_command_);
 }
 static std::string text(const Json& object, const char* key) {
  return object.is_object() && object.contains(key) && object[key].is_string() ? object[key].get<std::string>() : std::string();
 }
 static int integer(const Json& object, const char* key, int fallback) {
  return object.is_object() && object.contains(key) && object[key].is_number_integer() ? object[key].get<int>() : fallback;
 }
 static double real(const Json& object, const char* key, double fallback) {
  return object.is_object() && object.contains(key) && object[key].is_number() ? object[key].get<double>() : fallback;
 }
 static bool flag(const Json& object, const char* key) {
  return object.is_object() && object.contains(key) && object[key].is_boolean() && object[key].get<bool>();
 }
 // Head temperatures as projected under "heads", found by id.
 static Json head_status(const Json& snapshot, unsigned head) {
  if (snapshot.contains("heads") && snapshot["heads"].is_array())
   for (const auto& h : snapshot["heads"])
    if (text(h, "id") == "h" + number(head)) return h;
  return Json::object();
 }
 // True when the status object under key belongs to the bound request.
 bool for_run(const Json& snapshot, const char* key) const {
  return !request_.empty() && snapshot.contains(key) && text(snapshot[key], "request") == request_;
 }
 bool attempt_in(const Json& snapshot, const char* state) const {
  return for_run(snapshot, "calibration_attempt") && text(snapshot["calibration_attempt"], "state") == state;
 }
 // The backend runs no further command of the bound attempt: it failed, or
 // it was refused before or at admission.
 bool attempt_stopped(const Json& snapshot) const {
  return attempt_in(snapshot, "failed") || attempt_in(snapshot, "refused");
 }
 void observe_scrub(const Json& snapshot, double now) {
  const bool own = for_run(snapshot, "nozzle_scrub");
  const Json scrub = own ? snapshot["nozzle_scrub"] : Json::object();
  const auto phase = text(scrub, "phase");
  const bool on_head = integer(scrub, "head", -1) == int(head_);
  if (phase == "failed" || attempt_stopped(snapshot)) {
   const auto error = text(scrub, "error");
   const bool refused = attempt_in(snapshot, "refused");
   fail(!error.empty() ? ScrubStop::Backend : refused ? ScrubStop::NotStarted : ScrubStop::Stopped, error);
   // A refusal with scrub status for this request, whatever its phase, can
   // leave a heater on: the backend adopts the request and then fails to
   // switch off a heater of the previous scrub. Without any status for this
   // request the refusal came before anything ran.
   if (refused) hot_ = seen_;
   return;
  }
  if (!own) return;  // not yet about this run
  if (state_ == ScrubState::Cancelling) {
   if (phase == "ended") state_ = ScrubState::Finished;
   return;
  }
  const Json head = head_status(snapshot, head_);
  const double actual = real(head, "actual", 0), target = real(head, "target", 0);
  if (state_ == ScrubState::Mounting && !mount_acked_ && on_head && (phase != "heating" || target > 0)) mount_acked_ = true;
  if (state_ == ScrubState::Mounting && mount_acked_ && on_head && phase == "heating") {
   heat_acked_ = true;
   if (target == 0) return cool(now);
   if (next_head() >= 0) queue("_WMP_SCRUB_HEAT T=" + number(unsigned(next_head())));
   state_ = ScrubState::Heating;
  }
  if (state_ == ScrubState::Heating) {
   actual_ = actual;
   target_ = real(scrub, "target", target);
   // A reheat is acknowledged once it was handed out and the target is set;
   // earlier status may still show the cleared target.
   if (!heat_acked_ && reheat_sent_ && on_head && target > 0) heat_acked_ = true;
   if (!heat_acked_) return;
   if (target == 0) return cool(now);
   if (actual >= kScrubReady) {
    state_ = ScrubState::Scrub;
    scrub_since_ = now;
    set_attention(true, now);
   }
   return;
  }
  if (state_ == ScrubState::Scrub && heat_acked_ && target == 0) cool(now);
 }
 void observe_fresh(const Json& snapshot, double now) {
  const auto session = text(snapshot, "calibration_session");
  if (state_ == ScrubState::Prepare) { latest_session_ = session; return; }
  if ((state_ == ScrubState::StockChecks || held()) && !session.empty() && session != session_)
   return fail(ScrubStop::Restarted);
  // Klipper restarted while waiting at the park send: released, the run
  // completes as without a re-check.
  if (deciding_ && !session.empty() && session != session_) { deciding_ = false; return; }
  if (for_run(snapshot, "nozzle_scrub")) seen_ = true;
  touch_present_ = for_run(snapshot, "nozzle_touch");
  touch_ = touch_present_ ? head_list(snapshot["nozzle_touch"], "flagged") : std::vector<unsigned>();
  touch_heads_ = touch_present_ && snapshot["nozzle_touch"].contains("heads") && snapshot["nozzle_touch"]["heads"].is_array()
                 ? snapshot["nozzle_touch"]["heads"] : Json::array();
  last_progress_ = for_run(snapshot, "calibration_progress") ? snapshot["calibration_progress"] : Json::object();
  if (!head_list(last_progress_, "measured").empty() || flag(last_progress_, "measuring")) written_ = true;
  if (state_ == ScrubState::Recheck || state_ == ScrubState::Remeasure) observe_check(snapshot, now);
  else if (held()) observe_scrub(snapshot, now);
  else if (state_ == ScrubState::Calibrate) {
   observe_progress(snapshot);
   // A failure or refusal of this attempt once the scrub is complete ends
   // the offset stage. The stock result screen reports it; this screen does
   // not change.
   if (attempt_stopped(snapshot)) outcome_ = ScrubOutcome::Skip;
   if (deciding_) recheck(now);
  }
 }
 // Recheck and Remeasure. A failure or refusal of the attempt ends the offset
 // stage as in the first pass, without a restore.
 void observe_check(const Json& snapshot, double now) {
  if (attempt_stopped(snapshot)) {
   queue_.clear();
   attention_ = false;
   rapid_command_.clear();
   rapid_sent_ = cancel_wanted_ = false;
   state_ = ScrubState::Calibrate;
   outcome_ = ScrubOutcome::Skip;
   return;
  }
  if (state_ != ScrubState::Remeasure) return;
  observe_progress(snapshot);
  if (!rapid_sent_ || !for_run(snapshot, "calibration_progress")) return;
  // The head leaves measured when its RAPID_MODE starts and is added when it
  // completes. Status from before the start still lists it from the earlier
  // measurement.
  const Json progress = snapshot["calibration_progress"];
  const bool measured = contains(head_list(progress, "measured"), measure_[measure_next_ - 1]);
  const bool measuring = flag(progress, "measuring");
  if (!measured || measuring) rapid_started_ = true;
  if (!rapid_started_ || !measured || measuring) return;
  rapid_command_.clear();
  rapid_sent_ = false;
  if (cancel_wanted_) return end_scrub(now, true);
  measure_head(now);
 }
 // A head's mark: Flagged once flagged; otherwise nothing before its first
 // centre, then Measuring while its measurement runs and Passed once
 // calibration_progress lists it measured.
 std::vector<ScrubReading> readings() const {
  std::vector<ScrubReading> out(heads_, ScrubReading{ScrubMark::None, false, 0});
  const auto measured = head_list(last_progress_, "measured");
  const int measuring = flag(last_progress_, "measuring") ? integer(last_progress_, "head", -1) : -1;
  for (const auto& entry : touch_heads_) {
   const int head = integer(entry, "head", -1), centres = integer(entry, "centres", 0);
   if (head < 0 || unsigned(head) >= heads_) continue;  // a head of this run
   auto& r = out[unsigned(head)];
   r.span_known = centres > 0;
   r.span = r.span_known ? real(entry, "centre_span", 0) : 0;
   if (flag(entry, "flagged")) r.mark = ScrubMark::Flagged;
   else if (centres <= 0) r.mark = ScrubMark::None;
   else if (head == measuring) r.mark = ScrubMark::Measuring;
   else if (contains(measured, unsigned(head))) r.mark = ScrubMark::Passed;
  }
  return out;
 }
 void observe_progress(const Json& snapshot) {
  if (!for_run(snapshot, "calibration_progress")) return;
  const Json progress = snapshot["calibration_progress"];
  progress_phase_ = text(progress, "phase");
  progress_head_ = integer(progress, "head", -1);
  if (progress_head_ >= 0) known_progress_head_ = progress_head_;
 }

 public:
 void open(unsigned heads, bool combined, const std::string& session) {
  close();
  if (heads < 1 || heads > 4) return;
  heads_ = heads;
  combined_ = combined;
  session_ = latest_session_ = session;
  state_ = ScrubState::Prepare;
 }
 // The calibration request of the run started from Prepare.
 void bind(const std::string& request) {
  if (state_ == ScrubState::StockChecks) request_ = request;
 }
 void select(bool brush) {
  if (state_ == ScrubState::Prepare) brush_ = brush;
 }
 void select_recheck(ScrubChoice choice) {
  if (state_ == ScrubState::Recheck) choice_ = choice;
 }
 // True when the caller must start the stock run (Prepare). The run is bound
 // to the calibration session of the latest fresh status.
 bool confirm(double now) {
  if (!confirm_enabled()) return false;
  switch (state_) {
   case ScrubState::Prepare:
    session_ = latest_session_;
    state_ = brush_ ? ScrubState::StockChecks : ScrubState::Idle;
    return true;
   case ScrubState::ReturnPrompt:
    set_attention(false, now);
    mount(0);
    return false;
   case ScrubState::Recheck:
    set_attention(false, now);
    if (choice_ == ScrubChoice::Save) {
     saved_anyway_ = true;
     state_ = ScrubState::Calibrate;
     outcome_ = ScrubOutcome::Proceed;
    } else {
     repeat_ = true;
     revisit_ = flagged_;
     mount(revisit_.front());
    }
    return false;
   case ScrubState::Scrub:
    if (now - scrub_since_ >= kUnattended) { cool(now); return false; }
    set_attention(false, now);
    queue("_WMP_SCRUB_COOL T=" + number(head_));
    if (next_head() >= 0) mount(unsigned(next_head()));
    else if (repeat_) remeasure(now);
    else { state_ = ScrubState::Calibrate; outcome_ = ScrubOutcome::Proceed; }
    return false;
   case ScrubState::Cooled:
    set_attention(false, now);
    reheat_command_ = "_WMP_SCRUB_HEAT T=" + number(head_);
    heat_acked_ = reheat_sent_ = false;
    queue(reheat_command_);
    state_ = ScrubState::Heating;
    return false;
   default:
    return false;
  }
 }
 // In Recheck, Remeasure and a repeat scrub the offsets are restored first.
 // The backend refuses the restore while a RAPID_MODE runs, so a cancel
 // during one waits for it to complete.
 void cancel(double now) {
  if (state_ == ScrubState::Prepare) return close();
  if (!held() || state_ == ScrubState::Cancelling) return;
  const bool restore = repeat_ || state_ == ScrubState::Recheck || state_ == ScrubState::Remeasure;
  if (restore && rapid_sent_) { cancel_wanted_ = true; return; }
  end_scrub(now, restore);
 }
 // A screen touch at the flow clock time at. It releases the signal when the
 // signal started no later than the touch.
 void touched(double at) {
  if (attention_ && at >= attention_since_) set_attention(false, at);
 }
 // The worker is at its final park send.
 void park_reached(double now) {
  if (state_ != ScrubState::Calibrate || deciding_) return;
  recheck(now);
 }
 // The worker could not send command. A failed END stops the run. Any other
 // failure once the scrub stage is under way discards what is queued and
 // queues END alone: nothing mounts or heats after it and the offset stage is
 // skipped. An END the backend runs releases the attention signal. After a
 // send that never reached the backend the END arrives out of sequence and is
 // refused; the backend's failure cleanup then cools the heaters and releases
 // the signal.
 void send_failed(const std::string& command, double now) {
  if (!held() && state_ != ScrubState::Calibrate) return;
  if (command == kEnd) return fail(ScrubStop::Stopped);
  queue_.clear();
  attention_ = false;
  rapid_command_.clear();
  rapid_sent_ = cancel_wanted_ = false;
  // A restore counts only once handed out and sent.
  restored_requested_ = restore_sent_ && command != kRestore;
  queue(kEnd);
  begin_cancelling(now);
 }
 void offset_stage_reached(double now) {
  if (state_ != ScrubState::StockChecks) return;
  held_since_ = now;
  if (!combined_) return mount(0);
  head_ = 0;
  state_ = ScrubState::ReturnPrompt;
  set_attention(true, now);
 }
 void observe(const Json& snapshot, double now) {
  if (!snapshot.is_object()) return;
  fresh_ = snapshot.value("fresh", false);
  if (fresh_) stale_ = false;
  else if (!stale_) { stale_ = true; stale_since_ = now; }
  // The clock alone ends an unattended scrub, whatever the status.
  if (state_ == ScrubState::Scrub && now - scrub_since_ >= kUnattended) cool(now);
  // Before the state changes: a door opening in the status that starts the
  // signal is not an opening after it.
  if (fresh_) observe_doors(snapshot, now);
  if (fresh_) observe_fresh(snapshot, now);
  // The worker is never held without a bound. A cancel that the backend does
  // not report as ended stops the run; status that stays stale, or that is
  // never about this run, cancels.
  if (state_ == ScrubState::Cancelling) {
   // END waits in Klipper behind commands already sent; that time is not idle.
   if (fresh_ && flag(snapshot, "calibration_active")) cancelling_busy_ += now - cancelling_at_;
   cancelling_at_ = now;
   const double total = now - cancelling_since_;
   if (total - cancelling_busy_ >= kCancellingIdle || total >= kCancellingCap)
    fail(fresh_ ? ScrubStop::Stopped : ScrubStop::StatusLost);
  } else if (held() && ((stale_ && now - stale_since_ >= kStale) || (!seen_ && now - held_since_ >= kStale))) end_scrub(now, false);
  // Flags that do not become final within the stale limit are not decided on.
  if (deciding_ && ((stale_ && now - stale_since_ >= kStale) || now - deciding_since_ >= kStale)) deciding_ = false;
 }
 bool next_command(std::string& command) {
  if (queue_.empty()) return false;
  command = queue_.front();
  queue_.pop_front();
  started_ = true;
  if (!reheat_command_.empty() && command == reheat_command_) { reheat_sent_ = true; reheat_command_.clear(); }
  if (!rapid_command_.empty() && command == rapid_command_) rapid_sent_ = true;
  if (command == kRestore) restore_sent_ = true;
  return true;
 }
 bool hold() const { return !queue_.empty() || held() || deciding_; }
 ScrubOutcome outcome() const { return outcome_; }
 bool brush() const { return brush_; }
 ScrubFacts facts() const {
  return ScrubFacts{state_, head_, heads_, brush_, confirm_enabled(), stop_, error_, hot_,
                    actual_, target_, progress_phase_, progress_head_, known_progress_head_,
                    flagged_, revisit_, choice_, restored_requested_, saved_anyway_, cancel_mounted_, cancel_unchanged_, readings()};
 }
 void close() { *this = NozzleScrubFlow(); }
};
}}

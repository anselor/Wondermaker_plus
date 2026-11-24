#include "native/nozzle_scrub_flow.hpp"
#include "native/nozzle_scrub_view.hpp"
#include <algorithm>
#include <cassert>
#include <cmath>
#include <vector>
using namespace wmp_ui;
using native::NozzleScrubFlow;
using native::ScrubChoice;
using native::ScrubMark;
using native::ScrubOutcome;
using native::ScrubState;
using native::ScrubView;

namespace {
const std::string kSession(32, 'a');
const std::string kRequest(32, 'c'), kOldRequest(32, 'd');

// Projected snapshot with per-head temperatures and the two scrub status keys.
// request is the attempt the scrub and progress status belong to. A non-empty
// failed is the backend's failure latch and marks attempt_request as failed.
// A non-empty refused marks attempt_request as refused with that error.
struct Snapshot {
 bool fresh = true, active = false;
 std::string refused;
 std::string session = kSession, failed, request = kRequest, attempt_request = kRequest;
 int scrub_head = -1;
 std::string scrub_phase = "idle", scrub_error;
 int progress_head = -1;
 std::string progress_phase = "idle";
 double actual[4] = {25, 25, 25, 25}, target[4] = {0, 0, 0, 0};
 unsigned heads = 4;
 // calibration_progress measured and measuring; nozzle_touch for touch_request
 // (absent when touch is false) with the per-head readings touch_heads.
 std::vector<unsigned> measured, flagged;
 bool measuring = false, touch = true;
 std::string touch_request = kRequest, restore = "none";
 Json touch_heads = Json::array();
 int doors = 0;                                    // open doors, bit n for door n+1; -1 unknown
 Json json() const {
  Json out = {{"fresh", fresh}, {"calibration_session", session}, {"calibration_failed", failed}, {"calibration_active", active},
              {"heads", Json::array()}, {"doors", doors},
              {"calibration_attempt", {{"protocol", 1}, {"session", session}, {"request", attempt_request},
                                       {"state", !refused.empty() ? "refused" : failed.empty() ? "pending" : "failed"},
                                       {"error", !refused.empty() ? refused : failed}}},
              {"nozzle_scrub", {{"protocol", 1}, {"head", scrub_head}, {"phase", scrub_phase}, {"target", 160.0}, {"error", scrub_error}, {"request", request}}},
              {"calibration_progress", {{"protocol", 1}, {"head", progress_head}, {"phase", progress_phase}, {"request", request},
                                        {"measured", measured}, {"measuring", measuring}}}};
  if (touch) out["nozzle_touch"] = {{"protocol", 2}, {"request", touch_request}, {"heads", touch_heads}, {"flagged", flagged}, {"restore", restore}};
  for (unsigned i = 0; i < heads; ++i)
   out["heads"].push_back({{"id", "h" + std::to_string(i)}, {"actual", int(actual[i])}, {"target", int(target[i])}});
  return out;
 }
};

// Screen content for the flow's current state.
ScrubView view(const NozzleScrubFlow& flow) { return native::nozzle_scrub_view(flow.facts()); }

std::vector<std::string> drain(NozzleScrubFlow& flow) {
 std::vector<std::string> out;
 std::string command;
 while (flow.next_command(command)) out.push_back(command);
 return out;
}

// Opens a brush run, confirms Prepare, binds it to kRequest and reaches the
// offset stage.
void start(NozzleScrubFlow& flow, Snapshot& s, unsigned heads, bool combined, double now = 0) {
 s.heads = heads;
 flow.open(heads, combined, kSession);
 flow.observe(s.json(), now);
 assert(flow.confirm(now));
 flow.bind(kRequest);
 assert(view(flow).state == ScrubState::StockChecks);
 assert(!flow.hold());
 flow.offset_stage_reached(now);
}

// Backend reports head h mounted at the scrub position and heated to target.
void heat(NozzleScrubFlow& flow, Snapshot& s, unsigned h, double actual, double now) {
 s.scrub_head = int(h);
 s.scrub_phase = "heating";
 s.target[h] = 160;
 s.actual[h] = actual;
 flow.observe(s.json(), now);
}

void prepare_defaults_to_brush_and_exact_text() {
 NozzleScrubFlow flow;
 Snapshot s;
 flow.open(4, false, kSession);
 auto v = view(flow);
 assert(v.state == ScrubState::Prepare && v.brush && flow.brush());
 assert(v.heading == "How will the nozzles be cleaned?");
 assert(v.confirm_visible && v.cancel_visible && !v.back_visible);
 assert(!v.confirm_enabled);  // No snapshot observed yet.
 assert(!flow.confirm(0));
 flow.observe(s.json(), 0);
 assert(view(flow).confirm_enabled);
 flow.select(false);
 assert(!view(flow).brush);
 flow.select(true);
 assert(view(flow).brush);
 flow.cancel(0);
 assert(view(flow).state == ScrubState::Idle);
 assert(drain(flow).empty());
 for (unsigned heads : {0u, 5u}) {
  flow.open(heads, false, kSession);
  assert(view(flow).state == ScrubState::Idle && !flow.confirm(0));
 }
}

void blob_choice_never_holds() {
 NozzleScrubFlow flow;
 Snapshot s;
 flow.open(4, true, kSession);
 flow.observe(s.json(), 0);
 flow.select(false);
 assert(flow.confirm(0));
 assert(!flow.brush());
 assert(view(flow).state == ScrubState::Idle);
 flow.offset_stage_reached(1);
 assert(!flow.hold() && drain(flow).empty());
 assert(flow.outcome() == ScrubOutcome::None);
 assert(view(flow).state == ScrubState::Idle);
}

void offsets_only_run_skips_return_prompt() {
 NozzleScrubFlow flow;
 Snapshot s;
 start(flow, s, 4, false);
 auto v = view(flow);
 assert(v.state == ScrubState::Mounting && v.head == 0);
 assert(v.heading == "Mounting head 1...");
 assert(v.cancel_visible && v.confirm_visible && !v.confirm_enabled);
 s.progress_phase = "homing";
 flow.observe(s.json(), 1);
 assert(view(flow).heading == "Homing printer...");
 assert(nozzle_scrub_current_step(view(flow)) == 0);
 assert(nozzle_scrub_panel_view(view(flow))["steps"][0]["state"] == "running");
 assert(nozzle_scrub_panel_view(view(flow))["steps"][1]["state"] == "pending");
 s.scrub_head = 0; s.scrub_phase = "mounting";
 flow.observe(s.json(), 2);
 assert(view(flow).heading == "Mounting head 1...");
 s.scrub_phase = "positioning";
 flow.observe(s.json(), 3);
 assert(view(flow).heading == "Positioning head 1...");
 assert(nozzle_scrub_current_step(view(flow)) == 1);
 assert(flow.hold());
 assert(drain(flow) == std::vector<std::string>({"_WMP_SCRUB_HEAD T=0"}));
}

void combined_run_shows_return_prompt() {
 NozzleScrubFlow flow;
 Snapshot s;
 start(flow, s, 4, true);
 auto v = view(flow);
 assert(v.state == ScrubState::ReturnPrompt && v.head == 0);
 assert(v.heading == "Ready to clean the nozzles." && v.body == "Press Confirm to start.");
 assert(v.cancel_visible && v.confirm_visible && v.confirm_enabled);
 assert(flow.hold());
 assert(drain(flow) == std::vector<std::string>({"_WMP_SCRUB_ATTENTION VALUE=1"}));
 assert(!flow.confirm(1));
 assert(view(flow).state == ScrubState::Mounting);
 assert(drain(flow) == std::vector<std::string>({"_WMP_SCRUB_ATTENTION VALUE=0", "_WMP_SCRUB_HEAD T=0"}));
}

void head_sequence_commands() {
 NozzleScrubFlow flow;
 Snapshot s;
 start(flow, s, 4, false);
 std::vector<std::string> sent = drain(flow), expected = {"_WMP_SCRUB_HEAD T=0"};
 double now = 10;
 for (unsigned h = 0; h < 4; ++h) {
  s.scrub_head = int(h);
  s.scrub_phase = "mounting";
  flow.observe(s.json(), now);
  assert(view(flow).state == ScrubState::Mounting && view(flow).head == h);
  heat(flow, s, h, 100, now);
  assert(view(flow).state == ScrubState::Heating);
  if (h + 1 < 4) expected.push_back("_WMP_SCRUB_HEAT T=" + std::to_string(h + 1));
  heat(flow, s, h, 160, now);
  assert(view(flow).state == ScrubState::Scrub);
  expected.push_back("_WMP_SCRUB_ATTENTION VALUE=1");
  assert(!flow.confirm(now + 5));
  expected.push_back("_WMP_SCRUB_ATTENTION VALUE=0");
  expected.push_back("_WMP_SCRUB_COOL T=" + std::to_string(h));
  if (h + 1 < 4) {
   expected.push_back("_WMP_SCRUB_HEAD T=" + std::to_string(h + 1));
   assert(view(flow).state == ScrubState::Mounting && view(flow).head == h + 1);
   assert(flow.hold());
  }
  s.target[h] = 0;
  auto more = drain(flow);
  sent.insert(sent.end(), more.begin(), more.end());
  now += 20;
 }
 assert(sent == expected);
 assert(sent.back() == "_WMP_SCRUB_COOL T=3");
 assert(flow.outcome() == ScrubOutcome::Proceed);
 assert(view(flow).state == ScrubState::Calibrate);
 assert(!flow.hold());
 auto v = view(flow);
 assert(!v.confirm_visible && !v.cancel_visible && !v.back_visible);
}

void heating_shows_temperature() {
 NozzleScrubFlow flow;
 Snapshot s;
 start(flow, s, 4, false);
 drain(flow);
 heat(flow, s, 0, 127, 1);
 auto v = view(flow);
 assert(v.state == ScrubState::Heating);
 assert(v.heading == "Heating head 1...");
 assert(v.actual == 127 && v.target == 160);
 assert(v.cancel_visible && v.confirm_visible && !v.confirm_enabled);
 assert(!flow.confirm(2) && view(flow).state == ScrubState::Heating);
}

void scrub_at_157_5() {
 NozzleScrubFlow flow;
 Snapshot s;
 start(flow, s, 4, false);
 drain(flow);
 heat(flow, s, 0, 157, 1);
 assert(view(flow).state == ScrubState::Heating);
 Json raw = s.json();
 raw["heads"][0]["actual"] = 157.4;
 flow.observe(raw, 2);
 assert(view(flow).state == ScrubState::Heating);
 raw["heads"][0]["actual"] = 157.5;
 flow.observe(raw, 3);
 auto v = view(flow);
 assert(v.state == ScrubState::Scrub);
 assert(v.heading == "Scrub the nozzle on head 1");
 assert(v.body == "Brush the nozzle tip until it is clean, then press Confirm.");
 assert(v.note == "The nozzle is hot.");
 assert(v.cancel_visible && v.confirm_visible && v.confirm_enabled);
}

void timeout_after_600_seconds_cools_and_offers_reheat() {
 NozzleScrubFlow flow;
 Snapshot s;
 start(flow, s, 4, false);
 drain(flow);
 heat(flow, s, 0, 160, 5);
 drain(flow);
 // Head 2 reaches the scrub position at t=100.
 assert(!flow.confirm(50));
 drain(flow);
 heat(flow, s, 1, 160, 100);
 assert(view(flow).state == ScrubState::Scrub);
 assert(drain(flow) == std::vector<std::string>({"_WMP_SCRUB_HEAT T=2", "_WMP_SCRUB_ATTENTION VALUE=1"}));
 flow.observe(s.json(), 699.9);
 assert(view(flow).state == ScrubState::Scrub);
 // The clock alone ends the wait; stale status cannot keep heaters on.
 s.fresh = false;
 flow.observe(s.json(), 700);
 auto v = view(flow);
 assert(v.state == ScrubState::Cooled && v.head == 1);
 assert(v.heading == "Head 2 has cooled." && v.body == "Press Confirm to reheat.");
 assert(v.cancel_visible && v.confirm_visible && !v.confirm_enabled);
 assert(drain(flow) == std::vector<std::string>({"_WMP_SCRUB_COOL"}));
 s.fresh = true;
 s.target[1] = s.target[2] = 0;
 flow.observe(s.json(), 701);
 assert(view(flow).confirm_enabled && flow.hold());
 assert(!flow.confirm(702));
 assert(view(flow).state == ScrubState::Heating);
 assert(drain(flow) == std::vector<std::string>({"_WMP_SCRUB_ATTENTION VALUE=0", "_WMP_SCRUB_HEAT T=1"}));
 // Status taken before the reheat applied still shows a cleared target.
 flow.observe(s.json(), 703);
 assert(view(flow).state == ScrubState::Heating);
 s.target[1] = 160;
 s.actual[1] = 140;
 flow.observe(s.json(), 710);
 assert(view(flow).state == ScrubState::Heating);
 s.actual[1] = 158;
 flow.observe(s.json(), 720);
 assert(view(flow).state == ScrubState::Scrub);
 assert(drain(flow) == std::vector<std::string>({"_WMP_SCRUB_ATTENTION VALUE=1"}));
 // The timeout restarts with the new Scrub state.
 flow.observe(s.json(), 1319);
 assert(view(flow).state == ScrubState::Scrub);
 flow.observe(s.json(), 1320);
 assert(view(flow).state == ScrubState::Cooled);
}

void external_target_clear_during_heating_becomes_cooled() {
 NozzleScrubFlow flow;
 Snapshot s;
 start(flow, s, 4, false);
 drain(flow);
 heat(flow, s, 0, 90, 1);
 assert(drain(flow) == std::vector<std::string>({"_WMP_SCRUB_HEAT T=1"}));
 s.target[0] = 0;  // idle_timeout zeroes extruder targets.
 flow.observe(s.json(), 2);
 auto v = view(flow);
 assert(v.state == ScrubState::Cooled && v.heading == "Head 1 has cooled.");
 assert(drain(flow) == std::vector<std::string>({"_WMP_SCRUB_COOL", "_WMP_SCRUB_ATTENTION VALUE=1"}));
 // Cleared before the head reached the scrub position: no preheat of the next head.
 NozzleScrubFlow early;
 Snapshot e;
 start(early, e, 4, false);
 drain(early);
 e.scrub_head = 0;
 e.scrub_phase = "heating";
 early.observe(e.json(), 1);
 assert(view(early).state == ScrubState::Cooled);
 assert(drain(early) == std::vector<std::string>({"_WMP_SCRUB_COOL", "_WMP_SCRUB_ATTENTION VALUE=1"}));
 // A cleared target in Scrub also cools.
 NozzleScrubFlow scrub;
 Snapshot c;
 start(scrub, c, 4, false);
 drain(scrub);
 heat(scrub, c, 0, 160, 1);
 drain(scrub);
 c.target[0] = 0;
 c.fresh = false;
 scrub.observe(c.json(), 2);
 assert(view(scrub).state == ScrubState::Scrub);  // Stale status is not evidence.
 c.fresh = true;
 scrub.observe(c.json(), 3);
 assert(view(scrub).state == ScrubState::Cooled);
 assert(drain(scrub) == std::vector<std::string>({"_WMP_SCRUB_COOL"}));
}

void double_confirm_queues_one_command() {
 NozzleScrubFlow flow;
 Snapshot s;
 s.heads = 4;
 flow.open(4, true, kSession);
 flow.observe(s.json(), 0);
 assert(flow.confirm(0));
 assert(!flow.confirm(0));
 flow.bind(kRequest);
 flow.offset_stage_reached(1);
 drain(flow);
 assert(!flow.confirm(2));
 assert(!flow.confirm(2));
 assert(drain(flow) == std::vector<std::string>({"_WMP_SCRUB_ATTENTION VALUE=0", "_WMP_SCRUB_HEAD T=0"}));
 heat(flow, s, 0, 160, 3);
 drain(flow);
 flow.confirm(4);
 flow.confirm(4);
 assert(drain(flow) == std::vector<std::string>({"_WMP_SCRUB_ATTENTION VALUE=0", "_WMP_SCRUB_COOL T=0", "_WMP_SCRUB_HEAD T=1"}));
 heat(flow, s, 1, 160, 5);
 drain(flow);
 flow.observe(s.json(), 700);
 drain(flow);
 s.target[1] = 0;
 flow.observe(s.json(), 701);
 flow.confirm(702);
 flow.confirm(702);
 assert(drain(flow) == std::vector<std::string>({"_WMP_SCRUB_ATTENTION VALUE=0", "_WMP_SCRUB_HEAT T=1"}));
 flow.cancel(703);
 flow.cancel(703);
 assert(drain(flow) == std::vector<std::string>({"_WMP_SCRUB_END"}));
}

void three_heads() {
 NozzleScrubFlow flow;
 Snapshot s;
 start(flow, s, 3, false);
 std::vector<std::string> sent = drain(flow);
 for (unsigned h = 0; h < 3; ++h) {
  assert(view(flow).heads == 3);
  heat(flow, s, h, 160, 1 + h);
  flow.confirm(2 + h);
  auto more = drain(flow);
  sent.insert(sent.end(), more.begin(), more.end());
 }
 for (const auto& c : sent) assert(c.find("T=3") == std::string::npos);
 assert(sent.back() == "_WMP_SCRUB_COOL T=2");
 assert(view(flow).state == ScrubState::Calibrate && flow.outcome() == ScrubOutcome::Proceed);
 s.progress_head = 0;
 s.progress_phase = "mounting";
 flow.observe(s.json(), 10);
 auto v = view(flow);
 assert(v.heading == "Head 1 of 3" && v.body == "Mounting head 1...");
 s.progress_phase = "idle";
 s.progress_head = -1;
 flow.observe(s.json(), 11);
 assert(view(flow).heading == "Measuring head 1 of 3...");
}

void stale_status_disables_confirm() {
 NozzleScrubFlow flow;
 Snapshot s;
 s.fresh = false;
 flow.open(4, false, kSession);
 flow.observe(s.json(), 0);
 assert(!view(flow).confirm_enabled);
 assert(!flow.confirm(0));
 assert(view(flow).state == ScrubState::Prepare);
 s.fresh = true;
 flow.observe(s.json(), 1);
 assert(view(flow).confirm_enabled);
 s.fresh = false;
 flow.observe(s.json(), 2);
 assert(!view(flow).confirm_enabled && !flow.confirm(2));
 // Held states disable CONFIRM on stale status too.
 NozzleScrubFlow held;
 Snapshot h;
 start(held, h, 4, true);
 drain(held);
 h.fresh = false;
 held.observe(h.json(), 1);
 assert(!view(held).confirm_enabled);
 assert(!held.confirm(1) && view(held).state == ScrubState::ReturnPrompt);
 assert(drain(held).empty());
}

void session_change_while_held_releases_with_skip() {
 for (int stage = 0; stage < 5; ++stage) {
  NozzleScrubFlow flow;
  Snapshot s;
  start(flow, s, 4, stage == 0);
  drain(flow);
  if (stage >= 2) heat(flow, s, 0, 100, 1);
  if (stage >= 3) heat(flow, s, 0, 160, 2);
  if (stage == 4) flow.cancel(3);
  assert(flow.hold());
  Snapshot restarted = s;
  restarted.session = std::string(32, 'b');
  restarted.fresh = false;
  flow.observe(restarted.json(), 4);
  assert(flow.hold());  // Stale status is not evidence of a restart.
  restarted.fresh = true;
  restarted.scrub_phase = "idle";
  restarted.scrub_head = -1;
  flow.observe(restarted.json(), 5);
  auto v = view(flow);
  assert(v.state == ScrubState::Failed);
  assert(v.body == "Printer restarted. Calibration stopped.");
  assert(v.back_visible && !v.confirm_visible && !v.cancel_visible);
  assert(!flow.hold() && flow.outcome() == ScrubOutcome::Skip);
  assert(drain(flow).empty());
  flow.close();
  assert(view(flow).state == ScrubState::Idle && flow.outcome() == ScrubOutcome::None);
 }
 // A restart during the other checks also stops the scrub before it starts.
 NozzleScrubFlow flow;
 Snapshot s;
 flow.open(4, true, kSession);
 flow.observe(s.json(), 0);
 assert(flow.confirm(0));
 s.session = std::string(32, 'c');
 flow.observe(s.json(), 1);
 assert(view(flow).state == ScrubState::Failed && flow.outcome() == ScrubOutcome::Skip);
 flow.offset_stage_reached(2);
 assert(!flow.hold() && drain(flow).empty());
 // The session is bound when the run starts, not when Prepare opens.
 NozzleScrubFlow late;
 Snapshot l;
 l.session = std::string(32, 'd');
 late.open(4, false, kSession);
 late.observe(l.json(), 0);
 assert(late.confirm(0));
 late.bind(kRequest);
 late.offset_stage_reached(1);
 late.observe(l.json(), 2);
 assert(view(late).state == ScrubState::Mounting);
}

void cancel_mid_scrub_queues_end_and_skips() {
 NozzleScrubFlow flow;
 Snapshot s;
 start(flow, s, 4, false);
 drain(flow);
 heat(flow, s, 0, 160, 1);
 flow.confirm(2);
 drain(flow);
 heat(flow, s, 1, 160, 3);
 drain(flow);
 flow.cancel(4);
 auto v = view(flow);
 assert(v.state == ScrubState::Cancelling);
 assert(v.heading == "Cancelling...");
 assert(v.body == "Cooling and returning head 2 to its dock. Offsets are unchanged.");
 assert(!v.confirm_visible && !v.cancel_visible && !v.back_visible);
 assert(flow.outcome() == ScrubOutcome::Skip);
 assert(flow.hold());
 assert(drain(flow) == std::vector<std::string>({"_WMP_SCRUB_ATTENTION VALUE=0", "_WMP_SCRUB_END"}));
 flow.observe(s.json(), 5);
 assert(flow.hold());
 s.scrub_phase = "ended";
 s.scrub_head = -1;
 s.fresh = false;
 flow.observe(s.json(), 6);
 assert(flow.hold());
 s.fresh = true;
 flow.observe(s.json(), 7);
 assert(!flow.hold() && flow.outcome() == ScrubOutcome::Skip);
 assert(view(flow).state == ScrubState::Finished);
 assert(view(flow).heading == "Cancelling...");
 // Cancel during Mounting and on the return prompt also ends the scrub.
 for (bool combined : {false, true}) {
  NozzleScrubFlow other;
  Snapshot o;
  start(other, o, 4, combined);
  drain(other);
  other.cancel(1);
  assert(view(other).state == ScrubState::Cancelling && view(other).head == 0);
  auto sent = drain(other);
  assert(sent.back() == "_WMP_SCRUB_END");
  assert(sent.size() == (combined ? 2u : 1u));
  o.scrub_phase = "failed";
  o.scrub_error = "Park failed.";
  other.observe(o.json(), 2);
  assert(!other.hold() && other.outcome() == ScrubOutcome::Skip);
  assert(view(other).state == ScrubState::Failed && view(other).body == "Park failed.");
 }
 // Cancel is not offered in Calibrate.
 NozzleScrubFlow done;
 Snapshot d;
 start(done, d, 1, false);
 drain(done);
 heat(done, d, 0, 160, 1);
 done.confirm(2);
 drain(done);
 done.cancel(3);
 assert(view(done).state == ScrubState::Calibrate && done.outcome() == ScrubOutcome::Proceed && drain(done).empty());
}

const char* const kStopped = "Calibration stopped. Check the printer before trying again.";
const char* const kStatusLost = "Printer status was lost. Calibration stopped.";

void backend_failure_shows_one_sentence_and_back() {
 NozzleScrubFlow flow;
 Snapshot s;
 start(flow, s, 4, false);
 drain(flow);
 heat(flow, s, 0, 160, 1);
 flow.confirm(2);
 assert(flow.hold());
 s.scrub_head = 1;
 s.scrub_phase = "failed";
 s.scrub_error = "Head 2 did not mount.";
 s.failed = "Command failed: _WMP_SCRUB_HEAD";
 flow.observe(s.json(), 3);
 auto v = view(flow);
 assert(v.state == ScrubState::Failed && v.body == "Head 2 did not mount.");
 assert(v.back_visible && !v.confirm_visible && !v.cancel_visible);
 assert(flow.outcome() == ScrubOutcome::Skip && !flow.hold());
 assert(drain(flow).empty());  // Nothing more is sent to a failed attempt.
 // The raw calibration failure text is never shown: it names commands.
 NozzleScrubFlow other;
 Snapshot o;
 start(other, o, 4, true);
 drain(other);
 o.failed = "Command failed: _WMP_SCRUB_ATTENTION VALUE=1";
 other.observe(o.json(), 1);
 assert(view(other).state == ScrubState::Failed && view(other).body == kStopped);
 assert(other.outcome() == ScrubOutcome::Skip && !other.hold());
 // The same holds when the scrub reports a failure without a sentence.
 NozzleScrubFlow bare;
 Snapshot b;
 start(bare, b, 4, false);
 drain(bare);
 b.scrub_phase = "failed";
 b.failed = "Calibration stage was missing, repeated, or out of order: SEQUENCE=4; expected 3";
 bare.observe(b.json(), 1);
 assert(view(bare).state == ScrubState::Failed && view(bare).body == kStopped);
 // A scrub sentence is shown whatever phase the scrub reports with it.
 NozzleScrubFlow parked;
 Snapshot k;
 start(parked, k, 4, false);
 drain(parked);
 parked.cancel(1);
 drain(parked);
 k.scrub_error = "The head could not be returned to its dock.";
 k.failed = "PARK_CURRENT_TOOL failed";
 parked.observe(k.json(), 2);
 assert(view(parked).state == ScrubState::Failed && view(parked).body == "The head could not be returned to its dock.");
}

// A failure latched after the scrub completed ends the offset stage: the
// remaining probing sends and the park are withheld, the screen is unchanged.
void failure_during_probing_skips_the_rest() {
 NozzleScrubFlow flow;
 Snapshot s;
 start(flow, s, 2, true);
 drain(flow);
 flow.confirm(1);
 for (unsigned h = 0; h < 2; ++h) {
  heat(flow, s, h, 160, 2 + h);
  flow.confirm(3 + h);
 }
 drain(flow);
 assert(view(flow).state == ScrubState::Calibrate && flow.outcome() == ScrubOutcome::Proceed);
 s.progress_head = 0;
 s.progress_phase = "position";
 flow.observe(s.json(), 10);
 assert(flow.outcome() == ScrubOutcome::Proceed);
 // The backend resets progress when it latches the failure.
 s.progress_head = -1;
 s.progress_phase = "idle";
 s.failed = "Calibration head changed or tool change failed: fail_flag=-2";
 Json stale = s.json();
 stale["fresh"] = false;
 flow.observe(stale, 11);
 assert(flow.outcome() == ScrubOutcome::Proceed);  // stale status decides nothing
 flow.observe(s.json(), 12);
 assert(flow.outcome() == ScrubOutcome::Skip && view(flow).state == ScrubState::Calibrate);
 assert(!flow.hold() && drain(flow).empty());
 // Without a failure the outcome never changes.
 NozzleScrubFlow clean;
 Snapshot c;
 start(clean, c, 1, false);
 drain(clean);
 heat(clean, c, 0, 160, 1);
 clean.confirm(2);
 drain(clean);
 for (const char* phase : {"mounting", "position", "height", "docking", "idle"}) {
  c.progress_head = 0;
  c.progress_phase = phase;
  clean.observe(c.json(), 3);
  assert(clean.outcome() == ScrubOutcome::Proceed);
 }
}

void calibrate_progress_text() {
 NozzleScrubFlow flow;
 Snapshot s;
 start(flow, s, 4, false);
 drain(flow);
 for (unsigned h = 0; h < 4; ++h) {
  heat(flow, s, h, 160, 1 + h);
  flow.confirm(2 + h);
 }
 drain(flow);
 auto v = view(flow);
 assert(v.state == ScrubState::Calibrate);
 assert(v.heading == "Measuring nozzle offsets..." && v.body.empty());
 assert(v.note == "Keep the door closed.");
 struct Case { int head; const char *phase, *heading, *body; };
 for (const auto& c : {Case{-1, "homing", "Homing...", ""},
                       Case{1, "mounting", "Head 2 of 4", "Mounting head 2..."},
                       Case{1, "position", "Head 2 of 4", "Measuring nozzle position..."},
                       Case{2, "height", "Head 3 of 4", "Measuring nozzle height..."},
                       Case{3, "docking", "Returning head 4 to its dock...", ""},
                       Case{-1, "idle", "Measuring head 4 of 4...", ""}}) {
  s.progress_head = c.head;
  s.progress_phase = c.phase;
  flow.observe(s.json(), 20);
  v = view(flow);
  assert(v.heading == c.heading && v.body == c.body);
  assert(v.note == "Keep the door closed.");
  assert(!v.confirm_visible && !v.cancel_visible && !v.back_visible);
 }
 Json raw = s.json();
 raw["calibration_progress"] = {{"phase", "unavailable"}};
 flow.observe(raw, 21);
 assert(view(flow).heading == "Measuring head 4 of 4...");
 assert(!flow.hold());
}

void assert_failed_with(const NozzleScrubFlow& flow, const std::string& body) {
 const auto v = view(flow);
 assert(v.state == ScrubState::Failed && v.body == body && v.back_visible);
 assert(!v.confirm_visible && !v.cancel_visible);
 assert(!flow.hold() && flow.outcome() == ScrubOutcome::Skip);
}

void cancelling_times_out_after_60_seconds_stale() {
 NozzleScrubFlow flow;
 Snapshot s;
 start(flow, s, 4, false, 10);
 drain(flow);
 flow.cancel(20);
 assert(drain(flow) == std::vector<std::string>({"_WMP_SCRUB_END"}));
 s.fresh = false;
 flow.observe(s.json(), 79.9);
 assert(view(flow).state == ScrubState::Cancelling && flow.hold());
 flow.observe(s.json(), 80);
 assert_failed_with(flow, kStatusLost);
 assert(drain(flow).empty());
}

// The backend refused END cleanly: status stays fresh and never reports ended.
void cancelling_times_out_after_refused_end() {
 NozzleScrubFlow flow;
 Snapshot s;
 start(flow, s, 4, true, 0);
 drain(flow);
 flow.cancel(5);  // from the return prompt
 drain(flow);
 for (double now = 6; now < 65; now += 1) {
  flow.observe(s.json(), now);
  assert(view(flow).state == ScrubState::Cancelling && flow.hold());
 }
 flow.observe(s.json(), 65);
 assert_failed_with(flow, kStopped);
 // An END that is reported in time still finishes the cancel.
 NozzleScrubFlow ended;
 Snapshot e;
 start(ended, e, 4, false, 0);
 ended.cancel(5);
 drain(ended);
 e.scrub_phase = "ended";
 ended.observe(e.json(), 64);
 assert(view(ended).state == ScrubState::Finished && !ended.hold());
 ended.observe(e.json(), 500);
 assert(view(ended).state == ScrubState::Finished);
}

void stale_status_for_120_seconds_cancels_then_fails() {
 for (const bool heating : {false, true}) {
  NozzleScrubFlow flow;
  Snapshot s;
  start(flow, s, 4, false, 0);
  if (heating) {
   heat(flow, s, 0, 100, 1);
   assert(view(flow).state == ScrubState::Heating);
  } else {
   flow.observe(s.json(), 1);
   assert(view(flow).state == ScrubState::Mounting);
  }
  drain(flow);
  s.fresh = false;
  flow.observe(s.json(), 10);  // stale from here
  flow.observe(s.json(), 129.9);
  assert(view(flow).state == (heating ? ScrubState::Heating : ScrubState::Mounting) && flow.hold());
  assert(drain(flow).empty());
  flow.observe(s.json(), 130);
  assert(view(flow).state == ScrubState::Cancelling && flow.hold() && flow.outcome() == ScrubOutcome::Skip);
  assert(drain(flow) == std::vector<std::string>({"_WMP_SCRUB_END"}));
  flow.observe(s.json(), 189.9);
  assert(view(flow).state == ScrubState::Cancelling);
  flow.observe(s.json(), 190);
  assert_failed_with(flow, kStatusLost);
 }
 // The same bound applies to the return prompt, Scrub and Cooled.
 NozzleScrubFlow prompt;
 Snapshot p;
 start(prompt, p, 4, true, 0);
 drain(prompt);
 p.fresh = false;
 prompt.observe(p.json(), 0);
 prompt.observe(p.json(), 120);
 const auto sent = drain(prompt);
 assert(view(prompt).state == ScrubState::Cancelling && sent.back() == "_WMP_SCRUB_END");
}

void fresh_status_resets_stale_timer() {
 NozzleScrubFlow flow;
 Snapshot s;
 start(flow, s, 4, false, 0);
 drain(flow);
 s.fresh = false;
 flow.observe(s.json(), 0);
 flow.observe(s.json(), 119);
 s.fresh = true;
 flow.observe(s.json(), 119.5);
 s.fresh = false;
 flow.observe(s.json(), 120);  // a new stale period starts here
 flow.observe(s.json(), 239.9);
 assert(view(flow).state == ScrubState::Mounting && drain(flow).empty());
 flow.observe(s.json(), 240);
 assert(view(flow).state == ScrubState::Cancelling);
}

// The backend clears the previous attempt's status only when it admits the new
// attempt's first command. Until then the snapshot is not about this run.
void stale_failed_status_from_previous_attempt_is_ignored() {
 for (const bool combined : {false, true}) {
  NozzleScrubFlow flow;
  Snapshot s;
  s.request = s.attempt_request = kOldRequest;
  s.scrub_head = 2;
  s.scrub_phase = "failed";
  s.scrub_error = "Head 3 did not mount.";
  s.failed = "Command failed: _WMP_SCRUB_HEAD T=2";
  start(flow, s, 4, combined, 0);
  if (combined) {
   drain(flow);
   flow.observe(s.json(), 0.5);
   assert(view(flow).state == ScrubState::ReturnPrompt && view(flow).confirm_enabled);
   assert(!flow.confirm(0.6));
  }
  std::string command;
  while (flow.next_command(command) && command != "_WMP_SCRUB_HEAD T=0") {}
  assert(command == "_WMP_SCRUB_HEAD T=0");
  for (double now = 1; now < 5; now += 0.5) {
   flow.observe(s.json(), now);
   assert(view(flow).state == ScrubState::Mounting && view(flow).heading == "Mounting head 1...");
   assert(flow.hold() && flow.outcome() == ScrubOutcome::None && drain(flow).empty());
  }
  // The previous attempt's heating report and heater target do not advance the flow.
  Snapshot heating = s;
  heating.failed.clear();
  heating.scrub_head = 0;
  heating.scrub_phase = "heating";
  heating.target[0] = 160;
  heating.actual[0] = 160;
  flow.observe(heating.json(), 5);
  assert(view(flow).state == ScrubState::Mounting && drain(flow).empty());
  // The backend admits this run: its status takes over and the flow proceeds.
  Snapshot own;
  own.heads = 4;
  flow.observe(own.json(), 6);
  assert(view(flow).state == ScrubState::Mounting && flow.hold());
  heat(flow, own, 0, 100, 7);
  assert(view(flow).state == ScrubState::Heating);
  heat(flow, own, 0, 160, 8);
  assert(view(flow).state == ScrubState::Scrub && flow.outcome() == ScrubOutcome::None);
 }
 // The latch string alone, without this run's attempt, is not a failure.
 NozzleScrubFlow latch;
 Snapshot l;
 start(latch, l, 4, false, 0);
 drain(latch);
 Json raw = l.json();
 raw["calibration_failed"] = "Command failed: G28";
 latch.observe(raw, 1);
 assert(view(latch).state == ScrubState::Mounting && latch.hold());
 // Nor is another request's failed attempt, during the scrub or during probing.
 l.failed = "Command failed: G28";
 l.attempt_request = kOldRequest;
 latch.observe(l.json(), 2);
 assert(view(latch).state == ScrubState::Mounting && latch.hold());
 NozzleScrubFlow probing;
 Snapshot p;
 start(probing, p, 1, false, 0);
 drain(probing);
 heat(probing, p, 0, 160, 1);
 probing.confirm(2);
 drain(probing);
 assert(view(probing).state == ScrubState::Calibrate);
 p.failed = "Command failed: RAPID_MODE T=0";
 p.attempt_request = kOldRequest;
 probing.observe(p.json(), 3);
 assert(probing.outcome() == ScrubOutcome::Proceed);
 // Progress published for another request is not shown.
 p.failed.clear();
 p.request = kOldRequest;
 p.progress_head = 0;
 p.progress_phase = "height";
 probing.observe(p.json(), 4);
 assert(view(probing).heading == "Measuring nozzle offsets...");
 p.request = kRequest;
 probing.observe(p.json(), 5);
 assert(view(probing).heading == "Head 1 of 1" && view(probing).body == "Measuring nozzle height...");
}

// A cancel right at the offset stage must not take the previous attempt's
// "ended" for its own.
void stale_ended_status_from_previous_attempt_is_ignored() {
 NozzleScrubFlow flow;
 Snapshot s;
 s.request = s.attempt_request = kOldRequest;
 s.scrub_phase = "ended";
 start(flow, s, 4, false, 0);
 drain(flow);
 flow.cancel(1);
 assert(drain(flow) == std::vector<std::string>({"_WMP_SCRUB_END"}));
 for (double now = 2; now < 10; now += 1) {
  flow.observe(s.json(), now);
  assert(view(flow).state == ScrubState::Cancelling && flow.hold());
 }
 s.request = kRequest;
 s.scrub_phase = "idle";
 flow.observe(s.json(), 10);
 assert(view(flow).state == ScrubState::Cancelling && flow.hold());
 s.scrub_phase = "ended";
 flow.observe(s.json(), 11);
 assert(view(flow).state == ScrubState::Finished && !flow.hold() && flow.outcome() == ScrubOutcome::Skip);
}

void status_for_bound_request_fails_normally() {
 // Scrub failure of this run, reported with its sentence.
 NozzleScrubFlow flow;
 Snapshot s;
 start(flow, s, 4, false, 0);
 drain(flow);
 s.scrub_head = 0;
 s.scrub_phase = "failed";
 s.scrub_error = "Head 1 did not mount.";
 s.failed = "Command failed: _WMP_SCRUB_HEAD T=0";
 flow.observe(s.json(), 1);
 assert(view(flow).state == ScrubState::Failed && view(flow).body == "Head 1 did not mount.");
 assert(!flow.hold() && flow.outcome() == ScrubOutcome::Skip);
 // The scrub phase alone, before the attempt reports the failure.
 NozzleScrubFlow phase;
 Snapshot p;
 start(phase, p, 4, false, 0);
 drain(phase);
 p.scrub_phase = "failed";
 p.scrub_error = "Head 1 could not be heated.";
 phase.observe(p.json(), 1);
 assert(view(phase).state == ScrubState::Failed && view(phase).body == "Head 1 could not be heated.");
 // This run's attempt failed on a command that is not a scrub command (the
 // homing): the scrub status still belongs to the previous attempt, whose
 // sentence is not shown.
 NozzleScrubFlow homing;
 Snapshot h;
 h.request = kOldRequest;
 h.scrub_phase = "failed";
 h.scrub_error = "Head 3 did not mount.";
 start(homing, h, 4, false, 0);
 drain(homing);
 h.failed = "Command failed: G28";
 homing.observe(h.json(), 1);
 assert(view(homing).state == ScrubState::Failed);
 assert(view(homing).body == "Calibration stopped. Check the printer before trying again.");
 // An unbound flow trusts no status.
 NozzleScrubFlow unbound;
 Snapshot u;
 u.request = u.attempt_request = "";
 u.heads = 4;
 unbound.open(4, false, kSession);
 unbound.observe(u.json(), 0);
 assert(unbound.confirm(0));
 unbound.offset_stage_reached(0);
 drain(unbound);
 u.scrub_phase = "failed";
 u.failed = "Command failed";
 unbound.observe(u.json(), 1);
 assert(view(unbound).state == ScrubState::Mounting);
}

// The backend never admits the run: status is fresh but never about it.
void never_admitted_run_cancels_after_120_seconds() {
 for (const bool combined : {false, true}) {
  NozzleScrubFlow flow;
  Snapshot s;
  s.request = s.attempt_request = combined ? std::string() : kOldRequest;
  start(flow, s, 4, combined, 10);
  drain(flow);
  for (double now = 11; now < 130; now += 1) {
   flow.observe(s.json(), now);
   assert(view(flow).state == (combined ? ScrubState::ReturnPrompt : ScrubState::Mounting) && flow.hold());
  }
  flow.observe(s.json(), 129.9);
  assert(flow.hold() && flow.outcome() == ScrubOutcome::None && drain(flow).empty());
  flow.observe(s.json(), 130);
  assert(view(flow).state == ScrubState::Cancelling && flow.hold() && flow.outcome() == ScrubOutcome::Skip);
  assert(drain(flow).back() == "_WMP_SCRUB_END");
  // END is refused as well; the idle bound of Cancelling releases the worker.
  flow.observe(s.json(), 189.9);
  assert(view(flow).state == ScrubState::Cancelling);
  flow.observe(s.json(), 190);
  assert_failed_with(flow, kStopped);
 }
 // One snapshot for the bound request is enough: the bound no longer applies.
 NozzleScrubFlow seen;
 Snapshot n;
 n.request = kOldRequest;
 start(seen, n, 4, false, 0);
 drain(seen);
 seen.observe(n.json(), 60);
 n.request = kRequest;
 seen.observe(n.json(), 119);
 n.request = kOldRequest;
 seen.observe(n.json(), 500);
 assert(view(seen).state == ScrubState::Mounting && seen.hold());
 // Seen during the earlier stages of a combined run.
 NozzleScrubFlow early;
 Snapshot e;
 e.heads = 4;
 early.open(4, true, kSession);
 early.observe(e.json(), 0);
 assert(early.confirm(0));
 early.bind(kRequest);
 early.observe(e.json(), 1);
 e.request = kOldRequest;
 early.offset_stage_reached(900);
 early.observe(e.json(), 1100);
 assert(view(early).state == ScrubState::ReturnPrompt && early.hold());
}

// END waits in Klipper behind the homing and the mount already handed out.
void cancelling_bound_pauses_while_backend_is_executing() {
 NozzleScrubFlow flow;
 Snapshot s;
 start(flow, s, 4, false, 0);
 drain(flow);
 flow.cancel(10);
 drain(flow);
 s.active = true;
 for (double now = 11; now <= 200; now += 1) {
  flow.observe(s.json(), now);
  assert(view(flow).state == ScrubState::Cancelling && flow.hold());
 }
 // Idle from 200: the bound counts from here, and does not start over.
 s.active = false;
 flow.observe(s.json(), 230);  // 30 s idle
 s.active = true;
 flow.observe(s.json(), 240);  // executing again: paused, not reset
 flow.observe(s.json(), 250);
 s.active = false;
 flow.observe(s.json(), 279);  // 59 s idle
 assert(view(flow).state == ScrubState::Cancelling && flow.hold());
 flow.observe(s.json(), 280);  // 60 s idle
 assert_failed_with(flow, kStopped);
 // Stale status counts whatever it last said about the backend.
 NozzleScrubFlow stale;
 Snapshot t;
 start(stale, t, 4, false, 0);
 drain(stale);
 stale.cancel(10);
 drain(stale);
 t.active = true;
 stale.observe(t.json(), 20);
 t.fresh = false;
 stale.observe(t.json(), 79);
 assert(view(stale).state == ScrubState::Cancelling);
 stale.observe(t.json(), 80);
 assert_failed_with(stale, kStatusLost);
 // The end reported while the backend was executing finishes the cancel.
 NozzleScrubFlow ended;
 Snapshot e;
 start(ended, e, 4, false, 0);
 drain(ended);
 ended.cancel(10);
 drain(ended);
 e.active = true;
 ended.observe(e.json(), 150);
 e.active = false;
 e.scrub_phase = "ended";
 ended.observe(e.json(), 151);
 assert(view(ended).state == ScrubState::Finished && !ended.hold());
}

void cancelling_absolute_cap_after_300_seconds() {
 NozzleScrubFlow flow;
 Snapshot s;
 start(flow, s, 4, false, 0);
 drain(flow);
 flow.cancel(10);
 drain(flow);
 s.active = true;
 for (double now = 11; now < 310; now += 1) {
  flow.observe(s.json(), now);
  assert(view(flow).state == ScrubState::Cancelling && flow.hold());
 }
 flow.observe(s.json(), 309.9);
 assert(view(flow).state == ScrubState::Cancelling && flow.hold());
 flow.observe(s.json(), 310);
 assert_failed_with(flow, kStopped);
 assert(view(flow).note == "The nozzle may still be hot.");
 // A send failure restarts both bounds.
 NozzleScrubFlow resent;
 Snapshot r;
 start(resent, r, 4, false, 0);
 drain(resent);
 heat(resent, r, 0, 160, 1);
 drain(resent);
 resent.cancel(10);
 std::string command;
 assert(resent.next_command(command) && command == "_WMP_SCRUB_ATTENTION VALUE=0");
 r.active = true;
 resent.observe(r.json(), 100);
 resent.send_failed(command, 100);
 resent.observe(r.json(), 399.9);
 assert(view(resent).state == ScrubState::Cancelling);
 resent.observe(r.json(), 400);
 assert(view(resent).state == ScrubState::Failed);
}

const char* const kHot = "The nozzle may still be hot.";
const std::vector<std::string> kOnlyEnd = {"_WMP_SCRUB_END"};

// Path A: after the last CONFIRM nothing holds the worker, but ATTENTION and
// COOL are still queued. A failed send must end the scrub, not start probing.
void send_failure_after_last_confirm_sends_end_and_skips() {
 for (const char* failing : {"_WMP_SCRUB_ATTENTION VALUE=0", "_WMP_SCRUB_COOL T=0"}) {
  NozzleScrubFlow flow;
  Snapshot s;
  start(flow, s, 1, false, 0);
  drain(flow);
  heat(flow, s, 0, 160, 1);
  drain(flow);
  assert(!flow.confirm(2) && view(flow).state == ScrubState::Calibrate && flow.outcome() == ScrubOutcome::Proceed);
  std::string command;
  do assert(flow.next_command(command)); while (command != failing);
  flow.send_failed(command, 3);
  assert(view(flow).state == ScrubState::Cancelling && flow.outcome() == ScrubOutcome::Skip && flow.hold());
  assert(drain(flow) == kOnlyEnd);
  assert(flow.hold());  // until the backend reports the end, or the bound
  flow.observe(s.json(), 62.9);
  assert(view(flow).state == ScrubState::Cancelling);
  s.scrub_phase = "ended";
  flow.observe(s.json(), 62.95);
  assert(view(flow).state == ScrubState::Finished && !flow.hold() && flow.outcome() == ScrubOutcome::Skip);
 }
 // Without the end being reported the 60 s bound runs from the failure.
 NozzleScrubFlow late;
 Snapshot l;
 start(late, l, 1, false, 0);
 drain(late);
 heat(late, l, 0, 160, 1);
 drain(late);
 late.confirm(2);
 std::string command;
 assert(late.next_command(command));
 late.send_failed(command, 100);
 drain(late);
 late.observe(l.json(), 159.9);
 assert(view(late).state == ScrubState::Cancelling);
 late.observe(l.json(), 160);
 assert(view(late).state == ScrubState::Failed && view(late).note == kHot && !late.hold());
}

// Path B: attention is on (Scrub). The failure queues END alone, with no
// ATTENTION command ahead of it, also when a cancel was already under way.
void send_failure_with_attention_on_sends_only_end() {
 NozzleScrubFlow flow;
 Snapshot s;
 start(flow, s, 4, false, 0);
 drain(flow);
 heat(flow, s, 0, 160, 1);
 assert(view(flow).state == ScrubState::Scrub);
 std::string command;
 assert(flow.next_command(command) && command == "_WMP_SCRUB_HEAT T=1");
 flow.send_failed(command, 2);
 assert(view(flow).state == ScrubState::Cancelling && flow.outcome() == ScrubOutcome::Skip);
 assert(drain(flow) == kOnlyEnd);
 // The user cancels in Scrub; the ATTENTION send that precedes END fails.
 NozzleScrubFlow cancelled;
 Snapshot c;
 start(cancelled, c, 4, false, 0);
 drain(cancelled);
 heat(cancelled, c, 0, 160, 1);
 drain(cancelled);
 cancelled.cancel(2);
 assert(cancelled.next_command(command) && command == "_WMP_SCRUB_ATTENTION VALUE=0");
 cancelled.send_failed(command, 30);
 assert(view(cancelled).state == ScrubState::Cancelling && drain(cancelled) == kOnlyEnd);
 // The bound restarts at the failure.
 cancelled.observe(c.json(), 89.9);
 assert(view(cancelled).state == ScrubState::Cancelling);
 cancelled.observe(c.json(), 90);
 assert(view(cancelled).state == ScrubState::Failed);
 // From the return prompt as well.
 NozzleScrubFlow prompt;
 Snapshot p;
 start(prompt, p, 4, true, 0);
 assert(prompt.next_command(command) && command == "_WMP_SCRUB_ATTENTION VALUE=1");
 prompt.send_failed(command, 1);
 assert(view(prompt).state == ScrubState::Cancelling && drain(prompt) == kOnlyEnd);
}

void second_send_failure_on_end_fails_with_hot_note() {
 NozzleScrubFlow flow;
 Snapshot s;
 start(flow, s, 4, false, 0);
 heat(flow, s, 0, 100, 1);
 std::string command;
 assert(flow.next_command(command) && command == "_WMP_SCRUB_HEAD T=0");
 flow.send_failed(command, 2);
 assert(flow.next_command(command) && command == "_WMP_SCRUB_END");
 flow.send_failed(command, 3);
 const auto v = view(flow);
 assert(v.state == ScrubState::Failed && v.body == kStopped && v.note == kHot && v.back_visible);
 assert(!flow.hold() && flow.outcome() == ScrubOutcome::Skip && drain(flow).empty());
 // Later failures change nothing.
 flow.send_failed("_WMP_SCRUB_COOL", 4);
 assert(view(flow).state == ScrubState::Failed && drain(flow).empty());
 // Other failures after the scrub started carry the note too.
 NozzleScrubFlow restarted;
 Snapshot r;
 start(restarted, r, 4, false, 0);
 drain(restarted);
 r.session = std::string(32, 'b');
 restarted.observe(r.json(), 1);
 assert(view(restarted).state == ScrubState::Failed && view(restarted).note == kHot);
}

// CONFIRM on head 1 of 2 queues ATTENTION, COOL and the mount of head 2.
void send_failure_never_mounts_next_head() {
 NozzleScrubFlow flow;
 Snapshot s;
 start(flow, s, 2, false, 0);
 drain(flow);
 heat(flow, s, 0, 160, 1);
 drain(flow);
 flow.confirm(2);
 std::string command;
 assert(flow.next_command(command) && command == "_WMP_SCRUB_ATTENTION VALUE=0");
 flow.send_failed(command, 3);
 assert(view(flow).state == ScrubState::Cancelling && drain(flow) == kOnlyEnd);
}

void user_cancel_drops_queued_head_and_heat() {
 NozzleScrubFlow flow;
 Snapshot s;
 start(flow, s, 4, false, 0);
 drain(flow);
 heat(flow, s, 0, 160, 1);  // queues the preheat of head 2 and the attention signal
 flow.cancel(2);
 assert(drain(flow) == std::vector<std::string>({"_WMP_SCRUB_ATTENTION VALUE=1", "_WMP_SCRUB_ATTENTION VALUE=0", "_WMP_SCRUB_END"}));
 // CONFIRM then CANCEL before the worker sent anything: cool, but no mount.
 NozzleScrubFlow next;
 Snapshot n;
 start(next, n, 4, false, 0);
 drain(next);
 heat(next, n, 0, 160, 1);
 drain(next);
 next.confirm(2);
 next.cancel(3);
 assert(drain(next) == std::vector<std::string>({"_WMP_SCRUB_ATTENTION VALUE=0", "_WMP_SCRUB_COOL T=0", "_WMP_SCRUB_END"}));
 // Cancel right at the offset stage: the first mount is not sent.
 NozzleScrubFlow first;
 Snapshot f;
 start(first, f, 4, false, 0);
 first.cancel(1);
 assert(drain(first) == kOnlyEnd);
}

void failed_note_absent_before_scrub_started() {
 // Session change during the stock checks: no scrub command was handed out.
 NozzleScrubFlow flow;
 Snapshot s;
 s.heads = 4;
 flow.open(4, true, kSession);
 flow.observe(s.json(), 0);
 assert(flow.confirm(0));
 s.session = std::string(32, 'b');
 flow.observe(s.json(), 1);
 assert(view(flow).state == ScrubState::Failed && view(flow).note.empty());
 // Backend failure reported before the queued mount left the flow.
 NozzleScrubFlow early;
 Snapshot e;
 start(early, e, 4, false, 0);
 e.failed = "Homing failed.";
 early.observe(e.json(), 1);
 assert(view(early).state == ScrubState::Failed && view(early).note.empty());
 // A cancel the backend confirmed is not a failure and shows no note.
 NozzleScrubFlow ended;
 Snapshot d;
 start(ended, d, 4, false, 0);
 drain(ended);
 ended.cancel(1);
 drain(ended);
 d.scrub_phase = "ended";
 ended.observe(d.json(), 2);
 assert(view(ended).state == ScrubState::Finished && view(ended).note.empty());
}

const char* const kNotStarted = "Calibration did not start.";

// The backend refused the run's first command before admitting the attempt:
// scrub status still belongs to an earlier attempt, or to none.
void refused_attempt_with_foreign_scrub_status_stops() {
 for (const bool combined : {false, true}) {
  for (const std::string& foreign : {kOldRequest, std::string()}) {
   NozzleScrubFlow flow;
   Snapshot s;
   s.request = foreign;
   start(flow, s, 4, combined, 10);
   std::string command;
   assert(flow.next_command(command));  // a scrub command was handed out
   const auto held = combined ? ScrubState::ReturnPrompt : ScrubState::Mounting;
   flow.observe(s.json(), 11);
   assert(view(flow).state == held && flow.hold() && flow.outcome() == ScrubOutcome::None);
   if (combined) {
    assert(!flow.confirm(11));  // queues the mount, which is never sent
    assert(flow.hold());
   }
   // A refusal of another attempt is not about this run.
   s.attempt_request = kOldRequest;
   s.refused = "Printer must be idle before calibration";
   flow.observe(s.json(), 12);
   assert(flow.hold() && flow.outcome() == ScrubOutcome::None);
   // Stale status decides nothing.
   s.attempt_request = kRequest;
   Json stale = s.json();
   stale["fresh"] = false;
   flow.observe(stale, 13);
   assert(flow.hold() && flow.outcome() == ScrubOutcome::None);
   flow.observe(s.json(), 14);
   const auto v = view(flow);
   assert(v.state == ScrubState::Failed && v.heading.empty() && v.body == kNotStarted);
   assert(v.note.empty());  // nothing was heated
   assert(v.back_visible && !v.confirm_visible && !v.cancel_visible);
   assert(flow.outcome() == ScrubOutcome::Skip && !flow.hold());
   assert(drain(flow).empty());  // the queue was cleared
  }
 }
}

// The admission-time cool-down failed: scrub status is for this run and idle,
// and the attempt is refused. A heater the previous scrub turned on could not
// be switched off, so the caution is shown.
void refused_attempt_with_own_scrub_status_stops_with_hot_note() {
 NozzleScrubFlow flow;
 Snapshot s;
 start(flow, s, 4, false, 0);
 assert(drain(flow) == std::vector<std::string>({"_WMP_SCRUB_HEAD T=0"}));
 flow.observe(s.json(), 1);
 assert(view(flow).state == ScrubState::Mounting && flow.hold());
 s.refused = "Heater extruder could not be cooled";
 // Status is fresh and for this run, so no time bound would end the hold.
 flow.observe(s.json(), 2);
 const auto v = view(flow);
 assert(v.state == ScrubState::Failed && v.heading.empty() && v.body == kNotStarted && v.note == kHot);
 assert(v.back_visible && !v.confirm_visible && !v.cancel_visible);
 assert(flow.outcome() == ScrubOutcome::Skip && !flow.hold() && drain(flow).empty());
 // A refusal seen after the scrub ran for this request shows the note too.
 NozzleScrubFlow ran;
 Snapshot r;
 start(ran, r, 4, false, 0);
 drain(ran);
 heat(ran, r, 0, 100, 1);
 assert(view(ran).state == ScrubState::Heating);
 r.refused = "Calibration attempt is already stopped";
 ran.observe(r.json(), 2);
 assert(view(ran).state == ScrubState::Failed && view(ran).body == kNotStarted && view(ran).note == kHot);
 assert(ran.outcome() == ScrubOutcome::Skip && !ran.hold() && drain(ran).empty());
 // ... also when the scrub status has returned to idle by then.
 NozzleScrubFlow earlier;
 Snapshot e;
 start(earlier, e, 4, false, 0);
 drain(earlier);
 heat(earlier, e, 0, 100, 1);
 e.scrub_head = -1;
 e.scrub_phase = "idle";
 e.refused = "Calibration attempt is already stopped";
 earlier.observe(e.json(), 2);
 assert(view(earlier).state == ScrubState::Failed && view(earlier).note == kHot);
 // A failed attempt with idle scrub status keeps the note as before.
 NozzleScrubFlow failed;
 Snapshot f;
 start(failed, f, 4, false, 0);
 drain(failed);
 f.failed = "Homing failed.";
 failed.observe(f.json(), 1);
 assert(view(failed).state == ScrubState::Failed && view(failed).body == kStopped && view(failed).note == kHot);
 // The note does not depend on a command having been handed out: status for
 // this request, in any phase, is enough.
 for (const char* phase : {"idle", "mounting"}) {
  NozzleScrubFlow unsent;
  Snapshot u;
  start(unsent, u, 4, false, 0);
  u.scrub_phase = phase;
  u.refused = "Calibration attempt is already stopped";
  unsent.observe(u.json(), 1);
  assert(view(unsent).state == ScrubState::Failed && view(unsent).note == kHot && drain(unsent).empty());
 }
 // Own status seen in an earlier snapshot counts when the refusal arrives
 // with status that is no longer for this request.
 NozzleScrubFlow before;
 Snapshot b;
 start(before, b, 4, false, 0);
 before.observe(b.json(), 1);
 b.request = kOldRequest;
 b.refused = "Calibration attempt is already stopped";
 before.observe(b.json(), 2);
 assert(view(before).state == ScrubState::Failed && view(before).body == kNotStarted && view(before).note == kHot);
 // A scrub sentence is shown in place of the fixed one.
 NozzleScrubFlow sentence;
 Snapshot t;
 start(sentence, t, 4, false, 0);
 drain(sentence);
 t.scrub_phase = "failed";
 t.scrub_error = "Head 1 did not mount.";
 t.refused = "Calibration attempt is already stopped";
 sentence.observe(t.json(), 1);
 assert(view(sentence).state == ScrubState::Failed && view(sentence).body == "Head 1 did not mount." && view(sentence).note == kHot);
}

// Refused before anything ran for this request: no scrub status for it was
// ever seen, so no heater of this run or of its admission can be on.
void refused_attempt_without_own_scrub_status_stops_without_hot_note() {
 for (const std::string& foreign : {kOldRequest, std::string()}) {
  NozzleScrubFlow flow;
  Snapshot s;
  s.request = foreign;
  start(flow, s, 4, false, 0);
  assert(drain(flow) == std::vector<std::string>({"_WMP_SCRUB_HEAD T=0"}));  // handed out, never run
  flow.observe(s.json(), 1);
  s.refused = "Printer must be idle before calibration";
  flow.observe(s.json(), 2);
  const auto v = view(flow);
  assert(v.state == ScrubState::Failed && v.body == kNotStarted && v.note.empty() && v.back_visible);
  assert(flow.outcome() == ScrubOutcome::Skip && !flow.hold() && drain(flow).empty());
 }
}

// A refusal of this attempt once the scrub is complete ends the offset stage
// exactly as a failure does: the outcome becomes Skip and this screen does
// not change (failure_during_probing_skips_the_rest).
void refused_attempt_during_calibrate_stops() {
 NozzleScrubFlow flow;
 Snapshot s;
 start(flow, s, 1, false);
 drain(flow);
 heat(flow, s, 0, 160, 1);
 flow.confirm(2);
 drain(flow);
 assert(view(flow).state == ScrubState::Calibrate && flow.outcome() == ScrubOutcome::Proceed && !flow.hold());
 // A refusal of another attempt changes nothing.
 s.attempt_request = kOldRequest;
 s.refused = "Calibration attempt is already stopped";
 flow.observe(s.json(), 3);
 assert(flow.outcome() == ScrubOutcome::Proceed);
 s.attempt_request = kRequest;
 Json stale = s.json();
 stale["fresh"] = false;
 flow.observe(stale, 4);
 assert(flow.outcome() == ScrubOutcome::Proceed);  // stale status decides nothing
 flow.observe(s.json(), 5);
 assert(flow.outcome() == ScrubOutcome::Skip && view(flow).state == ScrubState::Calibrate);
 assert(!flow.hold() && drain(flow).empty());
}

// Scrubs every head of a brush run and reaches Calibrate; the scrub status
// keeps the last head in phase heating with its target cleared, as the backend
// leaves it after the last cool.
void first_pass(NozzleScrubFlow& flow, Snapshot& s, unsigned heads = 4) {
 start(flow, s, heads, false);
 for (unsigned h = 0; h < heads; ++h) {
  heat(flow, s, h, 160, 1 + h);
  flow.confirm(2 + h);
  s.target[h] = 0;
 }
 drain(flow);
 for (unsigned h = 0; h < heads; ++h) s.measured.push_back(h);
 flow.observe(s.json(), 10);
 assert(view(flow).state == ScrubState::Calibrate && !flow.hold() && flow.outcome() == ScrubOutcome::Proceed);
}

// The worker reaches its park send with the given heads flagged.
void at_park(NozzleScrubFlow& flow, Snapshot& s, const std::vector<unsigned>& flagged, double now = 11) {
 s.flagged = flagged;
 flow.observe(s.json(), now);
 flow.park_reached(now);
}

// A RAPID_MODE T=head starts and completes.
void measure(NozzleScrubFlow& flow, Snapshot& s, unsigned head, double now) {
 for (auto it = s.measured.begin(); it != s.measured.end();) it = *it == head ? s.measured.erase(it) : it + 1;
 s.measuring = true;
 flow.observe(s.json(), now);
 s.measured.push_back(head);
 std::sort(s.measured.begin(), s.measured.end());
 s.measuring = false;
 flow.observe(s.json(), now + 1);
}

// Scrubs the heads of a repeat pass from the Recheck screen; returns the
// commands. The status no longer flags heads: the backend discards a head's
// flag when it is measured again.
std::vector<std::string> clean_again(NozzleScrubFlow& flow, Snapshot& s, const std::vector<unsigned>& heads, double now) {
 flow.select_recheck(ScrubChoice::Clean);
 assert(!flow.confirm(now));
 s.flagged.clear();
 std::vector<std::string> sent = drain(flow);
 for (unsigned h : heads) {
  assert(view(flow).state == ScrubState::Mounting && view(flow).head == h);
  heat(flow, s, h, 160, now);
  assert(view(flow).state == ScrubState::Scrub && view(flow).head == h);
  assert(!flow.confirm(now + 1));
  s.target[h] = 0;
  auto more = drain(flow);
  sent.insert(sent.end(), more.begin(), more.end());
  now += 2;
 }
 return sent;
}

void recheck_entered_only_with_flags_fresh_status_and_brush_run() {
 const auto not_held = [](NozzleScrubFlow& flow) {
  assert(view(flow).state == ScrubState::Calibrate && !flow.hold() && drain(flow).empty());
  assert(flow.outcome() == ScrubOutcome::Proceed);
 };
 {  // No flags.
  NozzleScrubFlow flow;
  Snapshot s;
  first_pass(flow, s);
  at_park(flow, s, {});
  not_held(flow);
 }
 {  // Stale status.
  NozzleScrubFlow flow;
  Snapshot s;
  first_pass(flow, s);
  s.flagged = {1};
  flow.observe(s.json(), 11);
  s.fresh = false;
  flow.observe(s.json(), 12);
  flow.park_reached(12);
  not_held(flow);
 }
 {  // Flags of another request.
  NozzleScrubFlow flow;
  Snapshot s;
  first_pass(flow, s);
  s.touch_request = kOldRequest;
  at_park(flow, s, {1});
  not_held(flow);
 }
 {  // No nozzle touch status.
  NozzleScrubFlow flow;
  Snapshot s;
  first_pass(flow, s);
  s.touch = false;
  at_park(flow, s, {1});
  not_held(flow);
  Json empty = s.json();
  empty["nozzle_touch"] = Json::object();
  flow.observe(empty, 12);
  flow.park_reached(12);
  not_held(flow);
 }
 {  // The attempt failed before the park.
  NozzleScrubFlow flow;
  Snapshot s;
  first_pass(flow, s);
  s.failed = "Command failed: RAPID_MODE T=3";
  at_park(flow, s, {1});
  assert(view(flow).state == ScrubState::Calibrate && !flow.hold() && drain(flow).empty());
  assert(flow.outcome() == ScrubOutcome::Skip);
 }
 {  // A flag for a head this run does not have.
  NozzleScrubFlow flow;
  Snapshot s;
  first_pass(flow, s, 3);
  at_park(flow, s, {3});
  not_held(flow);
 }
 {  // Printed blob run.
  NozzleScrubFlow flow;
  Snapshot s;
  flow.open(4, false, kSession);
  flow.observe(s.json(), 0);
  flow.select(false);
  assert(flow.confirm(0));
  s.flagged = {1};
  flow.observe(s.json(), 1);
  flow.park_reached(1);
  assert(view(flow).state == ScrubState::Idle && !flow.hold() && drain(flow).empty());
 }
 // Flags, fresh status, this request, brush run.
 NozzleScrubFlow flow;
 Snapshot s;
 first_pass(flow, s);
 at_park(flow, s, {1});
 assert(view(flow).state == ScrubState::Recheck && flow.hold());
 assert(flow.facts().flagged == std::vector<unsigned>({1}) && flow.facts().choice == ScrubChoice::Clean);
 assert(drain(flow) == std::vector<std::string>({"_WMP_SCRUB_ATTENTION VALUE=1"}));
 assert(flow.hold());
 // Recheck has no unattended limit.
 flow.observe(s.json(), 5000);
 assert(view(flow).state == ScrubState::Recheck && flow.hold() && drain(flow).empty());
 // A second park call changes nothing.
 flow.park_reached(5001);
 assert(view(flow).state == ScrubState::Recheck && drain(flow).empty());
}

void recheck_save_releases_with_proceed() {
 NozzleScrubFlow flow;
 Snapshot s;
 first_pass(flow, s);
 at_park(flow, s, {1, 3});
 drain(flow);
 flow.select_recheck(ScrubChoice::Save);
 assert(flow.facts().choice == ScrubChoice::Save && !view(flow).first_selected);
 assert(!flow.confirm(12));
 assert(view(flow).state == ScrubState::Calibrate && flow.outcome() == ScrubOutcome::Proceed);
 assert(flow.facts().saved_anyway && !flow.facts().restored_requested);
 assert(flow.facts().flagged == std::vector<unsigned>({1, 3}));
 assert(flow.hold());
 assert(drain(flow) == std::vector<std::string>({"_WMP_SCRUB_ATTENTION VALUE=0"}));
 assert(!flow.hold());
 flow.park_reached(13);
 assert(view(flow).state == ScrubState::Calibrate && !flow.hold());
 // select_recheck outside Recheck changes nothing.
 flow.select_recheck(ScrubChoice::Clean);
 assert(flow.facts().choice == ScrubChoice::Save);
}

void recheck_cancel_restores_then_ends_and_skips() {
 NozzleScrubFlow flow;
 Snapshot s;
 first_pass(flow, s);
 at_park(flow, s, {2});
 drain(flow);
 flow.cancel(12);
 assert(view(flow).state == ScrubState::Cancelling && flow.outcome() == ScrubOutcome::Skip && flow.hold());
 assert(flow.facts().restored_requested && !flow.facts().saved_anyway);
 assert(drain(flow) == std::vector<std::string>({"_WMP_SCRUB_ATTENTION VALUE=0", "_WMP_OFFSETS_RESTORE", "_WMP_SCRUB_END"}));
 flow.cancel(13);
 assert(drain(flow).empty());
 s.restore = "done";
 s.scrub_phase = "ended";
 s.scrub_head = -1;
 flow.observe(s.json(), 14);
 assert(view(flow).state == ScrubState::Finished && !flow.hold() && flow.outcome() == ScrubOutcome::Skip);
}

void recheck_clean_visits_only_flagged_heads() {
 NozzleScrubFlow flow;
 Snapshot s;
 first_pass(flow, s);
 at_park(flow, s, {1, 3});
 drain(flow);
 const auto sent = clean_again(flow, s, {1, 3}, 20);
 assert(sent == std::vector<std::string>({"_WMP_SCRUB_ATTENTION VALUE=0", "_WMP_SCRUB_HEAD T=1", "_WMP_SCRUB_HEAT T=3",
                                          "_WMP_SCRUB_ATTENTION VALUE=1", "_WMP_SCRUB_ATTENTION VALUE=0", "_WMP_SCRUB_COOL T=1",
                                          "_WMP_SCRUB_HEAD T=3", "_WMP_SCRUB_ATTENTION VALUE=1", "_WMP_SCRUB_ATTENTION VALUE=0",
                                          "_WMP_SCRUB_COOL T=3", "RAPID_MODE T=1"}));
 assert(flow.facts().revisit == std::vector<unsigned>({1, 3}));
 assert(view(flow).state == ScrubState::Remeasure && flow.hold());
}

void recheck_head_one_flagged_remeasures_every_head() {
 NozzleScrubFlow flow;
 Snapshot s;
 first_pass(flow, s);
 at_park(flow, s, {0, 2});
 drain(flow);
 auto sent = clean_again(flow, s, {0, 2}, 20);
 assert(sent.back() == "RAPID_MODE T=0");
 sent.clear();
 for (unsigned h = 0; h < 4; ++h) {
  assert(view(flow).state == ScrubState::Remeasure && flow.hold());
  measure(flow, s, h, 40 + 2 * h);
  auto more = drain(flow);
  sent.insert(sent.end(), more.begin(), more.end());
 }
 assert(sent == std::vector<std::string>({"RAPID_MODE T=1", "RAPID_MODE T=2", "RAPID_MODE T=3"}));
 assert(view(flow).state == ScrubState::Calibrate && !flow.hold() && flow.outcome() == ScrubOutcome::Proceed);
 assert(!flow.facts().restored_requested && !flow.facts().saved_anyway);
}

void recheck_other_head_flagged_remeasures_only_it() {
 NozzleScrubFlow flow;
 Snapshot s;
 first_pass(flow, s);
 at_park(flow, s, {3});
 drain(flow);
 // The scrub status still shows head 4 heating with no target from the
 // first pass; it is not the repeat's heat.
 flow.select_recheck(ScrubChoice::Clean);
 flow.confirm(20);
 assert(drain(flow) == std::vector<std::string>({"_WMP_SCRUB_ATTENTION VALUE=0", "_WMP_SCRUB_HEAD T=3"}));
 flow.observe(s.json(), 21);
 assert(view(flow).state == ScrubState::Mounting && view(flow).head == 3);
 s.scrub_phase = "mounting";
 flow.observe(s.json(), 22);
 heat(flow, s, 3, 160, 23);
 assert(view(flow).state == ScrubState::Scrub && view(flow).head == 3);
 flow.confirm(24);
 assert(drain(flow) == std::vector<std::string>({"_WMP_SCRUB_ATTENTION VALUE=1", "_WMP_SCRUB_ATTENTION VALUE=0",
                                                 "_WMP_SCRUB_COOL T=3", "RAPID_MODE T=3"}));
 s.target[3] = 0;
 s.flagged.clear();
 measure(flow, s, 3, 30);
 assert(view(flow).state == ScrubState::Calibrate && !flow.hold() && drain(flow).empty());
 assert(flow.outcome() == ScrubOutcome::Proceed);
}

void remeasure_sends_next_only_after_measured_and_idle() {
 NozzleScrubFlow flow;
 Snapshot s;
 first_pass(flow, s);
 at_park(flow, s, {0});
 drain(flow);
 clean_again(flow, s, {0}, 20);
 assert(view(flow).state == ScrubState::Remeasure);
 // Status from before the command was admitted shows head 1 measured by the
 // first pass.
 flow.observe(s.json(), 30);
 assert(drain(flow).empty() && flow.hold());
 s.measuring = true;
 s.measured = {0, 1, 2, 3};
 flow.observe(s.json(), 31);
 assert(drain(flow).empty());
 s.measured = {1, 2, 3};
 flow.observe(s.json(), 32);
 assert(drain(flow).empty());
 s.measured = {0, 1, 2, 3};
 flow.observe(s.json(), 33);  // measured, still running
 assert(drain(flow).empty());
 s.measuring = false;
 Json stale = s.json();
 stale["fresh"] = false;
 flow.observe(stale, 34);
 assert(drain(flow).empty());
 Json other = s.json();
 other["calibration_progress"]["request"] = kOldRequest;
 flow.observe(other, 35);
 assert(drain(flow).empty());
 flow.observe(s.json(), 36);
 assert(drain(flow) == std::vector<std::string>({"RAPID_MODE T=1"}));
 // The progress text follows the measurement.
 s.progress_head = 1;
 s.progress_phase = "position";
 flow.observe(s.json(), 37);
 auto v = view(flow);
 assert(v.state == ScrubState::Remeasure && v.heading == "Head 2 of 4" && v.body == "Measuring nozzle position...");
 assert(v.note == "Keep the door closed." && !v.confirm_visible && !v.cancel_visible && !v.back_visible);
 // A failure of the attempt during the re-measurement ends it as in the first pass.
 s.failed = "Command failed: RAPID_MODE T=1";
 flow.observe(s.json(), 38);
 assert(view(flow).state == ScrubState::Calibrate && flow.outcome() == ScrubOutcome::Skip);
 assert(!flow.hold() && drain(flow).empty() && !flow.facts().restored_requested);
 flow.park_reached(39);
 assert(!flow.hold());
}

void recheck_repeats_when_a_head_is_flagged_again() {
 NozzleScrubFlow flow;
 Snapshot s;
 first_pass(flow, s);
 at_park(flow, s, {1, 3});
 drain(flow);
 clean_again(flow, s, {1, 3}, 20);
 measure(flow, s, 1, 30);
 assert(drain(flow) == std::vector<std::string>({"RAPID_MODE T=3"}));
 s.flagged = {3};
 measure(flow, s, 3, 32);
 assert(view(flow).state == ScrubState::Recheck && flow.hold());
 assert(flow.facts().flagged == std::vector<unsigned>({3}) && flow.facts().choice == ScrubChoice::Clean);
 assert(view(flow).heading == "Head 4 may not be clean");
 assert(drain(flow) == std::vector<std::string>({"_WMP_SCRUB_ATTENTION VALUE=1"}));
 const auto sent = clean_again(flow, s, {3}, 40);
 assert(sent.front() == "_WMP_SCRUB_ATTENTION VALUE=0" && sent.back() == "RAPID_MODE T=3");
 assert(std::count(sent.begin(), sent.end(), std::string("_WMP_SCRUB_HEAD T=3")) == 1 && sent.size() == 6);
 s.flagged = {};
 measure(flow, s, 3, 50);
 assert(view(flow).state == ScrubState::Calibrate && !flow.hold() && flow.outcome() == ScrubOutcome::Proceed);
}

void cancel_during_remeasure_waits_for_the_running_command_then_restores() {
 {
  NozzleScrubFlow flow;
  Snapshot s;
  first_pass(flow, s);
  at_park(flow, s, {0});
  drain(flow);
  clean_again(flow, s, {0}, 20);  // RAPID_MODE T=0 handed out
  s.measured = {1, 2, 3};
  s.measuring = true;
  flow.observe(s.json(), 30);
  flow.cancel(31);
  assert(view(flow).state == ScrubState::Remeasure && flow.hold() && drain(flow).empty());
  flow.cancel(32);
  flow.observe(s.json(), 33);
  assert(drain(flow).empty());
  s.measured = {0, 1, 2, 3};
  s.measuring = false;
  flow.observe(s.json(), 34);
  assert(drain(flow) == std::vector<std::string>({"_WMP_OFFSETS_RESTORE", "_WMP_SCRUB_END"}));
  assert(view(flow).state == ScrubState::Cancelling && flow.outcome() == ScrubOutcome::Skip);
  assert(flow.facts().restored_requested);
 }
 // A RAPID_MODE not yet handed out is dropped.
 NozzleScrubFlow flow;
 Snapshot s;
 first_pass(flow, s);
 at_park(flow, s, {2});
 drain(flow);
 flow.select_recheck(ScrubChoice::Clean);
 flow.confirm(20);
 drain(flow);
 heat(flow, s, 2, 160, 21);
 flow.confirm(22);
 flow.cancel(23);
 assert(drain(flow) == std::vector<std::string>({"_WMP_SCRUB_ATTENTION VALUE=1", "_WMP_SCRUB_ATTENTION VALUE=0", "_WMP_SCRUB_COOL T=2",
                                                 "_WMP_OFFSETS_RESTORE", "_WMP_SCRUB_END"}));
 assert(view(flow).state == ScrubState::Cancelling);
}

void cancel_during_repeat_heating_drops_next_heat_and_restores() {
 NozzleScrubFlow flow;
 Snapshot s;
 first_pass(flow, s);
 at_park(flow, s, {1, 2});
 drain(flow);
 flow.select_recheck(ScrubChoice::Clean);
 flow.confirm(20);
 assert(drain(flow) == std::vector<std::string>({"_WMP_SCRUB_ATTENTION VALUE=0", "_WMP_SCRUB_HEAD T=1"}));
 // The current head is really heating, with the next head's preheat queued
 // but not yet handed to the sender. Stop must discard that future work.
 heat(flow, s, 1, 100, 21);
 assert(view(flow).state == ScrubState::Heating);
 flow.cancel(22);
 flow.cancel(23);
 // Attention was already released when Clean again was selected.
 assert(drain(flow) == std::vector<std::string>({"_WMP_OFFSETS_RESTORE", "_WMP_SCRUB_END"}));
 assert(flow.facts().restored_requested && flow.outcome() == ScrubOutcome::Skip);
 assert(view(flow).state == ScrubState::Cancelling && flow.hold());
 s.restore = "done";
 s.scrub_phase = "ended";
 flow.observe(s.json(), 24);
 assert(view(flow).state == ScrubState::Finished && !flow.hold());
 assert(drain(flow).empty());
}

void cancel_during_repeat_scrub_cools_docks_and_restores() {
 {
  NozzleScrubFlow flow;
  Snapshot s;
  first_pass(flow, s);
  at_park(flow, s, {1, 2});
  drain(flow);
  flow.select_recheck(ScrubChoice::Clean);
  flow.confirm(20);
  drain(flow);
  heat(flow, s, 1, 160, 21);
  assert(view(flow).state == ScrubState::Scrub);
  drain(flow);
  flow.cancel(22);
  auto v = view(flow);
  assert(v.state == ScrubState::Cancelling && v.body == "Cooling and returning head 2 to its dock. Offsets are unchanged.");
  assert(drain(flow) == std::vector<std::string>({"_WMP_SCRUB_ATTENTION VALUE=0", "_WMP_OFFSETS_RESTORE", "_WMP_SCRUB_END"}));
  assert(flow.outcome() == ScrubOutcome::Skip && flow.facts().restored_requested);
  s.scrub_phase = "ended";
  flow.observe(s.json(), 23);
  assert(view(flow).state == ScrubState::Finished && !flow.hold());
 }
 // Cancel in the repeat's Mounting drops the queued mount.
 NozzleScrubFlow flow;
 Snapshot s;
 first_pass(flow, s);
 at_park(flow, s, {1});
 drain(flow);
 flow.select_recheck(ScrubChoice::Clean);
 flow.confirm(20);
 flow.cancel(21);
 assert(drain(flow) == std::vector<std::string>({"_WMP_SCRUB_ATTENTION VALUE=0", "_WMP_OFFSETS_RESTORE", "_WMP_SCRUB_END"}));
}

void stale_status_in_recheck_releases_after_the_limit_without_restore() {
 NozzleScrubFlow flow;
 Snapshot s;
 first_pass(flow, s);
 at_park(flow, s, {1});
 drain(flow);
 s.fresh = false;
 flow.observe(s.json(), 20);
 assert(!view(flow).confirm_enabled);
 flow.observe(s.json(), 139.9);
 assert(view(flow).state == ScrubState::Recheck && flow.hold() && drain(flow).empty());
 flow.observe(s.json(), 140);
 assert(view(flow).state == ScrubState::Cancelling && flow.outcome() == ScrubOutcome::Skip);
 assert(drain(flow) == std::vector<std::string>({"_WMP_SCRUB_ATTENTION VALUE=0", "_WMP_SCRUB_END"}));
 assert(!flow.facts().restored_requested);
 flow.observe(s.json(), 200);
 assert_failed_with(flow, kStatusLost);
 // The same limit applies during the re-measurement, without waiting for it.
 NozzleScrubFlow measuring;
 Snapshot m;
 first_pass(measuring, m);
 at_park(measuring, m, {1});
 drain(measuring);
 clean_again(measuring, m, {1}, 20);
 m.fresh = false;
 measuring.observe(m.json(), 30);
 measuring.observe(m.json(), 150);
 assert(view(measuring).state == ScrubState::Cancelling);
 assert(drain(measuring) == std::vector<std::string>({"_WMP_SCRUB_END"}));
 assert(!measuring.facts().restored_requested);
}

// A cancel waiting for a running RAPID_MODE is overtaken by the stale limit:
// END alone, no restore, and no wait for the command.
void stale_limit_overtakes_cancel_waiting_for_remeasure() {
 NozzleScrubFlow flow;
 Snapshot s;
 first_pass(flow, s);
 at_park(flow, s, {1});
 drain(flow);
 const auto sent = clean_again(flow, s, {1}, 20);  // RAPID_MODE T=1 handed out
 assert(sent.back() == "RAPID_MODE T=1");
 s.measured = {0, 2, 3};
 s.measuring = true;
 flow.observe(s.json(), 30);
 flow.cancel(31);
 assert(view(flow).state == ScrubState::Remeasure && flow.hold() && drain(flow).empty());
 s.fresh = false;
 flow.observe(s.json(), 40);
 flow.observe(s.json(), 159.9);
 assert(view(flow).state == ScrubState::Remeasure && drain(flow).empty());
 flow.observe(s.json(), 160);
 assert(view(flow).state == ScrubState::Cancelling && flow.outcome() == ScrubOutcome::Skip);
 assert(drain(flow) == std::vector<std::string>({"_WMP_SCRUB_END"}));
 assert(!flow.facts().restored_requested);
 // The RAPID_MODE completing afterwards sends nothing more.
 s.fresh = true;
 s.measured = {0, 1, 2, 3};
 s.measuring = false;
 flow.observe(s.json(), 161);
 assert(drain(flow).empty() && !flow.facts().restored_requested);
}

void restart_during_repeat_stops_without_restore() {
 NozzleScrubFlow flow;
 Snapshot s;
 first_pass(flow, s);
 at_park(flow, s, {1});
 drain(flow);
 flow.select_recheck(ScrubChoice::Clean);
 flow.confirm(20);
 drain(flow);
 heat(flow, s, 1, 100, 21);
 assert(view(flow).state == ScrubState::Heating);
 s.session = std::string(32, 'b');
 flow.observe(s.json(), 22);
 assert_failed_with(flow, "Printer restarted. Calibration stopped.");
 assert(drain(flow).empty() && !flow.facts().restored_requested);
}

void recheck_view_texts_for_one_two_and_four_heads() {
 struct Case { std::vector<unsigned> flagged; const char *heading, *body, *steps; };
 const char* const one = "Its measurement did not repeat, which usually means residue on the nozzle.";
 const char* const many = "Their measurements did not repeat, which usually means residue on the nozzle.";
 for (const auto& c : {Case{{1}, "Head 2 may not be clean", one, "ccfccr"},
                       Case{{1, 3}, "Heads 2 and 4 may not be clean", many, "ccfcfr"},
                       Case{{0, 1, 3}, "Heads 1, 2 and 4 may not be clean", many, "cffcfr"},
                       Case{{0, 1, 2, 3}, "Heads 1, 2, 3 and 4 may not be clean", many, "cffffr"}}) {
  NozzleScrubFlow flow;
  Snapshot s;
  first_pass(flow, s);
  at_park(flow, s, c.flagged);
  auto v = view(flow);
  assert(v.state == ScrubState::Recheck && v.heading == c.heading && v.body == c.body && v.note.empty());
  assert(v.option_title[0] == "Clean again" && v.option_detail[0] == "Scrub the flagged heads, then measure again.");
  assert(v.option_title[1] == "Save anyway" && v.option_detail[1] == "Keep the offsets as measured.");
  assert(v.first_selected && v.confirm_visible && v.confirm_enabled && v.cancel_visible && !v.back_visible);
  const Json panel = native::nozzle_scrub_panel_view(v);
  // The readings of the four heads in two columns (72 px) above the options (216 px).
  assert(panel["decisions"] == true && panel["choices_height"] == 72 + 216 && v.rows.size() == 4);
  assert(panel["heading"] == c.heading && panel["instruction"] == c.body && panel["note"] == "" && !panel.contains("value"));
  std::string steps;
  for (const auto& step : panel["steps"]) steps += step["state"].get<std::string>()[0];
  assert(steps == c.steps);
  flow.select_recheck(ScrubChoice::Save);
  assert(!view(flow).first_selected);
 }
 // Prepare carries its option texts in the same fields.
 NozzleScrubFlow prepare;
 Snapshot p;
 prepare.open(4, false, kSession);
 prepare.observe(p.json(), 0);
 auto v = view(prepare);
 assert(v.option_title[0] == "Wire brush" && v.option_detail[0] == "Scrub each heated nozzle by hand. Have a wire brush ready.");
 assert(v.option_title[1] == "Printed blob" && v.option_detail[1] == "Every head must be loaded with filament.");
 assert(v.first_selected);
 prepare.select(false);
 assert(!view(prepare).first_selected);
 // Remeasure: the Calibrate texts and steps.
 NozzleScrubFlow flow;
 Snapshot s;
 first_pass(flow, s);
 at_park(flow, s, {2});
 clean_again(flow, s, {2}, 20);
 v = view(flow);
 assert(v.state == ScrubState::Remeasure && v.heading == "Measuring nozzle offsets..." && v.note == "Keep the door closed.");
 const Json panel = native::nozzle_scrub_panel_view(v);
 // The decisions container holds the per-head readings, one row per head.
 assert(panel["decisions"] == true && panel["choices_height"] == 144 && v.rows.size() == 4);
 std::string steps;
 for (const auto& step : panel["steps"]) steps += step["state"].get<std::string>()[0];
 assert(steps == "cccccr");
}

void recheck_requests_attention_and_releases_it_on_each_choice() {
 for (int choice = 0; choice < 3; ++choice) {
  NozzleScrubFlow flow;
  Snapshot s;
  first_pass(flow, s);
  at_park(flow, s, {1});
  assert(drain(flow) == std::vector<std::string>({"_WMP_SCRUB_ATTENTION VALUE=1"}));
  if (choice == 2) flow.cancel(12);
  else {
   flow.select_recheck(choice == 0 ? ScrubChoice::Clean : ScrubChoice::Save);
   flow.confirm(12);
  }
  const auto sent = drain(flow);
  assert(!sent.empty() && sent.front() == "_WMP_SCRUB_ATTENTION VALUE=0");
  assert(std::count(sent.begin(), sent.end(), std::string("_WMP_SCRUB_ATTENTION VALUE=1")) == 0);
 }
}

void recheck_decides_only_on_final_flags() {
 {  // The last head's measurement is still running at the park send.
  NozzleScrubFlow flow;
  Snapshot s;
  first_pass(flow, s);
  s.measured = {0, 1, 2};
  s.measuring = true;
  at_park(flow, s, {});
  assert(view(flow).state == ScrubState::Calibrate && flow.hold() && drain(flow).empty());
  s.measured = {0, 1, 2, 3};
  s.measuring = false;
  s.flagged = {3};
  flow.observe(s.json(), 12);
  assert(view(flow).state == ScrubState::Recheck && flow.hold());
  assert(flow.facts().flagged == std::vector<unsigned>({3}));
  assert(drain(flow) == std::vector<std::string>({"_WMP_SCRUB_ATTENTION VALUE=1"}));
 }
 {  // Final without flags: released.
  NozzleScrubFlow flow;
  Snapshot s;
  first_pass(flow, s);
  s.measuring = true;
  at_park(flow, s, {});
  assert(flow.hold());
  s.measuring = false;
  flow.observe(s.json(), 12);
  assert(view(flow).state == ScrubState::Calibrate && !flow.hold() && drain(flow).empty());
  assert(flow.outcome() == ScrubOutcome::Proceed);
 }
 {  // Never final: released after the stale limit, as today.
  NozzleScrubFlow flow;
  Snapshot s;
  first_pass(flow, s);
  s.measured = {0, 1, 2};
  at_park(flow, s, {}, 11);
  flow.observe(s.json(), 130.9);
  assert(flow.hold());
  flow.observe(s.json(), 131);
  assert(view(flow).state == ScrubState::Calibrate && !flow.hold() && drain(flow).empty());
  assert(flow.outcome() == ScrubOutcome::Proceed);
 }
 {  // Status stale while waiting: released after the stale limit.
  NozzleScrubFlow flow;
  Snapshot s;
  first_pass(flow, s);
  s.measuring = true;
  at_park(flow, s, {}, 11);
  s.fresh = false;
  flow.observe(s.json(), 20);
  flow.observe(s.json(), 120);
  assert(flow.hold());
  flow.observe(s.json(), 140);
  assert(view(flow).state == ScrubState::Calibrate && !flow.hold() && drain(flow).empty());
 }
 {  // The attempt fails while waiting: released with Skip.
  NozzleScrubFlow flow;
  Snapshot s;
  first_pass(flow, s);
  s.measuring = true;
  at_park(flow, s, {});
  s.failed = "Command failed: RAPID_MODE T=3";
  flow.observe(s.json(), 12);
  assert(!flow.hold() && flow.outcome() == ScrubOutcome::Skip && drain(flow).empty());
 }
 {  // Klipper restarts while waiting: released.
  NozzleScrubFlow flow;
  Snapshot s;
  first_pass(flow, s);
  s.measuring = true;
  at_park(flow, s, {});
  s.session = std::string(32, 'b');
  flow.observe(s.json(), 12);
  assert(!flow.hold() && drain(flow).empty());
 }
}

void remeasure_starts_without_first_pass_progress() {
 NozzleScrubFlow flow;
 Snapshot s;
 first_pass(flow, s);
 s.progress_head = 3;
 s.progress_phase = "docking";
 at_park(flow, s, {2});
 assert(view(flow).state == ScrubState::Recheck);
 drain(flow);
 clean_again(flow, s, {2}, 20);
 const auto v = view(flow);
 assert(v.state == ScrubState::Remeasure && v.heading == "Measuring nozzle offsets..." && v.body.empty());
 assert(flow.facts().progress_head == -1 && flow.facts().known_progress_head == -1 && flow.facts().progress_phase == "unavailable");
}

void cancelling_text_names_a_mounted_head_and_unchanged_offsets_only() {
 const auto cancelling = [](const NozzleScrubFlow& flow, const char* body) {
  const auto v = view(flow);
  assert(v.state == ScrubState::Cancelling && v.heading == "Cancelling..." && v.body == body);
 };
 {  // Cancel from Recheck: restored, no head mounted.
  NozzleScrubFlow flow;
  Snapshot s;
  first_pass(flow, s);
  at_park(flow, s, {1});
  flow.cancel(12);
  cancelling(flow, "Offsets are unchanged.");
  s.scrub_phase = "ended";
  flow.observe(s.json(), 13);
  assert(view(flow).state == ScrubState::Finished && view(flow).body == "Offsets are unchanged.");
 }
 {  // Stale cancel from Recheck: nothing restored, no head mounted.
  NozzleScrubFlow flow;
  Snapshot s;
  first_pass(flow, s);
  at_park(flow, s, {1});
  s.fresh = false;
  flow.observe(s.json(), 20);
  flow.observe(s.json(), 140);
  cancelling(flow, "");
 }
 {  // Cancel from Remeasure after the running command.
  NozzleScrubFlow flow;
  Snapshot s;
  first_pass(flow, s);
  at_park(flow, s, {1});
  clean_again(flow, s, {1}, 20);
  s.measured = {0, 2, 3};
  s.measuring = true;
  flow.observe(s.json(), 30);
  flow.cancel(31);
  s.measured = {0, 1, 2, 3};
  s.measuring = false;
  flow.observe(s.json(), 32);
  cancelling(flow, "Offsets are unchanged.");
 }
 {  // Stale cancel from Remeasure.
  NozzleScrubFlow flow;
  Snapshot s;
  first_pass(flow, s);
  at_park(flow, s, {1});
  clean_again(flow, s, {1}, 20);
  s.fresh = false;
  flow.observe(s.json(), 30);
  flow.observe(s.json(), 150);
  cancelling(flow, "");
 }
 {  // Stale cancel during a repeat scrub: the head is mounted, offsets were measured.
  NozzleScrubFlow flow;
  Snapshot s;
  first_pass(flow, s);
  at_park(flow, s, {1});
  flow.select_recheck(ScrubChoice::Clean);
  flow.confirm(20);
  heat(flow, s, 1, 160, 21);
  assert(view(flow).state == ScrubState::Scrub);
  s.fresh = false;
  flow.observe(s.json(), 22);
  flow.observe(s.json(), 142);
  cancelling(flow, "Cooling and returning head 2 to its dock.");
  assert(!flow.facts().restored_requested);
 }
}

void restore_send_failure_clears_the_restore_request() {
 {  // The restore itself could not be sent.
  NozzleScrubFlow flow;
  Snapshot s;
  first_pass(flow, s);
  at_park(flow, s, {1});
  drain(flow);
  flow.cancel(12);
  std::string command;
  assert(flow.next_command(command) && command == "_WMP_SCRUB_ATTENTION VALUE=0");
  assert(flow.next_command(command) && command == "_WMP_OFFSETS_RESTORE");
  flow.send_failed(command, 13);
  assert(!flow.facts().restored_requested && view(flow).state == ScrubState::Cancelling);
  assert(drain(flow) == std::vector<std::string>({"_WMP_SCRUB_END"}));
  assert(view(flow).body.empty());
 }
 {  // A send failure before the restore was handed out drops it.
  NozzleScrubFlow flow;
  Snapshot s;
  first_pass(flow, s);
  at_park(flow, s, {1});
  drain(flow);
  flow.cancel(12);
  std::string command;
  assert(flow.next_command(command) && command == "_WMP_SCRUB_ATTENTION VALUE=0");
  flow.send_failed(command, 13);
  assert(!flow.facts().restored_requested);
  assert(drain(flow) == std::vector<std::string>({"_WMP_SCRUB_END"}));
 }
 {  // A restore that was sent stays requested when a later send fails.
  NozzleScrubFlow flow;
  Snapshot s;
  first_pass(flow, s);
  at_park(flow, s, {1});
  drain(flow);
  flow.cancel(12);
  std::string command;
  flow.next_command(command);
  flow.next_command(command);
  assert(flow.next_command(command) && command == "_WMP_SCRUB_END");
  flow.send_failed(command, 13);
  assert(flow.facts().restored_requested && view(flow).state == ScrubState::Failed);
 }
}

void restart_in_recheck_and_remeasure_stops_without_restore() {
 for (const bool measuring : {false, true}) {
  NozzleScrubFlow flow;
  Snapshot s;
  first_pass(flow, s);
  at_park(flow, s, {1});
  drain(flow);
  if (measuring) {
   clean_again(flow, s, {1}, 20);
   assert(view(flow).state == ScrubState::Remeasure);
  } else assert(view(flow).state == ScrubState::Recheck);
  s.session = std::string(32, 'b');
  flow.observe(s.json(), 30);
  assert_failed_with(flow, "Printer restarted. Calibration stopped.");
  assert(drain(flow).empty() && !flow.facts().restored_requested);
 }
}

// The view StockProgressPanel::update() consumes, for every flow state.
Json step(const char* label, const char* state) { return Json{{"label", label}, {"state", state}}; }

// One projected nozzle_touch head entry.
Json reading(unsigned head, int centres, double span, bool flagged = false) {
 return {{"head", head}, {"centres", centres}, {"centre_span", span}, {"flagged", flagged}};
}

using Row = std::pair<ScrubMark, std::string>;
const Row kBlank{ScrubMark::None, ""};

// The Calibrate rows: "Head N" for every head of the run, then mark and centre span.
void assert_rows(const NozzleScrubFlow& flow, const std::vector<Row>& expected) {
 const auto v = view(flow);
 assert(v.rows.size() == expected.size());
 for (std::size_t i = 0; i < expected.size(); ++i)
  assert(v.rows[i].name == "Head " + std::to_string(i + 1) && v.rows[i].mark == expected[i].first && v.rows[i].span == expected[i].second);
}

// Scrubs every head of a four-head run and stops in Calibrate before any
// measurement status.
void to_calibrate(NozzleScrubFlow& flow, Snapshot& s, unsigned heads = 4) {
 start(flow, s, heads, false);
 for (unsigned h = 0; h < heads; ++h) {
  heat(flow, s, h, 160, 1 + h);
  flow.confirm(2 + h);
  s.target[h] = 0;
 }
 drain(flow);
 assert(view(flow).state == ScrubState::Calibrate);
}

void calibrate_shows_each_heads_readings() {
 NozzleScrubFlow flow;
 Snapshot s;
 // Before Calibrate there are no rows.
 start(flow, s, 4, false);
 assert(view(flow).rows.empty());
 heat(flow, s, 0, 160, 1);
 assert(view(flow).state == ScrubState::Scrub && view(flow).rows.empty());
 flow.close();
 to_calibrate(flow, s);
 // No readings: one blank row per head.
 assert_rows(flow, {kBlank, kBlank, kBlank, kBlank});
 // Head 1 is being measured; before its first centre the row stays blank.
 s.progress_head = 0;
 s.progress_phase = "position";
 s.measuring = true;
 s.touch_heads = Json::array({reading(0, 0, 0)});
 flow.observe(s.json(), 20);
 assert_rows(flow, {kBlank, kBlank, kBlank, kBlank});
 s.touch_heads = Json::array({reading(0, 1, 0.0062)});
 flow.observe(s.json(), 21);
 assert_rows(flow, {{ScrubMark::Measuring, "0.006 mm"}, kBlank, kBlank, kBlank});
 // A flag shows at once, while the head is still being measured.
 s.touch_heads = Json::array({reading(0, 2, 0.0131, true)});
 flow.observe(s.json(), 22);
 assert_rows(flow, {{ScrubMark::Flagged, "0.013 mm"}, kBlank, kBlank, kBlank});
 // Head 1 measured without a flag, head 2 being measured.
 s.touch_heads = Json::array({reading(0, 4, 0.0062), reading(1, 1, 0.003)});
 s.measured = {0};
 s.progress_head = 1;
 flow.observe(s.json(), 23);
 assert_rows(flow, {{ScrubMark::Passed, "0.006 mm"}, {ScrubMark::Measuring, "0.003 mm"}, kBlank, kBlank});
 // Stale status changes nothing.
 Json stale = s.json();
 stale["fresh"] = false;
 stale["nozzle_touch"]["heads"] = Json::array();
 flow.observe(stale, 24);
 assert_rows(flow, {{ScrubMark::Passed, "0.006 mm"}, {ScrubMark::Measuring, "0.003 mm"}, kBlank, kBlank});
 // Every head measured, head 3 flagged; no measurement runs.
 s.touch_heads = Json::array({reading(0, 4, 0.0062), reading(1, 4, 0.003), reading(2, 4, 0.0217, true), reading(3, 4, 0)});
 s.measured = {0, 1, 2, 3};
 s.measuring = false;
 s.progress_head = 3;
 s.progress_phase = "docking";
 flow.observe(s.json(), 25);
 assert_rows(flow, {{ScrubMark::Passed, "0.006 mm"}, {ScrubMark::Passed, "0.003 mm"}, {ScrubMark::Flagged, "0.022 mm"}, {ScrubMark::Passed, "0.000 mm"}});
 // Touch status of another request is not shown.
 s.touch_request = kOldRequest;
 flow.observe(s.json(), 26);
 assert_rows(flow, {kBlank, kBlank, kBlank, kBlank});
 // Touch status of this request with progress of another: the marks need
 // this request's progress; a flag needs none.
 s.touch_request = kRequest;
 Json other = s.json();
 other["calibration_progress"]["request"] = kOldRequest;
 flow.observe(other, 27);
 assert_rows(flow, {{ScrubMark::None, "0.006 mm"}, {ScrubMark::None, "0.003 mm"}, {ScrubMark::Flagged, "0.022 mm"}, {ScrubMark::None, "0.000 mm"}});
 // Without nozzle touch status every row is blank.
 s.touch = false;
 flow.observe(s.json(), 28);
 assert_rows(flow, {kBlank, kBlank, kBlank, kBlank});
}

void readings_ignore_heads_outside_the_run() {
 NozzleScrubFlow flow;
 Snapshot s;
 to_calibrate(flow, s, 2);
 s.progress_head = 1;
 s.progress_phase = "height";
 s.measured = {0};
 s.measuring = true;
 s.touch_heads = Json::array({reading(0, 4, 0.001), reading(1, 2, 0.002), reading(3, 4, 0.05, true)});
 flow.observe(s.json(), 20);
 assert_rows(flow, {{ScrubMark::Passed, "0.001 mm"}, {ScrubMark::Measuring, "0.002 mm"}});
}

void remeasure_resets_a_heads_row() {
 NozzleScrubFlow flow;
 Snapshot s;
 s.touch_heads = Json::array({reading(0, 4, 0.002), reading(1, 4, 0.02, true), reading(2, 4, 0.003), reading(3, 4, 0.004)});
 first_pass(flow, s);
 assert_rows(flow, {{ScrubMark::Passed, "0.002 mm"}, {ScrubMark::Flagged, "0.020 mm"}, {ScrubMark::Passed, "0.003 mm"}, {ScrubMark::Passed, "0.004 mm"}});
 at_park(flow, s, {1});
 assert(view(flow).state == ScrubState::Recheck);
 drain(flow);
 clean_again(flow, s, {1}, 20);
 assert(view(flow).state == ScrubState::Remeasure);
 // Until head 2 is mounted again its row shows the earlier measurement.
 assert_rows(flow, {{ScrubMark::Passed, "0.002 mm"}, {ScrubMark::Flagged, "0.020 mm"}, {ScrubMark::Passed, "0.003 mm"}, {ScrubMark::Passed, "0.004 mm"}});
 // RAPID_MODE T=1 starts: the backend drops head 2's groups and its flag.
 s.measured = {0, 2, 3};
 s.measuring = true;
 s.progress_head = 1;
 s.progress_phase = "mounting";
 s.touch_heads[1] = reading(1, 0, 0);
 flow.observe(s.json(), 30);
 assert_rows(flow, {{ScrubMark::Passed, "0.002 mm"}, kBlank, {ScrubMark::Passed, "0.003 mm"}, {ScrubMark::Passed, "0.004 mm"}});
 s.progress_phase = "position";
 s.touch_heads[1] = reading(1, 2, 0.0041);
 flow.observe(s.json(), 31);
 assert_rows(flow, {{ScrubMark::Passed, "0.002 mm"}, {ScrubMark::Measuring, "0.004 mm"}, {ScrubMark::Passed, "0.003 mm"}, {ScrubMark::Passed, "0.004 mm"}});
 s.measured = {0, 1, 2, 3};
 s.measuring = false;
 s.touch_heads[1] = reading(1, 4, 0.0041);
 flow.observe(s.json(), 32);
 assert(view(flow).state == ScrubState::Calibrate);
 assert_rows(flow, {{ScrubMark::Passed, "0.002 mm"}, {ScrubMark::Passed, "0.004 mm"}, {ScrubMark::Passed, "0.003 mm"}, {ScrubMark::Passed, "0.004 mm"}});
}

const std::vector<std::string> kAttentionOn{"_WMP_SCRUB_ATTENTION VALUE=1"}, kAttentionOff{"_WMP_SCRUB_ATTENTION VALUE=0"};

// Head 1 of a two-head run reaches Scrub at t=10 with the signal on.
void scrub_with_attention(NozzleScrubFlow& flow, Snapshot& s) {
 start(flow, s, 2, false);
 drain(flow);
 heat(flow, s, 0, 160, 10);
 assert(view(flow).state == ScrubState::Scrub);
 assert(drain(flow) == std::vector<std::string>({"_WMP_SCRUB_HEAT T=1", "_WMP_SCRUB_ATTENTION VALUE=1"}));
}

void touch_stops_attention_once() {
 NozzleScrubFlow flow;
 Snapshot s;
 scrub_with_attention(flow, s);
 // A touch from before the signal started does not stop it.
 flow.touched(9.5);
 assert(drain(flow).empty());
 flow.touched(12);
 assert(drain(flow) == kAttentionOff);
 // The state is unchanged and the signal is not requested again in it.
 flow.touched(13);
 flow.observe(s.json(), 14);
 assert(view(flow).state == ScrubState::Scrub && drain(flow).empty() && flow.hold());
 // CONFIRM still works and sends no second release.
 assert(!flow.confirm(15));
 assert(drain(flow) == std::vector<std::string>({"_WMP_SCRUB_COOL T=0", "_WMP_SCRUB_HEAD T=1"}));
 // The next Scrub entry requests it again.
 heat(flow, s, 1, 160, 20);
 assert(view(flow).state == ScrubState::Scrub && drain(flow) == kAttentionOn);
 flow.touched(21);
 assert(drain(flow) == kAttentionOff);
 // So does Cooled after a touch in Scrub.
 flow.observe(s.json(), 20 + 600);
 assert(view(flow).state == ScrubState::Cooled);
 assert(drain(flow) == std::vector<std::string>({"_WMP_SCRUB_COOL", "_WMP_SCRUB_ATTENTION VALUE=1"}));
 // A touch in Cooled stops it; CONFIRM then sends no second release.
 flow.touched(621);
 assert(drain(flow) == kAttentionOff);
 assert(!flow.confirm(622));
 assert(drain(flow) == std::vector<std::string>({"_WMP_SCRUB_HEAT T=1"}));
 // Without the signal on a touch sends nothing.
 flow.touched(623);
 assert(drain(flow).empty());
}

void door_opening_stops_attention() {
 NozzleScrubFlow flow;
 Snapshot s;
 scrub_with_attention(flow, s);
 flow.observe(s.json(), 11);
 assert(drain(flow).empty());
 // Door 2 opens.
 s.doors = 2;
 flow.observe(s.json(), 12);
 assert(drain(flow) == kAttentionOff && view(flow).state == ScrubState::Scrub);
 // Further door changes send nothing more.
 s.doors = 3;
 flow.observe(s.json(), 13);
 s.doors = 0;
 flow.observe(s.json(), 14);
 assert(drain(flow).empty());
 // Stale status is not evidence of a door: the opening counts once fresh.
 NozzleScrubFlow stale;
 Snapshot t;
 scrub_with_attention(stale, t);
 t.doors = 1;
 t.fresh = false;
 stale.observe(t.json(), 11);
 assert(drain(stale).empty());
 t.fresh = true;
 stale.observe(t.json(), 12);
 assert(drain(stale) == kAttentionOff);
 // An unknown door state in between keeps the last known state.
 NozzleScrubFlow unknown;
 Snapshot u;
 scrub_with_attention(unknown, u);
 u.doors = -1;
 unknown.observe(u.json(), 11);
 assert(drain(unknown).empty());
 u.doors = 1;
 unknown.observe(u.json(), 12);
 assert(drain(unknown) == kAttentionOff);
}

void door_open_before_the_signal_keeps_it_on() {
 NozzleScrubFlow flow;
 Snapshot s;
 s.doors = 1;
 scrub_with_attention(flow, s);
 flow.observe(s.json(), 11);
 assert(drain(flow).empty());
 // Closing the door changes nothing; opening it again stops the signal.
 s.doors = 0;
 flow.observe(s.json(), 12);
 assert(drain(flow).empty());
 s.doors = 1;
 flow.observe(s.json(), 13);
 assert(drain(flow) == kAttentionOff);
 // The other door opening while the first stays open counts as well.
 NozzleScrubFlow other;
 Snapshot t;
 t.doors = 1;
 scrub_with_attention(other, t);
 t.doors = 3;
 other.observe(t.json(), 11);
 assert(drain(other) == kAttentionOff);
 // The door that opens in the status that also starts the signal is not an
 // opening after it.
 NozzleScrubFlow same;
 Snapshot u;
 start(same, u, 2, false);
 drain(same);
 u.doors = 1;
 heat(same, u, 0, 160, 10);
 assert(view(same).state == ScrubState::Scrub);
 assert(drain(same) == std::vector<std::string>({"_WMP_SCRUB_HEAT T=1", "_WMP_SCRUB_ATTENTION VALUE=1"}));
 same.observe(u.json(), 11);
 assert(drain(same).empty());
}

void return_prompt_and_recheck_signal_stops_and_returns() {
 NozzleScrubFlow prompt;
 Snapshot s;
 start(prompt, s, 2, true, 5);
 assert(view(prompt).state == ScrubState::ReturnPrompt && drain(prompt) == kAttentionOn);
 prompt.touched(6);
 assert(drain(prompt) == kAttentionOff && view(prompt).state == ScrubState::ReturnPrompt);
 assert(!prompt.confirm(7));
 assert(drain(prompt) == std::vector<std::string>({"_WMP_SCRUB_HEAD T=0"}));
 // Re-check: stopped by a door, requested again on the next Re-check entry.
 NozzleScrubFlow flow;
 Snapshot r;
 first_pass(flow, r);
 at_park(flow, r, {1});
 assert(view(flow).state == ScrubState::Recheck && drain(flow) == kAttentionOn);
 r.doors = 1;
 flow.observe(r.json(), 12);
 assert(drain(flow) == kAttentionOff && view(flow).state == ScrubState::Recheck);
 const auto sent = clean_again(flow, r, {1}, 20);
 assert(std::count(sent.begin(), sent.end(), kAttentionOff[0]) == 1 && std::count(sent.begin(), sent.end(), kAttentionOn[0]) == 1);
 r.flagged = {1};
 measure(flow, r, 1, 30);
 assert(view(flow).state == ScrubState::Recheck && drain(flow) == kAttentionOn);
 flow.touched(32);
 assert(drain(flow) == kAttentionOff);
}

void recheck_shows_each_heads_readings() {
 NozzleScrubFlow flow;
 Snapshot s;
 s.touch_heads = Json::array({reading(0, 6, 0.0083), reading(1, 6, 0.0412, true), reading(2, 6, 0.0141), reading(3, 6, 0.0172)});
 first_pass(flow, s);
 at_park(flow, s, {1});
 assert(view(flow).state == ScrubState::Recheck);
 assert_rows(flow, {{ScrubMark::Passed, "0.008 mm"}, {ScrubMark::Flagged, "0.041 mm"}, {ScrubMark::Passed, "0.014 mm"}, {ScrubMark::Passed, "0.017 mm"}});
 // The texts and options are unchanged.
 const auto v = view(flow);
 assert(v.heading == "Head 2 may not be clean" && v.option_title[0] == "Clean again" && v.option_title[1] == "Save anyway");
 // Two heads: one line of two rows above the options.
 NozzleScrubFlow two;
 Snapshot t;
 t.touch_heads = Json::array({reading(0, 6, 0.05, true), reading(1, 6, 0.01)});
 first_pass(two, t, 2);
 at_park(two, t, {0});
 assert_rows(two, {{ScrubMark::Flagged, "0.050 mm"}, {ScrubMark::Passed, "0.010 mm"}});
 assert(native::nozzle_scrub_panel_view(view(two))["choices_height"] == 36 + 216);
 // Three heads: two lines.
 NozzleScrubFlow three;
 Snapshot u;
 u.touch_heads = Json::array({reading(0, 6, 0.01), reading(1, 6, 0.01), reading(2, 6, 0.05, true)});
 first_pass(three, u, 3);
 at_park(three, u, {2});
 assert(view(three).rows.size() == 3 && native::nozzle_scrub_panel_view(view(three))["choices_height"] == 72 + 216);
 // Prepare has no rows.
 NozzleScrubFlow prepare;
 prepare.open(4, false, kSession);
 assert(view(prepare).rows.empty() && native::nozzle_scrub_panel_view(view(prepare))["choices_height"] == 216);
}

void panel_view_for_every_state() {
 const char* const title = "Nozzle offset calibration";
 const Json all_pending = Json::array({step("Prepare", "running"), step("Head 1", "pending"), step("Head 2", "pending"), step("Calibrate", "pending")});
 const Json on_head_2 = Json::array({step("Prepare", "complete"), step("Head 1", "complete"), step("Head 2", "running"), step("Calibrate", "pending")});
 // heading, value, instruction and note are separate panel fields.
 const auto shows = [&](const Json& steps, const char* heading, const std::string& instruction, const char* note, const char* value = nullptr) {
  Json expected = {{"title", title}, {"title_width", 540}, {"steps", steps}, {"steps_width", 200}, {"decisions", false},
                   {"heading", heading}, {"instruction", instruction}, {"note", note}};
  if (value) expected["value"] = value;
  return expected;
 };
 // Prepare: the only state with decisions.
 NozzleScrubFlow flow;
 Snapshot s;
 s.heads = 2;
 flow.open(2, true, kSession);
 flow.observe(s.json(), 0);
 Json panel = native::nozzle_scrub_panel_view(view(flow));
 Json prepare = shows(all_pending, "How will the nozzles be cleaned?", "", "");
 prepare["decisions"] = true;
 prepare["choices_height"] = 216;
 assert(panel == prepare);
 // StockChecks: no text; still on the first step.
 assert(flow.confirm(0));
 flow.bind(kRequest);
 panel = native::nozzle_scrub_panel_view(view(flow));
 assert(view(flow).state == ScrubState::StockChecks);
 assert(panel == shows(all_pending, "", "", ""));
 // ReturnPrompt: heading and instruction.
 flow.offset_stage_reached(0);
 const Json on_head_1 = Json::array({step("Prepare", "complete"), step("Head 1", "running"), step("Head 2", "pending"), step("Calibrate", "pending")});
 panel = native::nozzle_scrub_panel_view(view(flow));
 assert(panel == shows(on_head_1, "Ready to clean the nozzles.", "Press Confirm to start.", ""));
 // Mounting: heading alone.
 flow.confirm(1);
 panel = native::nozzle_scrub_panel_view(view(flow));
 assert(panel == shows(on_head_1, "Mounting head 1...", "", ""));
 // Heating: the temperature is the panel value, in whole degrees.
 drain(flow);
 Json raw;
 s.scrub_head = 0;
 s.scrub_phase = "heating";
 s.target[0] = 160;
 raw = s.json();
 raw["heads"][0]["actual"] = 126.6;
 flow.observe(raw, 2);
 assert(view(flow).state == ScrubState::Heating);
 panel = native::nozzle_scrub_panel_view(view(flow));
 assert(panel == shows(on_head_1, "Heating head 1...", "", "", "127 / 160 \xc2\xb0""C"));
 // Unknown temperatures read "--".
 ScrubView unknown = view(flow);
 unknown.actual = std::nan("");
 unknown.target = std::nan("");
 assert(native::nozzle_scrub_panel_view(unknown)["value"] == "-- / -- \xc2\xb0""C");
 // Scrub: heading, body and note.
 heat(flow, s, 0, 160, 3);
 panel = native::nozzle_scrub_panel_view(view(flow));
 assert(panel == shows(on_head_1, "Scrub the nozzle on head 1", "Brush the nozzle tip until it is clean, then press Confirm.", "The nozzle is hot."));
 // Cooled, on the second head.
 flow.confirm(4);
 heat(flow, s, 1, 160, 5);
 flow.observe(s.json(), 5 + 600);
 assert(view(flow).state == ScrubState::Cooled && view(flow).head == 1);
 panel = native::nozzle_scrub_panel_view(view(flow));
 assert(panel == shows(on_head_2, "Head 2 has cooled.", "Press Confirm to reheat.", ""));
 // Cancelling and Finished share their text.
 flow.cancel(606);
 assert(view(flow).state == ScrubState::Cancelling);
 panel = native::nozzle_scrub_panel_view(view(flow));
 assert(panel == shows(on_head_2, "Cancelling...", "Cooling and returning head 2 to its dock. Offsets are unchanged.", ""));
 s.scrub_phase = "ended";
 flow.observe(s.json(), 607);
 assert(view(flow).state == ScrubState::Finished);
 assert(native::nozzle_scrub_panel_view(view(flow)) == panel);
 // Failed: the current step is marked failed; instruction and note, no heading.
 NozzleScrubFlow failed;
 Snapshot f;
 start(failed, f, 2, false);
 drain(failed);
 heat(failed, f, 0, 160, 1);
 failed.confirm(2);
 f.scrub_head = 1;
 f.scrub_phase = "failed";
 f.scrub_error = "Head 2 did not mount.";
 failed.observe(f.json(), 3);
 assert(view(failed).state == ScrubState::Failed);
 panel = native::nozzle_scrub_panel_view(view(failed));
 const Json failed_steps = Json::array({step("Prepare", "complete"), step("Head 1", "complete"), step("Head 2", "failed"), step("Calibrate", "pending")});
 assert(panel == shows(failed_steps, "", "Head 2 did not mount.", "The nozzle may still be hot."));
 // Calibrate: every earlier step complete, for one to four heads.
 for (unsigned heads = 1; heads <= 4; ++heads) {
  NozzleScrubFlow done;
  Snapshot d;
  start(done, d, heads, false);
  for (unsigned h = 0; h < heads; ++h) {
   heat(done, d, h, 160, 1);
   done.confirm(2);
  }
  assert(view(done).state == ScrubState::Calibrate);
  d.progress_head = 0;
  d.progress_phase = "height";
  done.observe(d.json(), 3);
  panel = native::nozzle_scrub_panel_view(view(done));
  Json steps = Json::array({step("Prepare", "complete")});
  for (unsigned h = 0; h < heads; ++h) steps.push_back({{"label", "Head " + std::to_string(h + 1)}, {"state", "complete"}});
  steps.push_back(step("Calibrate", "running"));
  // The per-head readings take the decisions container, one 36 px row per head.
  Json expected = shows(steps, ("Head 1 of " + std::to_string(heads)).c_str(), "Measuring nozzle height...", "Keep the door closed.");
  expected["decisions"] = true;
  expected["choices_height"] = 36 * heads;
  assert(panel == expected);
 }
 // Idle (closed flow): nothing to say and no decisions.
 NozzleScrubFlow idle;
 panel = native::nozzle_scrub_panel_view(view(idle));
 assert(panel["title"] == title && panel["heading"] == "" && panel["instruction"] == "" && panel["note"] == "" && panel["decisions"] == false && !panel.contains("value"));
}
}  // namespace

int main() {
 // Out-of-band cancellation waits for its own cleanup receipt; it queues no END.
 {
  NozzleScrubFlow flow;Snapshot snapshot;
  flow.open(2,false,kSession);flow.observe(snapshot.json(),0);assert(flow.confirm(0));flow.bind(kRequest);
  assert(flow.cancel_out_of_band(1));assert(flow.facts().state==ScrubState::Cancelling);
  std::string command;assert(!flow.next_command(command));
  flow.send_failed("_WMP_SCRUB_HEAD T=0",1);assert(!flow.next_command(command));
  auto data=snapshot.json();data["calibration_attempt"]["state"]="failed";data["calibration_attempt"]["cancel_requested"]=true;
  flow.observe(data,2);assert(flow.facts().state==ScrubState::Cancelling);
  data["calibration_attempt"]["cancel_cleanup"]={{"state","complete"},{"offsets","restored"},{"park","parked"},{"error",""}};
  data["calibration_attempt"]["request"]=kOldRequest;flow.observe(data,3);assert(flow.facts().state==ScrubState::Cancelling);
  data["calibration_attempt"]["request"]=kRequest;flow.observe(data,4);
  assert(flow.facts().state==ScrubState::Finished&&flow.outcome()==ScrubOutcome::Skip);
  assert(flow.facts().offsets_unchanged&&!flow.next_command(command));
 }
 prepare_defaults_to_brush_and_exact_text();
 blob_choice_never_holds();
 offsets_only_run_skips_return_prompt();
 combined_run_shows_return_prompt();
 head_sequence_commands();
 heating_shows_temperature();
 scrub_at_157_5();
 timeout_after_600_seconds_cools_and_offers_reheat();
 external_target_clear_during_heating_becomes_cooled();
 double_confirm_queues_one_command();
 three_heads();
 stale_status_disables_confirm();
 session_change_while_held_releases_with_skip();
 cancel_mid_scrub_queues_end_and_skips();
 backend_failure_shows_one_sentence_and_back();
 failure_during_probing_skips_the_rest();
 calibrate_progress_text();
 cancelling_times_out_after_60_seconds_stale();
 cancelling_times_out_after_refused_end();
 stale_status_for_120_seconds_cancels_then_fails();
 fresh_status_resets_stale_timer();
 send_failure_after_last_confirm_sends_end_and_skips();
 send_failure_with_attention_on_sends_only_end();
 second_send_failure_on_end_fails_with_hot_note();
 send_failure_never_mounts_next_head();
 user_cancel_drops_queued_head_and_heat();
 failed_note_absent_before_scrub_started();
 stale_failed_status_from_previous_attempt_is_ignored();
 stale_ended_status_from_previous_attempt_is_ignored();
 status_for_bound_request_fails_normally();
 never_admitted_run_cancels_after_120_seconds();
 cancelling_bound_pauses_while_backend_is_executing();
 cancelling_absolute_cap_after_300_seconds();
 refused_attempt_with_foreign_scrub_status_stops();
 refused_attempt_with_own_scrub_status_stops_with_hot_note();
 refused_attempt_without_own_scrub_status_stops_without_hot_note();
 refused_attempt_during_calibrate_stops();
 panel_view_for_every_state();
 recheck_entered_only_with_flags_fresh_status_and_brush_run();
 recheck_save_releases_with_proceed();
 recheck_cancel_restores_then_ends_and_skips();
 recheck_clean_visits_only_flagged_heads();
 recheck_head_one_flagged_remeasures_every_head();
 recheck_other_head_flagged_remeasures_only_it();
 remeasure_sends_next_only_after_measured_and_idle();
 recheck_repeats_when_a_head_is_flagged_again();
 cancel_during_remeasure_waits_for_the_running_command_then_restores();
 cancel_during_repeat_heating_drops_next_heat_and_restores();
 cancel_during_repeat_scrub_cools_docks_and_restores();
 stale_status_in_recheck_releases_after_the_limit_without_restore();
 stale_limit_overtakes_cancel_waiting_for_remeasure();
 restart_during_repeat_stops_without_restore();
 recheck_view_texts_for_one_two_and_four_heads();
 recheck_requests_attention_and_releases_it_on_each_choice();
 recheck_decides_only_on_final_flags();
 remeasure_starts_without_first_pass_progress();
 cancelling_text_names_a_mounted_head_and_unchanged_offsets_only();
 restore_send_failure_clears_the_restore_request();
 restart_in_recheck_and_remeasure_stops_without_restore();
 calibrate_shows_each_heads_readings();
 readings_ignore_heads_outside_the_run();
 remeasure_resets_a_heads_row();
 touch_stops_attention_once();
 recheck_shows_each_heads_readings();
 door_opening_stops_attention();
 door_open_before_the_signal_keeps_it_on();
 return_prompt_and_recheck_signal_stops_and_returns();
}

// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "nozzle_scrub_flow.hpp"
#include <cmath>
#include <cstdio>
namespace wmp_ui { namespace native {
// One display-only row of the Calibrate and Re-check screens: "Head N", the mark and the
// centre span ("0.023 mm", empty before the head's first centre).
struct ScrubRow { std::string name, span; ScrubMark mark; };
inline bool operator==(const ScrubRow& a, const ScrubRow& b) { return a.name == b.name && a.span == b.span && a.mark == b.mark; }
inline bool operator!=(const ScrubRow& a, const ScrubRow& b) { return !(a == b); }
// Screen content of the guided nozzle scrub for one flow state.
struct ScrubView {
 ScrubState state; unsigned head, heads;           // head is 0-based
 bool brush, confirm_visible, confirm_enabled, cancel_visible, back_visible;
 std::string heading, body, note;
 double actual, target;                            // shown only in Heating
 // Prepare and Recheck: the two option rows, the first one selected or not.
 std::string option_title[2], option_detail[2];
 bool first_selected;
 std::vector<unsigned> flagged;                    // Recheck: steps shown failed
 std::vector<ScrubRow> rows;                       // Calibrate, Remeasure and Recheck: one per head
};
// Sentence for a stopped run. The raw calibration failure text names commands
// and is never shown; a backend scrub sentence is shown as given.
inline std::string nozzle_scrub_stop_text(const ScrubFacts& f) {
 switch (f.stop) {
  case ScrubStop::Backend: return f.error;
  case ScrubStop::Restarted: return "Printer restarted. Calibration stopped.";
  case ScrubStop::StatusLost: return "Printer status was lost. Calibration stopped.";
  case ScrubStop::NotStarted: return "Calibration did not start.";
  case ScrubStop::Stopped: return "Calibration stopped. Check the printer before trying again.";
  default: return "";
 }
}
// Progress of the stock offset stage that follows the scrub.
inline void nozzle_scrub_calibrate_text(const ScrubFacts& f, ScrubView& v) {
 const bool head = f.progress_head >= 0;
 const auto n = std::to_string(unsigned(f.progress_head + 1)), m = std::to_string(f.heads);
 if (f.progress_phase == "homing") v.heading = "Homing...";
 else if (head && f.progress_phase == "mounting") { v.heading = "Head " + n + " of " + m; v.body = "Mounting head " + n + "..."; }
 else if (head && f.progress_phase == "position") { v.heading = "Head " + n + " of " + m; v.body = "Measuring nozzle position..."; }
 else if (head && f.progress_phase == "height") { v.heading = "Head " + n + " of " + m; v.body = "Measuring nozzle height..."; }
 else if (head && f.progress_phase == "docking") v.heading = "Returning head " + n + " to its dock...";
 else if (f.known_progress_head >= 0) v.heading = "Measuring head " + std::to_string(unsigned(f.known_progress_head + 1)) + " of " + m + "...";
 else v.heading = "Measuring nozzle offsets...";
 v.note = "Keep the door closed.";
}
// Millimetres with three decimals: "0.023 mm".
inline std::string nozzle_scrub_span(double mm) {
 char text[32];
 std::snprintf(text, sizeof text, "%.3f mm", std::isfinite(mm) ? mm : 0.0);
 return text;
}
// One row per head of the run, from the flow's readings.
inline void nozzle_scrub_rows(const ScrubFacts& f, ScrubView& v) {
 for (unsigned i = 0; i < f.heads; ++i) {
  const auto r = i < f.readings.size() ? f.readings[i] : ScrubReading{ScrubMark::None, false, 0};
  v.rows.push_back({"Head " + std::to_string(i + 1), r.span_known ? nozzle_scrub_span(r.span) : "", r.mark});
 }
}
// "Head 2", "Heads 2 and 4", "Heads 1, 2 and 4"; heads are 0-based.
inline std::string nozzle_scrub_head_names(const std::vector<unsigned>& heads) {
 std::string out = heads.size() == 1 ? "Head " : "Heads ";
 for (std::size_t i = 0; i < heads.size(); ++i)
  out += (i == 0 ? "" : i + 1 == heads.size() ? " and " : ", ") + std::to_string(heads[i] + 1);
 return out;
}
inline ScrubView nozzle_scrub_view(const ScrubFacts& f) {
 ScrubView v{f.state, f.head, f.heads, f.brush, false, f.confirm_enabled, false, false, "", "", "", 0, 0,
             {"", ""}, {"", ""}, false, {}, {}};
 const auto n = std::to_string(f.head + 1);
 switch (f.state) {
  case ScrubState::Prepare:
   v.heading = "How will the nozzles be cleaned?";
   v.option_title[0] = "Wire brush";
   v.option_detail[0] = "Scrub each heated nozzle by hand. Have a wire brush ready.";
   v.option_title[1] = "Printed blob";
   v.option_detail[1] = "Every head must be loaded with filament.";
   v.first_selected = f.brush;
   v.confirm_visible = v.cancel_visible = true;
   break;
  case ScrubState::Recheck:
   nozzle_scrub_rows(f, v);
   v.heading = nozzle_scrub_head_names(f.flagged) + " may not be clean";
   v.body = f.flagged.size() == 1 ? "Its measurement did not repeat, which usually means residue on the nozzle."
                                  : "Their measurements did not repeat, which usually means residue on the nozzle.";
   v.option_title[0] = "Clean again";
   v.option_detail[0] = "Scrub the flagged heads, then measure again.";
   v.option_title[1] = "Save anyway";
   v.option_detail[1] = "Keep the offsets as measured.";
   v.first_selected = f.choice == ScrubChoice::Clean;
   v.flagged = f.flagged;
   v.confirm_visible = v.cancel_visible = true;
   break;
  case ScrubState::ReturnPrompt:
   v.heading = "Ready to clean the nozzles.";
   v.body = "Press Confirm to start.";
   v.confirm_visible = v.cancel_visible = true;
   break;
  case ScrubState::Mounting:
   v.heading = "Mounting head " + n + "...";
   v.confirm_visible = v.cancel_visible = true;
   break;
  case ScrubState::Heating:
   v.heading = "Heating head " + n + "...";
   v.actual = f.actual;
   v.target = f.target;
   v.confirm_visible = v.cancel_visible = true;
   break;
  case ScrubState::Scrub:
   v.heading = "Scrub the nozzle on head " + n;
   v.body = "Brush the nozzle tip until it is clean, then press Confirm.";
   v.note = "The nozzle is hot.";
   v.confirm_visible = v.cancel_visible = true;
   break;
  case ScrubState::Cooled:
   v.heading = "Head " + n + " has cooled.";
   v.body = "Press Confirm to reheat.";
   v.confirm_visible = v.cancel_visible = true;
   break;
  case ScrubState::Cancelling:
  case ScrubState::Finished:
   v.heading = "Cancelling...";
   v.body = f.cancel_mounted ? "Cooling and returning head " + n + " to its dock." : "";
   if (f.offsets_unchanged) v.body += std::string(v.body.empty() ? "" : " ") + "Offsets are unchanged.";
   break;
  case ScrubState::Failed:
   v.body = nozzle_scrub_stop_text(f);
   if (f.hot) v.note = "The nozzle may still be hot.";
   v.back_visible = true;
   break;
  case ScrubState::Calibrate:
  case ScrubState::Remeasure:
   nozzle_scrub_calibrate_text(f, v);
   nozzle_scrub_rows(f, v);
   break;
  default:
   break;
 }
 return v;
}
// Index of the current step: Prepare, one per head, Calibrate.
inline unsigned nozzle_scrub_current_step(const ScrubView& v) {
 switch (v.state) {
  case ScrubState::Idle: case ScrubState::Prepare: case ScrubState::StockChecks: return 0;
  case ScrubState::Calibrate: case ScrubState::Recheck: case ScrubState::Remeasure: return v.heads + 1;
  default: return v.head + 1;
 }
}
// Whole degrees; "--" when the temperature is not known.
inline std::string nozzle_scrub_degrees(double value) {
 return std::isfinite(value) ? std::to_string(long(std::lround(value))) : "--";
}
// The view StockProgressPanel::update() draws. The panel numbers the steps.
// The temperature (Heating) is the panel's value, so a change of degrees
// rewrites one label. The Prepare and Recheck choices and the per-head rows
// are drawn by the caller in the panel's choices_parent(), which is sized for
// them: in Calibrate and Remeasure one column of rows; in Recheck two columns
// of rows above the choices. In Recheck the flagged heads' steps are failed.
constexpr int nozzle_scrub_steps_width = 200, nozzle_scrub_title_width = 540, nozzle_scrub_choices_height = 216;
constexpr int nozzle_scrub_row_height = 36;       // one row: a 28 px line and 8 px
// Recheck shows the rows in two columns, the other states in one.
inline unsigned nozzle_scrub_row_columns(const ScrubView& v) { return v.state == ScrubState::Recheck ? 2 : 1; }
// Height of rows rows in columns columns, filled column by column.
inline int nozzle_scrub_rows_height(std::size_t rows, unsigned columns) {
 return nozzle_scrub_row_height * int((rows + columns - 1) / columns);
}
inline Json nozzle_scrub_panel_view(const ScrubView& v) {
 const bool decisions = v.state == ScrubState::Prepare || v.state == ScrubState::Recheck;
 Json view = {{"title", "Nozzle offset calibration"}, {"title_width", nozzle_scrub_title_width},
              {"steps", Json::array()}, {"steps_width", nozzle_scrub_steps_width},
              {"decisions", decisions},
              {"heading", v.heading}, {"instruction", v.body}, {"note", v.note}};
 const int rows = nozzle_scrub_rows_height(v.rows.size(), nozzle_scrub_row_columns(v));
 if (decisions) view["choices_height"] = rows + nozzle_scrub_choices_height;
 else if (!v.rows.empty()) {
  view["decisions"] = true;
  view["choices_height"] = rows;
 }
 if (v.state == ScrubState::Heating)
  view["value"] = nozzle_scrub_degrees(v.actual) + " / " + nozzle_scrub_degrees(v.target) + " \xc2\xb0""C";
 const unsigned current = nozzle_scrub_current_step(v);
 const char* now = v.state == ScrubState::Failed ? "failed" : "running";
 for (unsigned i = 0; i < v.heads + 2; ++i)
  view["steps"].push_back({{"label", i == 0 ? std::string("Prepare") : i == v.heads + 1 ? std::string("Calibrate") : "Head " + std::to_string(i)},
                           {"state", i >= 1 && i <= v.heads && std::find(v.flagged.begin(), v.flagged.end(), i - 1) != v.flagged.end() ? "failed"
                                     : i < current ? "complete" : i > current ? "pending" : now}});
 return view;
}
}}

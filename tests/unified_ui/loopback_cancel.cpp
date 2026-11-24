// SPDX-License-Identifier: GPL-3.0-or-later
#include "native/loopback_http.hpp"
#include <cassert>
int main(int argc,char**argv){
 assert(wmp_openace::UnifiedLoopbackHttp::allowed_query("/printer/wmp/filament/details"));
 for(const auto*path:{"/printer/wmp/filament/details?head=h0","/printer/wmp/filament/details/extra"})assert(!wmp_openace::UnifiedLoopbackHttp::allowed_query(path));
 assert(argc==2);wmp_openace::UnifiedLoopbackHttp http(std::stoi(argv[1]));
 // Scheduling delay above the former one-second deadline is still a valid reply.
 assert(wmp_openace::json::parse(http.get("/printer/objects/query?webhooks"))["result"]=="ok");
 // A genuinely stalled GET must still fail; it cannot become an unbounded wait.
 bool timed_out=false;try{http.get("/printer/objects/list");}catch(const wmp_openace::HttpFailure&e){timed_out=e.kind==wmp_openace::HttpFailureKind::Deadline;}assert(timed_out);
 auto body=wmp_openace::json{{"id","running-1"},{"session","session-1"},{"head","h2"}}.dump();
 for(const auto*route:{"/printer/wmp/recovery/review","/printer/wmp/recovery/resolve_review","/printer/wmp/recovery/retire_review","/printer/wmp/recovery/retire_result","/printer/wmp/recovery/stop","/printer/wmp/print/cancel_review","/printer/wmp/print/cancel","/printer/wmp/print/cancel_resolve_review"})
  assert(wmp_openace::json::parse(http.post(route,body))["result"]["state"]=="requested");
 auto accepted=wmp_openace::json::parse(http.post("/printer/wmp/filament/cancel",body));
 assert(accepted["result"]["state"]=="requested");
 auto tool_body=wmp_openace::json{{"id","running-1"},{"session","session-1"},{"head","h2"},{"action","take"}}.dump();
 assert(wmp_openace::json::parse(http.post("/printer/wmp/toolhead/cancel",tool_body))["result"]["state"]=="requested");
 auto rejected=wmp_openace::json::parse(http.post("/printer/wmp/filament/cancel","{}"));
 assert(rejected.contains("error"));
 auto probe=wmp_openace::json{{"session","session-1"},{"request","probe-1"}}.dump();
 auto stopped=wmp_openace::json::parse(http.post("/printer/wmp/probe_editor/stop",probe));
 assert(stopped["result"]["state"]=="requested");
 assert(stopped["result"]["request"]=="probe-1");
 assert(wmp_openace::json::parse(http.post("/printer/wmp/probe_editor/stop","{}" )).contains("error"));
 for(const auto*route:{"/printer/wmp/probe_editor/stop/extra","/printer/wmp/probe_editor/stop?session=x"}){
  bool refused=false;try{http.post(route,probe);}catch(...){refused=true;}assert(refused);
 }
 {bool refused=false;try{http.post("/printer/wmp/probe_editor/stop",std::string(2049,'x'));}catch(...){refused=true;}assert(refused);}
 assert(wmp_openace::json::parse(http.post("/printer/gcode/script","{\"script\":\"M105\"}"))["result"]=="ok");
 assert(wmp_openace::json::parse(http.post("/printer/wmp/identification/cancel",wmp_openace::json{{"session","session-1"},{"request","identity-1"}}.dump()))["result"]["state"]=="requested");
 auto macro_error=wmp_openace::json::parse(http.post("/printer/gcode/script","{\"script\":\"ERROR\"}"));
 assert(macro_error["error"]["message"]=="Heat the selected nozzle\n");
 const std::string recovery="WMP_RECOVERY_CONTINUE REQUEST="+std::string(2200,'a');
 assert(wmp_openace::json::parse(http.post("/printer/gcode/script",wmp_openace::json{{"script",recovery}}.dump()))["result"]=="ok");
 assert(wmp_openace::json::parse(http.post("/printer/gcode/script",wmp_openace::json{{"script","WMP_RETIRE_RECOVERY REQUEST="+std::string(2200,'a')}}.dump()))["result"]=="ok");
 for(const auto*path:{"/printer/wmp/recovery/retire_review/extra","/printer/wmp/recovery/retire_result?session=x"}){
  bool refused=false;try{http.post(path,body);}catch(...){refused=true;}assert(refused);
 }
 for(const auto&script:{std::string(2200,'x'),std::string("WMP_RECOVERY_CONTINUE REQUEST=")+std::string(2201,'a'),std::string("WMP_RECOVERY_CONTINUE REQUEST=")+std::string(2200,'z')}){
  bool refused=false;try{http.post("/printer/gcode/script",wmp_openace::json{{"script",script}}.dump());}catch(...){refused=true;}assert(refused);
 }

 bool bad_response=false;
 try{http.get("/server/files/roots");}catch(const wmp_openace::HttpFailure&e){bad_response=e.kind==wmp_openace::HttpFailureKind::Response;}
 assert(bad_response);
 for(const auto*script:{"WRONG_ID","BOTH","BAD_ERROR","DROP"}){
  bool refused=false;try{http.post("/printer/gcode/script",wmp_openace::json{{"script",script}}.dump());}catch(...){refused=true;}assert(refused);
 }
 for(const auto*body:{"{}","[]","{\"script\":1}","{\"script\":\"M105\",\"extra\":1}"}){
  bool refused=false;try{http.post("/printer/gcode/script",body);}catch(...){refused=true;}assert(refused);
 }
 for(const auto*path:{"/printer/wmp/identification/cancel/extra","/printer/wmp/identification/cancel?request=x","/printer/wmp/print/cancel_resolve_review/extra","/printer/wmp/print/cancel_resolve_review?file=x","/printer/wmp/print/cancel/extra","/printer/wmp/print/cancel_review?file=x","/printer/wmp/recovery/resolve_review/extra","/printer/wmp/recovery/resolve_review?session=x","/printer/wmp/recovery/review/extra","/printer/wmp/recovery/stop?session=x","/printer/wmp/filament/cancel/extra","/printer/emergency_stop","/printer/wmp/toolhead/cancel/extra","/printer/wmp/toolhead/cancel?action=take","/printer/wmp/filament/cancel?head=h0"}){
  bool refused=false;try{http.post(path,body);}catch(...){refused=true;}assert(refused);
 }
 for(const auto*route:{"/printer/wmp/print/cancel_review","/printer/wmp/print/cancel","/printer/wmp/print/cancel_resolve_review"}){
  bool refused=false;try{http.post(route,std::string(32769,'x'));}catch(...){refused=true;}assert(refused);
 }
 bool identity_refused=false;try{http.post("/printer/wmp/identification/cancel",std::string(2049,'x'));}catch(...){identity_refused=true;}assert(identity_refused);
 bool tool_refused=false;try{http.post("/printer/wmp/toolhead/cancel",std::string(2049,'x'));}catch(...){tool_refused=true;}assert(tool_refused);
 bool refused=false;try{http.post("/printer/wmp/filament/cancel",std::string(2049,'x'));}catch(...){refused=true;}assert(refused);
}

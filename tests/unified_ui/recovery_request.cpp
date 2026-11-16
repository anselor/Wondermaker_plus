#include "recovery_request.hpp"
#include <cassert>
using namespace wmp_ui;
int main(){
 auto selection=native_recovery_selection("attempt-1","session","/gcodes/nested/part.gcode","plr_dataB.ini",std::string(16,'a'),std::string(16,'b'));
 auto request=selection;request["file"]="nested/part.gcode";request["version"]=1;request["owner"]="standalone";
 request["execution_hash"]=std::string(16,'c');request["deposition_sha256"]=std::string(64,'d');
 Json review={{"selected_file",selection.at("file")},{"request",request},{"execution",{{"file",{{"path","nested/part.gcode"}}},{"job_fingerprint",std::string(16,'b')}}}};
 const auto command=recovery_continue_script(selection,review);const std::string prefix="WMP_RECOVERY_CONTINUE REQUEST=";
 assert(command.find(prefix)==0);std::string decoded;
 for(std::size_t i=prefix.size();i<command.size();i+=2)decoded+=char(std::stoul(command.substr(i,2),nullptr,16));
 assert(Json::parse(decoded)==request);
 for(const auto*key:{"id","session","checkpoint","checkpoint_hash","job_hash","owner","execution_hash","deposition_sha256","file"}){
  auto changed=review;changed["request"][key]="changed";bool failed=false;
  try{recovery_continue_script(selection,changed);}catch(...){failed=true;}assert(failed);
 }
 for(const auto&file:{std::string(),std::string("bad\nfile"),std::string(4096,'x')}){
  bool failed=false;try{native_recovery_selection("id","session",file,"plr_dataA.ini",std::string(16,'a'),std::string(16,'b'));}catch(...){failed=true;}assert(failed);
 }
 auto changed=review;changed["selected_file"]="different.gcode";bool failed=false;
 try{recovery_continue_script(selection,changed);}catch(...){failed=true;}assert(failed);

 auto modern=review;modern["request"]["id"]="wmp2rc_1";
 modern["ticket"]={{"protocol",1},{"selection_id",selection.at("id")},{"sequence","1"},{"token",std::string(64,'e')}};
 assert(recovery_continue_script(selection,modern).find(" TICKET="+std::string(64,'e'))!=std::string::npos);
 for(const auto*field:{"token","sequence","selection_id"}){auto invalid=modern;invalid["ticket"][field]="bad";bool denied=false;try{recovery_continue_script(selection,invalid);}catch(...){denied=true;}assert(denied);}
 modern.erase("ticket");failed=false;try{recovery_continue_script(selection,modern);}catch(...){failed=true;}assert(failed);
}

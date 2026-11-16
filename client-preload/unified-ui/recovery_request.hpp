// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "model.hpp"
namespace wmp_ui {
inline bool recovery_hex(const Json&value,std::size_t length){
 if(!value.is_string())return false;
 const auto s=value.get<std::string>();return s.size()==length&&s.find_first_not_of("0123456789abcdef")==std::string::npos;
}
inline Json native_recovery_selection(const std::string&id,const std::string&session,
 const std::string&file,const std::string&checkpoint,const std::string&checkpoint_hash,const std::string&job_hash){
 if(id.empty()||id.size()>64||id.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")!=std::string::npos
    ||session.empty()||session.size()>128||file.empty()||file.size()>=4096
    ||file.find('\0')!=std::string::npos||file.find('\n')!=std::string::npos||file.find('\r')!=std::string::npos
    ||(checkpoint!="plr_dataA.ini"&&checkpoint!="plr_dataB.ini")
    ||!recovery_hex(checkpoint_hash,16)||!recovery_hex(job_hash,16))throw std::runtime_error("Invalid native recovery selection");
 return {{"id",id},{"session",session},{"file",file},{"checkpoint",checkpoint},{"checkpoint_hash",checkpoint_hash},{"job_hash",job_hash}};
}
// Server operation identity is distinct from the UI selection identity.
inline std::string recovery_ticket_suffix(const Json&request,const Json&ticket,const std::string&selected,const char*kind){
 const auto id=request.value("id","");
 if(ticket.is_null()||ticket.empty()){
  if(id.find("wmp2rc_")==0||id.find("wmp2rr_")==0)throw std::runtime_error("Recovery ticket is missing for a ticket-bound operation");
  if(id!=selected)throw std::runtime_error("Recovery review changed identity");
  return "";
 }
 const auto sequence=ticket.value("sequence","");
 if(ticket.size()!=4||ticket.value("protocol",0)!=1||ticket.value("selection_id","")!=selected||
    sequence.empty()||sequence.size()>256||sequence[0]=='0'||sequence.find_first_not_of("0123456789")!=std::string::npos||
    id!=std::string(kind)+sequence||!recovery_hex(ticket.value("token",Json()),64))
  throw std::runtime_error("Recovery review ticket has invalid identity or sequence");
 return " TICKET="+ticket.at("token").get<std::string>();
}
// The review is not a lease. The command repeats backend admission, and callers
// send it once: lost delivery is reconciled through the durable attempt receipt.
inline std::string recovery_continue_script(const Json&selection,const Json&review){
 const auto&request=review.at("request");
 if(!request.is_object()||request.size()!=10||!request.at("version").is_number_integer()
    ||request.at("version")!=1||request.at("owner")!="standalone"
    ||review.at("selected_file")!=selection.at("file"))throw std::runtime_error("Recovery review changed selection");
 const auto suffix=recovery_ticket_suffix(request,review.value("ticket",Json()),selection.at("id"),"wmp2rc_");
 for(const auto*key:{"session","checkpoint","checkpoint_hash","job_hash"})
  if(request.at(key)!=selection.at(key))throw std::runtime_error("Recovery review changed binding");
 const auto&execution=review.at("execution");
 if(!request.at("file").is_string()||request.at("file").get<std::string>().empty()
    ||request.at("file")!=execution.at("file").at("path")
    ||request.at("job_hash")!=execution.at("job_fingerprint")
    ||!recovery_hex(request.at("execution_hash"),16)||!recovery_hex(request.at("deposition_sha256"),64))
  throw std::runtime_error("Recovery review has incomplete execution evidence");
 const auto payload=request.dump();
 if(payload.size()>8192)throw std::runtime_error("Recovery request too large");
 std::string hex;const char*digits="0123456789abcdef";
 for(unsigned char c:payload){hex+=digits[c>>4];hex+=digits[c&15];}
 return "WMP_RECOVERY_CONTINUE REQUEST="+hex+suffix;
}
inline std::string recovery_retirement_script(const Json&identity,const Json&request){
 if(!request.is_object()||request.size()!=4||!request.at("version").is_number_integer()
    ||request.at("version")!=1||!request.at("evidence").is_object())
  throw std::runtime_error("Invalid recovery discard review");
 for(const auto*key:{"id","session"}){
  if(request.at(key)!=identity.at(key))throw std::runtime_error("Discard review changed identity");
  const auto value=request.at(key).get<std::string>();
  if(value.empty()||value.size()>64||value.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")!=std::string::npos)
   throw std::runtime_error("Invalid discard identity");
 }
 const auto&e=request.at("evidence");
 if(e.size()!=3||!e.contains("receipt")||!e.at("receipt").is_object()
    ||!e.contains("manifest")||!e.at("manifest").is_object()||!recovery_hex(e.at("fingerprint"),64))
  throw std::runtime_error("Invalid discard evidence");
 const auto payload=request.dump();if(payload.size()>8192)throw std::runtime_error("Discard review too large");
 std::string hex;const char*digits="0123456789abcdef";
 for(unsigned char c:payload){hex+=digits[c>>4];hex+=digits[c&15];}
 return "WMP_RETIRE_RECOVERY REQUEST="+hex;
}
inline std::string recovery_resolution_script(const Json&identity,const Json&request,const Json&ticket=Json()){
 if(!request.is_object()||request.size()!=7||!request.at("version").is_number_integer()||request.at("version")!=1)
  throw std::runtime_error("Invalid recovery resolution review");
 const auto suffix=recovery_ticket_suffix(request,ticket,identity.at("id"),"wmp2rr_");
 for(const auto*key:{"attempt_id","session","action"})
  if(request.at(key)!=identity.at(key))throw std::runtime_error("Resolution review changed identity");
 for(const auto*key:{"id","attempt_id","session"}){
  const auto value=request.at(key).get<std::string>();
  if(value.empty()||value.size()>64||value.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")!=std::string::npos)
   throw std::runtime_error("Invalid resolution identity");
 }
 if((request.at("action")!="reconcile"&&request.at("action")!="abandon")
    ||!recovery_hex(request.at("journal_sha256"),64)||!recovery_hex(request.at("execution_hash"),16))
  throw std::runtime_error("Invalid resolution evidence");
 std::string hex;const char*digits="0123456789abcdef";
 for(unsigned char c:request.dump()){hex+=digits[c>>4];hex+=digits[c&15];}
 return "WMP_RECOVERY_RESOLVE REQUEST="+hex+suffix;
}

}

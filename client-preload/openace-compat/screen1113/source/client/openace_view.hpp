#pragma once
#include <algorithm>
#include <cstdint>
#include <functional>
#include <string>
#include <utility>
#include <nlohmann/json.hpp>

namespace wmp_openace {
using json = nlohmann::json;
struct View {
    bool visible=false, connected=false, data_current=false, pending_confirmation=false;
    bool approved=false, confirm_enabled=false;
    int tool=-1;
    std::int64_t session=-1;
    std::uint64_t serial=0;
    std::string title, message, from_label, to_label, expected_label, replacement_label, source, change_id, context, error;
};

// Presentation only. It owns no print, motion, approval or recovery state.
class ScreenModel {
public:
    typedef std::function<bool(const std::string&)> Enqueue;
    const View& view() const { return current_; }
    static bool acceptable_payload(const std::string&value){return bounded(value);}
    bool update(const std::string& payload, bool object_present, std::int64_t now_ms) {
        if (!object_present) { assign(View()); waiting_.clear(); return true; }
        try {
            if (now_ms<0 || !bounded(payload)) return unavailable("Status unavailable or too large");
            json value=json::parse(payload);
            if (!value.is_object() || !integer(value,"session_id")) return unavailable("Invalid printer status");
            View next; next.connected=next.data_current=true;next.session=value["session_id"].get<std::int64_t>();
            // Moonraker emits null for an absent field explicitly named by a selective query.
            if (!value.contains("material_change_prompt") || value["material_change_prompt"].is_null()) {
                // An explicit current status with no prompt completes only the UI presentation.
                assign(next);waiting_.clear();last_update_=now_ms;return true;
            }
            const json& prompt=value["material_change_prompt"];
            if (!prompt.is_object() || !integer(prompt,"tool") || !text(prompt,"head",64)
                    || !text(prompt,"source",128) || !text(prompt,"message",2048)
                    || !prompt.contains("record_saved") || !prompt["record_saved"].is_boolean()
                    || !prompt.contains("declared_target") || !prompt.contains("actual_from")
                    || !prompt.contains("target_declared") || !prompt["target_declared"].is_boolean())
                return unavailable("Invalid material change status");
            const auto tool=prompt["tool"].get<std::int64_t>();
            if (tool<0 || tool>31) return unavailable("Unsupported print tool");
            next.visible=true;next.tool=static_cast<int>(tool);
            next.title="Filament change T"+std::to_string(next.tool)+" ("+prompt["head"].get<std::string>()+")";
            next.message=prompt["message"].get<std::string>();
            next.source=prompt["source"].get<std::string>();
            next.from_label=label(prompt["actual_from"],"unknown");
            next.to_label=label(prompt["declared_target"],"not declared by slicer");
            if (prompt["target_declared"].get<bool>()!=!prompt["declared_target"].is_null())
                return unavailable("Inconsistent declared target");
            if (text(prompt,"change_id",128)) next.change_id=prompt["change_id"].get<std::string>();
            const std::string head=prompt["head"].get<std::string>();
            if (value.contains("loaded") && value["loaded"].is_object() && value["loaded"].contains(head)) {
                const auto& load=value["loaded"][head];
                if(load.is_object() && load.contains("identity") && !load["identity"].is_null())
                    next.replacement_label=label(load["identity"],"unknown");
            }
            if (prompt.contains("confirmation") && prompt["confirmation"].is_object()
                    && integer(prompt["confirmation"],"version") && prompt["confirmation"]["version"]==1) {
                const json& change=prompt["confirmation"];
                if (!change.is_object() || !integer(change,"tool") || change["tool"]!=prompt["tool"]
                        || !text(change,"source",128) || change["source"]!=prompt["source"]
                        || !text(change,"change_id",128) || change["change_id"]!=prompt["change_id"]
                        || !boolean(change,"pending_confirmation") || !boolean(change,"approved"))
                    return unavailable("Inconsistent material approval status");
                if (!text(change,"expected_material",256) || !text(change,"expected_color",64)
                        || !text(change,"actual_material",256) || !text(change,"actual_color",64))
                    return unavailable("Invalid expected or loaded filament label");
                next.expected_label=change["expected_material"].get<std::string>()+" "+change["expected_color"].get<std::string>();
                next.replacement_label=change["actual_material"].get<std::string>()+" "+change["actual_color"].get<std::string>();
                if (value.contains("loaded") && value["loaded"].is_object() && value["loaded"].contains(head)) {
                    const json& load=value["loaded"][head];
                    if (load.is_object() && load.contains("identity") && load["identity"].is_object()) {
                        const json& identity=load["identity"];
                        if (identity.contains("material") && identity["material"]==change["actual_material"]
                                && identity.contains("color") && identity["color"]==change["actual_color"])
                            next.replacement_label=label(identity,"unknown");
                    }
                }
                next.pending_confirmation=change["pending_confirmation"].get<bool>();
                next.approved=change["approved"].get<bool>();
                if (text(change,"context",64) && digest(change["context"].get<std::string>()))
                    next.context=change["context"].get<std::string>();
                if (next.pending_confirmation && next.context.empty())
                    next.error="This backend cannot bind a screen confirmation; update openACE";
                next.confirm_enabled=next.pending_confirmation && !next.approved && !next.context.empty()
                    && prompt["record_saved"].get<bool>() && !next.change_id.empty();
            } else next.error="This backend has no compact bound confirmation; update openACE";
            if (!prompt["record_saved"].get<bool>()) next.error="Change record not saved; fix storage before continuing";
            if (!waiting_.empty() && waiting_!=next.context) waiting_.clear();
            if (next.approved || !next.pending_confirmation) waiting_.clear();
            if (!waiting_.empty()) next.confirm_enabled=false;
            assign(next);last_update_=now_ms;return true;
        } catch (...) { return unavailable("Invalid printer status"); }
    }
    void disconnected() { unavailable("Printer disconnected; displayed change is not current"); }
    bool click_confirm(std::uint64_t displayed_serial, std::int64_t now_ms, const Enqueue& enqueue) {
        if (displayed_serial!=current_.serial || !current_.confirm_enabled || !current_.connected
                || !current_.data_current || now_ms<last_update_ || now_ms-last_update_>2000) return false;
        // Only validated numeric tool and backend hex context enter a command. Labels never do.
        const std::string command="OPENACE_CONFIRM_CHANGE TOOL="+std::to_string(current_.tool)
            +" CONFIRM=1 EXPECT_CONTEXT="+current_.context;
        try { if (!enqueue(command)) return false; } catch (...) { return false; }
        waiting_=current_.context;current_.confirm_enabled=false;return true;
    }
    // Failure acknowledges delivery only, never approval. A new status is required before retry.
    void command_failed() { waiting_.clear();unavailable("Confirmation failed; refresh the current change"); }
private:
    View current_;std::string waiting_;std::int64_t last_update_=-1;
    static bool integer(const json& o,const char* key) {
        return o.contains(key) && o[key].is_number_integer() && !o[key].is_boolean();
    }
    static bool boolean(const json& o,const char* key) {return o.contains(key) && o[key].is_boolean();}
    static bool text(const json& o,const char* key,std::size_t maximum) {
        return o.contains(key) && o[key].is_string() && o[key].get_ref<const std::string&>().size()<=maximum
            && std::none_of(o[key].get_ref<const std::string&>().begin(),o[key].get_ref<const std::string&>().end(),
                [](unsigned char c){return c<32 || c==127;});
    }
    static bool digest(const std::string& value) {
        return value.size()==64 && std::all_of(value.begin(),value.end(),[](char c){return (c>='0'&&c<='9')||(c>='a'&&c<='f');});
    }
    static bool bounded(const std::string& value) {
        if (value.empty() || value.size()>256*1024) return false;
        int depth=0;bool quoted=false,escape=false;
        for (char c:value) {
            if (quoted) {if(escape)escape=false;else if(c=='\\')escape=true;else if(c=='"')quoted=false;}
            else if(c=='"')quoted=true;
            else if(c=='{'||c=='[') {if(++depth>32)return false;}
            else if(c=='}'||c==']') {if(--depth<0)return false;}
        }
        return depth==0 && !quoted;
    }
    static std::string label(const json& o,const std::string& missing) {
        if(o.is_null())return missing;
        if(!o.is_object() || !text(o,"material",256) || !text(o,"color",64) || !text(o,"name",256))
            throw std::runtime_error("invalid filament label");
        const std::string name=o["name"].get<std::string>(),material=o["material"].get<std::string>();
        return (name.empty()?material:name)+" ["+material+" "+o["color"].get<std::string>()+"]";
    }
    void assign(View next) {
        // Snapshot equality excludes no backend authority. It is only a stale UI-event fence.
        const bool same=current_.visible==next.visible && current_.connected==next.connected
            && current_.data_current==next.data_current && current_.tool==next.tool && current_.session==next.session
            && current_.title==next.title && current_.source==next.source
            && current_.from_label==next.from_label && current_.to_label==next.to_label && current_.error==next.error
            && current_.message==next.message && current_.context==next.context
            && current_.expected_label==next.expected_label && current_.replacement_label==next.replacement_label
            && current_.change_id==next.change_id && current_.pending_confirmation==next.pending_confirmation
            && current_.approved==next.approved && current_.confirm_enabled==next.confirm_enabled;
        next.serial=current_.serial+(same?0:1);current_=std::move(next);
    }
    bool unavailable(const std::string& reason) {
        View next=current_;next.connected=false;next.data_current=false;next.confirm_enabled=false;next.error=reason;
        assign(next);waiting_.clear();return false;
    }
};
}

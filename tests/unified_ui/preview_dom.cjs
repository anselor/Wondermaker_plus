// Exercise the actual preview script with a small DOM lifetime/focus model.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
let allocations = 0, moves = 0;
const document = {activeElement: null};
class Element {
 constructor(tag) { allocations++; this.tagName=tag.toUpperCase(); this.children=[]; this.dataset={}; this.style={}; this.listeners={}; this.parent=null; }
 get isConnected() { return this===stage || !!this.parent?.isConnected; }
 addEventListener(event, fn) { (this.listeners[event] ||= []).push(fn); }
 emit(event) { for(const fn of this.listeners[event]||[]) fn({target:this}); }
 setAttribute(key,value) { this[key]=value; }
 focus() { document.activeElement=this; this.emit('focus'); }
 remove() { if(this.parent) { this.parent.children.splice(this.parent.children.indexOf(this),1); this.parent=null; } if(document.activeElement===this) document.activeElement=null; }
 replaceChildren() { for(const child of [...this.children]) child.remove(); }
 insertBefore(child,before) { moves++; child.remove(); const index=before?this.children.indexOf(before):this.children.length; assert.ok(index>=0); this.children.splice(index,0,child); child.parent=this; }
}
const stage=new Element('div'), reason=new Element('p'), scenario=new Element('select');
document.querySelector = selector => ({'#stage':stage,'#reason':reason,'#scenario':scenario})[selector];
document.createElement = tag => new Element(tag);
// Initial HTTP request stays pending: frames below are explicitly controlled.
const context=vm.createContext({document, fetch:()=>new Promise(()=>{})});
const html=fs.readFileSync(process.argv[2],'utf8');
vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1],context);
const events=[]; context.send=data=>events.push(data.event);
const widget=(id,extra={})=>({id,kind:'button',text:id,enabled:true,x:0,y:0,w:100,h:40,...extra});
const draw=(widgets,extra={})=>context.draw({page:'tools',modal:'',widgets,...extra});
const get=id=>stage.children.find(e=>e.dataset.id===id);
draw([widget('a'),widget('b',{color:'#ff0000'})]);
const a=get('a'),b=get('b'); a.focus();
const allocated=allocations, moved=moves;
for(let i=0;i<10;i++) draw([widget('a',{text:`Temp ${i}`,reason:`Reason ${i}`}),widget('b')]);
assert.equal(allocations,allocated); assert.equal(moves,moved);
assert.equal(get('a'),a); assert.equal(document.activeElement,a);
assert.equal(b.style.background,''); a.emit('pointerenter'); assert.equal(reason.textContent,'Reason 9');
a.emit('click'); assert.deepEqual(events,['a']); assert.equal(a.listeners.click.length,1);
draw([widget('b'),widget('a')]);
assert.equal(get('a'),a); assert.equal(get('b'),b); assert.equal(document.activeElement,a);
b.emit('click'); assert.deepEqual(events,['a','b']);
draw([widget('b',{enabled:false}),widget('a')]); b.emit('click'); assert.equal(events.length,2);
draw([widget('c'),widget('a')]); assert.equal(get('a'),a); assert.equal(b.isConnected,false); b.emit('click'); assert.equal(events.length,2);
const c=get('c'); draw([widget('c'),widget('c')]); assert.equal(get('c'),c); assert.equal(get('a'),a); assert.equal(reason.textContent,'Invalid widget identity');
draw([widget('a',{kind:'label'})]); assert.notEqual(get('a'),a); a.emit('click'); assert.equal(events.length,2);
const label=get('a'); draw([widget('a',{kind:'label'})],{page:'filaments'}); assert.notEqual(get('a'),label);
console.log('Preview DOM lifecycle checks passed');

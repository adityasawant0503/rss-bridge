/* PulsEdge membership: free trials, signed access links, the terminal's sign-up gate and feedback.
 *
 * Access comes from one of two places:
 *  - A self-serve free trial: the visitor enters an email and gets TRIAL_SESSIONS trading sessions in this browser.
 *  - An access link (terminal.html#pass=...), issued from PulsEdge HQ and signed with its private key.
 *    It carries the plan: trial7 / trial14 (5 or 10 trading sessions from a start date), or a paid / founding /
 *    guest plan valid until a date. Links listed in data/revoked.json stop working.
 * Trials count NSE trading sessions, not calendar days. A trial runs until the next trading day after its last session.
 *
 * This is a front-end gate for the beta: the data files are public, so it guards the experience, not the data.
 * Real protection comes with logins (Supabase) and private data.
 */
(function(){
  "use strict";
  // Public halves of the keys allowed to sign access links. PulsEdge HQ makes its own key on each device and
  // keeps the private half there; its public half is added to data/keys.json. This one signs links from
  // pulsedge-bot/issue_pass.js.
  var KEYS=[{kid:"ops1",x:"8RUNuqzLjyLlTZrvGe4-S-klQ-lTGQd800eIdX_-l-g",y:"yhQDBaVv6lBvZiydzekTSDTOZbTmJoc-sAdEOjefXo8"}];
  var FORMSPREE="https://formspree.io/f/mkjoaaga";
  var TRIAL_SESSIONS=5;
  var CLOSE_MIN=15*60+30;
  var PLANS={trial7:"Free trial",trial14:"Extended trial",monthly:"Pro",yearly:"Pro yearly",founding:"Founding member",comp:"Guest access"};
  // Fallback when data/calendar.json can't be read; keep in step with it.
  var HOLIDAYS=["2026-01-15","2026-01-26","2026-03-03","2026-03-26","2026-03-31","2026-04-03","2026-04-14","2026-05-01",
    "2026-05-28","2026-06-26","2026-09-14","2026-10-02","2026-11-10","2026-11-24","2026-12-25"];

  function store(k,v){try{if(v===undefined)return localStorage.getItem(k);if(v===null)localStorage.removeItem(k);else localStorage.setItem(k,v)}catch(e){return null}}
  function getJson(u){return fetch(u,{cache:"no-store"}).then(function(r){if(!r.ok)throw new Error(u);return r.json()})}

  // ---------- trading calendar (all dates are IST, "YYYY-MM-DD") ----------
  var hol={};HOLIDAYS.forEach(function(d){hol[d]=1});
  function istNow(){var d=new Date(Date.now()+(330+new Date().getTimezoneOffset())*60000);return {date:ymd(d),min:d.getHours()*60+d.getMinutes()}}
  function ymd(d){return d.getFullYear()+"-"+("0"+(d.getMonth()+1)).slice(-2)+"-"+("0"+d.getDate()).slice(-2)}
  function parse(s){var p=s.split("-");return new Date(+p[0],+p[1]-1,+p[2])}
  function addDays(s,n){var d=parse(s);d.setDate(d.getDate()+n);return ymd(d)}
  function isSession(s){var w=parse(s).getDay();return w>0&&w<6&&!hol[s]}
  function nextSession(s){while(!isSession(s))s=addDays(s,1);return s}
  function nthSession(first,n){var d=first,k=1;while(k<n){d=addDays(d,1);if(isSession(d))k++}return d}
  function sessionsBetween(a,b){var k=0;for(var d=a;d<=b;d=addDays(d,1))if(isSession(d))k++;return k}
  function nice(s){return parse(s).toLocaleDateString("en-IN",{weekday:"short",day:"numeric",month:"short"})}

  // A trial's sessions from its first session to today. Ends when the trading day after its last session begins.
  function trialState(first,total){
    var now=istNow(),used=first<=now.date?sessionsBetween(first,now.date):0,last=nthSession(first,total);
    return {total:total,used:Math.min(used,total),left:Math.max(total-used,0),first:first,last:last,
      next:nextSession(addDays(last,1)),ended:used>total,lastDay:now.date===last};
  }

  // ---------- signed access links ----------
  function b64u(s){s=s.replace(/-/g,"+").replace(/_/g,"/");while(s.length%4)s+="=";var b=atob(s),u=new Uint8Array(b.length);for(var i=0;i<b.length;i++)u[i]=b.charCodeAt(i);return u}
  var keysP=getJson("data/keys.json").then(function(j){return KEYS.concat(j.keys||[])}).catch(function(){return KEYS})
    .then(function(list){return Promise.all(list.map(function(k){
      return crypto.subtle.importKey("jwk",{kty:"EC",crv:"P-256",x:k.x,y:k.y},{name:"ECDSA",namedCurve:"P-256"},false,["verify"])
        .then(function(key){return {kid:k.kid,key:key}},function(){return null});
    }))}).then(function(l){return l.filter(Boolean)}).catch(function(){return []});
  // Resolves to the link's payload when a known key signed it, else null. The payload names its key (k).
  function verify(token){
    var parts=String(token||"").split(".");
    if(parts.length!==2||!window.crypto||!crypto.subtle)return Promise.resolve(null);
    var p;try{p=JSON.parse(new TextDecoder().decode(b64u(parts[0])))}catch(e){return Promise.resolve(null)}
    if(!p||!PLANS[p.p])return Promise.resolve(null);
    return keysP.then(function(keys){
      var cands=keys.filter(function(k){return !p.k||k.kid===p.k});
      return Promise.all(cands.map(function(k){return crypto.subtle.verify({name:"ECDSA",hash:"SHA-256"},k.key,b64u(parts[1]),new TextEncoder().encode(parts[0])).catch(function(){return false})}));
    }).then(function(oks){return oks.indexOf(true)>=0?p:null}).catch(function(){return null});
  }

  // ---------- current access ----------
  // {granted, kind:"pass"|"trial"|"none", state:"active"|"ended"|"invalid"|"none", plan, label, email, trial:{...}, until}
  function fromPass(p){
    var a={kind:"pass",plan:p.p,label:PLANS[p.p],email:p.e||"",id:p.i};
    if(p.p==="trial7"||p.p==="trial14"){
      a.trial=trialState(nextSession(p.s||istNow().date),p.n||(p.p==="trial14"?10:5));a.state=a.trial.ended?"ended":"active";
    }else{a.until=p.x;a.state=!p.x||istNow().date<=p.x?"active":"ended"}
    a.granted=a.state==="active";return a;
  }
  function fromTrial(t){
    var started=new Date(t.at),d=new Date(started.getTime()+(330+started.getTimezoneOffset())*60000),day=ymd(d);
    // Started after the close or on a holiday: the first session is the next trading day.
    var first=isSession(day)&&d.getHours()*60+d.getMinutes()<CLOSE_MIN?day:nextSession(addDays(day,1));
    var a={kind:"trial",plan:"trial7",label:PLANS.trial7,email:t.email,trial:trialState(first,t.n||TRIAL_SESSIONS)};
    a.state=a.trial.ended?"ended":"active";a.granted=a.state==="active";return a;
  }
  function current(revoked){
    var tok=store("pe_pass"),t=null;try{t=JSON.parse(store("pe_trial")||"null")}catch(e){}
    return verify(tok).then(function(p){
      var pass=p&&revoked.indexOf(p.i)<0?fromPass(p):null,trial=t&&t.at?fromTrial(t):null;
      if(pass&&pass.granted)return pass;
      if(trial&&trial.granted)return trial;
      return pass||trial||{kind:"none",state:"none",granted:false};
    });
  }

  var revokedP=getJson("data/revoked.json").then(function(j){return j.ids||[]}).catch(function(){return []});
  var calP=getJson("data/calendar.json").then(function(j){(j.holidays||[]).forEach(function(d){hol[d]=1})}).catch(function(){});

  // A link opened as terminal.html#pass=... is checked, kept in this browser and removed from the address bar.
  var linkMsg="";
  var passP=(function(){
    var m=location.hash.match(/[#&]pass=([A-Za-z0-9_\-.]+)/);
    if(!m)return Promise.resolve();
    history.replaceState(null,"",location.pathname+location.search);
    return verify(m[1]).then(function(p){if(p){store("pe_pass",m[1]);linkMsg=""}else linkMsg="That access link isn't valid. Ask PulsEdge for a new one."});
  })();

  var ready=Promise.all([calP,passP,revokedP]).then(function(r){return current(r[2])});

  // ---------- UI ----------
  var css=""+
  ".pe-gate{position:fixed;inset:0;z-index:50;display:grid;place-items:center;padding:max(16px,env(safe-area-inset-top,0px)) 16px max(16px,env(safe-area-inset-bottom,0px));background:color-mix(in srgb,var(--bg) 55%,transparent);backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px);opacity:0;transition:opacity 200ms ease-out}"+
  ".pe-gate.in{opacity:1}.pe-gate.out{opacity:0;transition:opacity 150ms ease-in}"+
  ".pe-card{width:min(440px,100%);max-height:calc(100dvh - 32px);overflow:auto;background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:24px;box-shadow:var(--elev),0 30px 80px -30px rgba(0,0,0,.55);transform:scale(.97);transition:transform 200ms cubic-bezier(.2,.8,.2,1);will-change:transform}"+
  ".pe-gate.in .pe-card{transform:none}.pe-gate.out .pe-card{transform:scale(.98);transition:transform 150ms ease-in}"+
  ".pe-k{font:500 11.5px/1.4 var(--mono);letter-spacing:.12em;text-transform:uppercase;color:var(--pur-l);margin:0 0 8px}"+
  ".pe-card h2{font-size:22px;line-height:1.2;letter-spacing:-.02em;margin:0 0 8px;font-weight:650;text-wrap:balance}"+
  ".pe-card p{color:var(--mute);margin:0 0 14px;font-size:14.5px}"+
  ".pe-card ul{margin:0 0 16px;padding:0;list-style:none;display:grid;gap:6px;font-size:14px}"+
  ".pe-card li::before{content:'✓';color:var(--green-l);margin-right:8px}"+
  ".pe-f{display:flex;gap:8px;flex-wrap:wrap}.pe-f input{flex:1 1 200px;min-width:0;font-size:16px;padding:11px 12px;border-radius:9px;border:1px solid var(--line);background:var(--panel2);color:var(--fg)}"+
  ".pe-f input:focus{outline:none;border-color:var(--pur)}"+
  ".pe-b{font:600 14.5px/1 var(--sans);padding:12px 16px;border-radius:9px;border:1px solid var(--pur);background:var(--pur);color:#fff;text-decoration:none;display:inline-flex;align-items:center;justify-content:center;gap:6px;transition:transform 160ms cubic-bezier(.2,.8,.2,1),opacity 160ms ease;will-change:transform}"+
  ".pe-b.ghost{background:none;color:var(--fg);border-color:var(--line)}"+
  ".pe-b:active{transform:scale(.97)}.pe-b[disabled]{opacity:.6}"+
  ".pe-row{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}.pe-row>*{flex:1 1 auto}"+
  ".pe-s{font-size:12px!important;color:var(--dim)!important;margin:10px 0 0!important}.pe-s a{color:var(--mute)}"+
  ".pe-msg{font-size:13px!important;margin:10px 0 0!important}.pe-msg:empty{display:none}.pe-msg.err{color:var(--red-l)!important}.pe-msg.ok{color:var(--green-l)!important}"+
  ".pe-link{display:block;background:none;border:0;padding:0;color:var(--mute);text-decoration:underline;text-underline-offset:3px;font-size:13px;margin-top:14px}"+
  ".pe-f+.pe-msg,.pe-link+.pe-f{margin-top:10px}"+
  ".pe-hide{display:none!important}"+
  ".pill.plan{cursor:pointer;color:var(--pur-l);border-color:var(--pur-edge);background:var(--pur-soft);transition:transform 160ms cubic-bezier(.2,.8,.2,1)}"+
  ".pill.plan:active{transform:scale(.97)}.pill.plan.warn{color:var(--amber-l);border-color:#f59e0b66;background:var(--amber-soft)}"+
  ".pe-pop{position:fixed;z-index:40;width:min(300px,calc(100vw - 24px));background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px;box-shadow:var(--elev),0 20px 50px -20px rgba(0,0,0,.5);font-size:13.5px;opacity:0;transform:scale(.97);transform-origin:top right;transition:opacity 160ms ease-out,transform 160ms cubic-bezier(.2,.8,.2,1)}"+
  ".pe-pop.in{opacity:1;transform:none}.pe-pop b{display:block;font-size:14.5px;margin-bottom:4px}.pe-pop p{margin:0 0 10px;color:var(--mute)}"+
  ".pe-pop .pe-b{width:100%;padding:10px 12px;font-size:13.5px}.pe-pop .pe-b+.pe-b{margin-top:6px}"+
  ".pe-bar{display:flex;align-items:center;justify-content:center;gap:10px;flex-wrap:wrap;padding:8px 16px;font-size:13px;background:var(--pur-box);border-bottom:1px solid var(--pur-edge);color:var(--fg)}"+
  ".pe-bar button{font:600 12.5px/1 var(--sans);padding:7px 11px;border-radius:7px;border:1px solid var(--pur);background:var(--pur);color:#fff}"+
  ".pe-fb textarea{width:100%;min-height:110px;font:16px/1.4 var(--sans);padding:10px 12px;border-radius:9px;border:1px solid var(--line);background:var(--panel2);color:var(--fg);resize:vertical}"+
  ".pe-fb textarea:focus{outline:none;border-color:var(--pur)}"+
  "@media (prefers-reduced-motion:reduce){.pe-gate,.pe-card,.pe-pop{transition:none!important}}"+
  "@media (max-width:520px){.pe-card{padding:20px 18px}.pe-card h2{font-size:20px}}";
  function h(tag,attrs,kids){var e=document.createElement(tag);for(var k in attrs||{}){if(k==="text")e.textContent=attrs[k];else if(k==="html")e.innerHTML=attrs[k];else e.setAttribute(k,attrs[k])}(kids||[]).forEach(function(c){if(c)e.appendChild(c)});return e}

  var open=null;
  function modal(card,dismissable){
    close(true);
    var g=h("div",{"class":"pe-gate",role:"dialog","aria-modal":"true"},[card]);
    if(dismissable){g.addEventListener("click",function(e){if(e.target===g)close()});}
    document.body.appendChild(g);open=g;
    requestAnimationFrame(function(){requestAnimationFrame(function(){g.classList.add("in")})});
    var f=card.querySelector("input,textarea,button");if(f&&matchMedia("(hover:hover)").matches)f.focus({preventScroll:true});
    return g;
  }
  function close(now){
    var g=open;if(!g)return;open=null;
    if(now){g.remove();return}
    g.classList.add("out");g.classList.remove("in");setTimeout(function(){g.remove()},160);
  }
  document.addEventListener("keydown",function(e){if(e.key==="Escape"&&open&&open.dataset.esc)close()});

  function post(data){
    return fetch(FORMSPREE,{method:"POST",headers:{"Content-Type":"application/json",Accept:"application/json"},body:JSON.stringify(data)})
      .then(function(r){if(!r.ok)throw new Error("form")});
  }
  function validEmail(s){return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(s)}

  function passForm(){
    var inp=h("input",{type:"text",placeholder:"Paste your access link",autocomplete:"off","aria-label":"Access link"}),
        btn=h("button",{"class":"pe-b ghost",type:"submit",text:"Open"}),msg=h("p",{"class":"pe-msg"}),
        f=h("form",{"class":"pe-f pe-hide"},[inp,btn]);
    f.addEventListener("submit",function(e){
      e.preventDefault();var m=inp.value.match(/pass=([A-Za-z0-9_\-.]+)/)||inp.value.trim().match(/^([A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+)$/);
      if(!m){msg.textContent="Paste the whole link from your email.";msg.className="pe-msg err";return}
      verify(m[1]).then(function(p){
        if(!p){msg.textContent="That link isn't valid. Ask PulsEdge for a new one.";msg.className="pe-msg err";return}
        store("pe_pass",m[1]);location.reload();
      });
    });
    var toggle=h("button",{type:"button","class":"pe-link",text:"I have an access link"});
    toggle.onclick=function(){f.classList.remove("pe-hide");toggle.classList.add("pe-hide");inp.focus()};
    return [toggle,f,msg];
  }

  function gate(a,onSample){
    var ended=a.state==="ended";
    var k=h("p",{"class":"pe-k",text:ended?(a.kind==="pass"&&!a.trial?"Access ended":"Trial ended"):"PULSE terminal"});
    var title=h("h2",{text:ended?(a.trial?"Your free trial has ended":"Your access has ended"):"Try PULSE free for "+TRIAL_SESSIONS+" trading sessions"});
    var kids=[k,title];
    if(ended){
      kids.push(h("p",{text:a.trial?"You've used all "+a.trial.total+" trading sessions. Keep the terminal with Pro, or apply for one of the 15 founding seats.":"Your "+(a.label||"access")+" ran until "+nice(a.until)+". Renew to keep live signals."}));
      kids.push(h("div",{"class":"pe-row"},[h("a",{"class":"pe-b",href:"index.html#pricing",text:"See plans"}),(function(){var b=h("button",{"class":"pe-b ghost",type:"button",text:"Send feedback"});b.onclick=function(){feedback(a)};return b})()]));
    }else{
      kids.push(h("p",{text:"Live signals sorted into Ignore, Watch and Act, the pre-market checklist, and alerts for your own stocks. No card or payment details."}));
      var inp=h("input",{type:"email",required:"",placeholder:"you@email.com",autocomplete:"email","aria-label":"Email address"}),
          btn=h("button",{"class":"pe-b",type:"submit",text:"Start free trial"}),msg=h("p",{"class":"pe-msg"}),
          f=h("form",{"class":"pe-f"},[inp,btn]);
      f.addEventListener("submit",function(e){
        e.preventDefault();var email=inp.value.trim().toLowerCase();
        if(!validEmail(email)){msg.textContent="Enter a full email address, like you@email.com.";msg.className="pe-msg err";return}
        btn.disabled=true;msg.textContent="Starting…";msg.className="pe-msg";
        var rec={email:email,at:new Date().toISOString(),n:TRIAL_SESSIONS};
        // The trial starts even if the signup can't be recorded; the email is retried on the next visit.
        post({email:email,source:"trial",plan:"trial7",sessions:TRIAL_SESSIONS,_subject:"PulsEdge trial started: "+email})
          .then(function(){rec.sent=1},function(){})
          .then(function(){store("pe_trial",JSON.stringify(rec));location.reload()});
      });
      kids.push(f,msg,h("p",{"class":"pe-s",html:'By starting you agree to the <a href="terms.html">Terms</a> and <a href="privacy.html">Privacy Policy</a>. Educational information, not investment advice.'}));
    }
    passForm().forEach(function(x){kids.push(x)});
    if(linkMsg){var lm=h("p",{"class":"pe-msg err",text:linkMsg});kids.splice(2,0,lm)}
    var sample=h("button",{type:"button","class":"pe-link",text:"Look around with sample data"});
    sample.onclick=function(){try{sessionStorage.setItem("pe_sample","1")}catch(e){}close();onSample()};
    kids.push(sample);
    modal(h("div",{"class":"pe-card"},kids));
  }

  function feedback(a){
    var ta=h("textarea",{placeholder:"What worked, what didn't, what you'd pay for…","aria-label":"Feedback"}),
        em=h("input",{type:"email",placeholder:"Email (optional, if you'd like a reply)",autocomplete:"email","aria-label":"Email"}),
        msg=h("p",{"class":"pe-msg"}),send=h("button",{"class":"pe-b",type:"submit",text:"Send"}),
        cancel=h("button",{"class":"pe-b ghost",type:"button",text:"Close"});
    if(a&&a.email)em.value=a.email;
    var f=h("form",{"class":"pe-fb"},[ta,h("div",{"class":"pe-f",style:"margin-top:8px"},[em]),h("div",{"class":"pe-row"},[send,cancel]),msg]);
    cancel.onclick=function(){close()};
    f.addEventListener("submit",function(e){
      e.preventDefault();var text=ta.value.trim();
      if(text.length<3){msg.textContent="Write a few words first.";msg.className="pe-msg err";return}
      send.disabled=true;msg.textContent="Sending…";msg.className="pe-msg";
      post({message:text,email:em.value.trim(),source:"feedback",plan:a&&a.plan||"",_subject:"PulsEdge feedback"})
        .then(function(){msg.textContent="Thanks — it goes straight to the founder.";msg.className="pe-msg ok";ta.value="";setTimeout(close,1400)},
              function(){msg.textContent="Couldn't send. Message us on Telegram instead: t.me/pulsedgein";msg.className="pe-msg err"})
        .then(function(){send.disabled=false});
    });
    var g=modal(h("div",{"class":"pe-card"},[h("p",{"class":"pe-k",text:"Feedback"}),h("h2",{text:"Tell us how PULSE is working for you"}),f]),true);
    g.dataset.esc="1";
  }

  function chip(a,anchor){
    var t=a.trial,c;
    if(t)c=h("button",{type:"button","class":"pill plan"+(t.left<=1?" warn":""),
      text:t.lastDay?"TRIAL · LAST DAY":t.left?"TRIAL · "+t.left+" LEFT":"TRIAL · ENDS "+nice(t.next).split(",")[0].toUpperCase()});
    else c=h("button",{type:"button","class":"pill plan",text:(a.plan==="founding"?"FOUNDING":a.plan==="comp"?"GUEST":"PRO")});
    c.setAttribute("aria-haspopup","dialog");
    c.onclick=function(e){e.stopPropagation();popover(a,c)};
    anchor.parentNode.insertBefore(c,anchor);
  }
  var pop=null;
  function popover(a,btn){
    if(pop){var p0=pop;pop=null;p0.remove();return}
    var t=a.trial,kids=[h("b",{text:a.label})];
    if(t)kids.push(h("p",{text:(t.lastDay?"Today is your last trading session.":t.left?t.left+" of "+t.total+" trading sessions left. Last session: "+nice(t.last)+".":"All "+t.total+" sessions used. Access ends when trading opens on "+nice(t.next)+".")+(a.email?" Signed up as "+a.email+".":"")}));
    else kids.push(h("p",{text:(a.until?"Active until "+nice(a.until)+".":"Active.")+(a.email?" For "+a.email+".":"")}));
    if(t||a.plan==="comp")kids.push(h("a",{"class":"pe-b",href:"index.html#pricing",text:"See plans"}));
    var fb=h("button",{"class":"pe-b ghost",type:"button",text:"Send feedback"});fb.onclick=function(){pop.remove();pop=null;feedback(a)};kids.push(fb);
    var p=h("div",{"class":"pe-pop",role:"dialog","aria-label":"Your plan"},kids),r=btn.getBoundingClientRect();
    p.style.top=(r.bottom+8)+"px";p.style.right=Math.max(12,innerWidth-r.right)+"px";
    document.body.appendChild(p);pop=p;requestAnimationFrame(function(){p.classList.add("in")});
  }
  document.addEventListener("click",function(e){if(pop&&!pop.contains(e.target)){pop.remove();pop=null}});

  function sampleBar(onStart){
    var b=h("button",{type:"button",text:"Start free trial"});b.onclick=onStart;
    var bar=h("div",{"class":"pe-bar"},[h("span",{text:"You're looking at sample data."}),b]);
    var top=document.querySelector(".top");top.insertBefore(bar,top.firstChild);
  }

  // Called by the terminal: resolves to {mode:"live"|"sample", access}
  function guard(){
    var style=h("style",{text:css});document.head.appendChild(style);
    return ready.then(function(a){
      var anchor=document.querySelector(".top .back");
      if(a.granted){if(anchor)chip(a,anchor);return {mode:"live",access:a}}
      var sampleOk=false;try{sampleOk=sessionStorage.getItem("pe_sample")==="1"&&!/[#&]trial\b/.test(location.hash)}catch(e){}
      var reopen=function(){gate(a,function(){})};
      sampleBar(reopen);
      if(!sampleOk)gate(a,function(){});
      return {mode:"sample",access:a};
    });
  }

  // Signups that couldn't be sent when the trial started are retried on later visits.
  ready.then(function(){
    var t=null;try{t=JSON.parse(store("pe_trial")||"null")}catch(e){}
    if(t&&t.email&&!t.sent)post({email:t.email,source:"trial",plan:"trial7",sessions:t.n,_subject:"PulsEdge trial started: "+t.email})
      .then(function(){t.sent=1;store("pe_trial",JSON.stringify(t))},function(){});
  });

  window.PulseAccess={ready:ready,guard:guard,feedback:function(){ready.then(feedback)},
    // exposed for tests and for HQ parity
    _cal:{isSession:isSession,nextSession:nextSession,nthSession:nthSession,trialState:trialState}};
})();

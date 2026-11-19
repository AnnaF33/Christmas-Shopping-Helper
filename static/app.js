// Browser side of the Christmas Shopping Helper.
// It collects the gift list and shows results. The catalogue, the matching rules and any
// API keys live on the server (see app.py); this file only talks to /api/....

let people=[],recs={},picked={},editing=null,touched=false,cur=1;
let CFG={relationships:[],age_bands:[],source:null};
const P={};           // every product the server has sent, by id
const $=id=>document.getElementById(id);
const esc=s=>String(s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const money=n=>"$"+(Number.isInteger(n)?n:n.toFixed(2));
const rel=name=>CFG.relationships.find(r=>r.name===name);
const band=v=>CFG.age_bands.find(b=>b.value===v);

function save(){try{localStorage.setItem("csa_people",JSON.stringify(people))}catch(e){}}
try{people=JSON.parse(localStorage.getItem("csa_people")||"[]")}catch(e){people=[]}

async function api(path,body){
  let r;
  try{r=await fetch(path,body?{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)}:undefined)}
  catch(e){throw new Error("Can't reach the server. Is it running? Start it with: python app.py")}
  const j=await r.json().catch(()=>({}));
  if(!r.ok)throw new Error(j.error||("The server returned an error ("+r.status+")."));
  return j;
}

// ---- Start-up: fetch the form options from the server, then draw the page.
async function init(){
  try{
    CFG=await api("/api/config");
    $("f_rel").insertAdjacentHTML("beforeend",CFG.relationships.map(r=>`<option>${esc(r.name)}</option>`).join(""));
    $("f_age").insertAdjacentHTML("beforeend",CFG.age_bands.map(b=>`<option value="${esc(b.value)}">${esc(b.label)}</option>`).join(""));
    if(CFG.error)note(CFG.error,true);
    else if(CFG.source==="sample")note("<b>Sample catalogue.</b> Products, shops and prices are invented and the shop links go nowhere. Your agent can buy these gifts from North Pole Gift Co, a demo seller, in Stripe's sandbox: no real money moves.");
    else note("<b>Live listings from "+esc(CFG.source_label||CFG.source)+".</b> Prices can change, and you buy at the shop. Nothing is purchased from this page.");
  }catch(e){note(esc(e.message),true)}
  // Bring recipients saved by earlier versions up to date (numeric ages become bands).
  people.forEach(p=>{p.asked=p.asked||"";if(p.age&&!band(p.age)){const n=+p.age,b=CFG.age_bands.find(b=>n>=b.min&&n<=b.max);p.age=b?b.value:""}});
  renderPeople();
}
function note(html,isErr){$("note").innerHTML=html;$("note").classList.toggle("err",!!isErr)}

// ---- Step 1: the gift list
function label(p,i){return p.name||p.rel||("Recipient "+(i+1))}
function ageLabel(p){return p.age?({"13-17":"teen","18-64":"adult","65+":"65+"}[p.age]||"age "+p.age.replace("-","–")):""}
function budget(p){return (p.min!==""||p.max!=="")?"$"+(p.min===""?0:p.min)+(p.max===""?"+":"–$"+p.max):""}
function desc(p){const b=[];if(p.name&&p.rel)b.push(p.rel);if(p.age)b.push(ageLabel(p));if(p.int)b.push(p.int);if(p.asked)b.push("asked for "+p.asked);
  if(budget(p))b.push(budget(p));return b.join(" · ")}

function renderPeople(){
  const ic=Object.keys(D);
  $("people").innerHTML=people.length?people.map((p,i)=>{const who=[p.rel,ageLabel(p),p.gen].filter(Boolean).join(" · ");
   return `<div class="tagw"><div class="tag"><span class="hole"></span><svg viewBox="0 0 100 100">${D[ic[i%ic.length]]}</svg><div class="tb"><div class="to">To</div><div class="tn">${esc(label(p,i))}</div>
   ${who?`<div class="meta">${esc(who)}</div>`:""}${p.int?`<div class="meta">Loves ${esc(p.int)}</div>`:""}${p.asked?`<div class="meta">Asked for ${esc(p.asked)}</div>`:""}${budget(p)?`<span class="bud">${budget(p)}</span>`:""}
   <div class="ta"><button class="lnk" onclick="edit(${i})">Edit</button><button class="lnk" onclick="del(${i})">Remove</button></div></div></div></div>`}).join(""):
   `<div class="empty">No one yet. Add a recipient above. Name, relationship, interests and price range are required.</div>`;
  $("findBtn").disabled=!people.length;$("tab2").disabled=!people.length;$("tab3").disabled=!people.length;
}

["f_name","f_rel","f_age","f_int","f_min","f_max"].forEach(id=>$(id).addEventListener("input",()=>$(id).setCustomValidity("")));
$("form").addEventListener("submit",e=>{e.preventDefault();
  const kid=(rel($("f_rel").value)||{}).age_required;
  for(const id of["f_name","f_rel"].concat(kid?["f_age"]:[],["f_int"]))if(!$(id).value.trim()){$(id).setCustomValidity("Please fill in this field.");$(id).reportValidity();return}
  if(+$("f_max").value<+$("f_min").value){$("f_max").setCustomValidity("Max must be at least the min.");$("f_max").reportValidity();return}
  const p={id:editing!==null?people[editing].id:Date.now(),name:$("f_name").value.trim(),rel:$("f_rel").value,age:$("f_age").value,gen:$("f_gen").value,
    int:$("f_int").value.trim(),asked:$("f_asked").value.trim(),min:$("f_min").value,max:$("f_max").value==="500"?"":$("f_max").value};
  if(editing!==null){people[editing]=p;delete recs[p.id];picked[p.id]=[];editing=null;$("addBtn").textContent="Add recipient"}else people.push(p);
  $("form").reset();touched=false;relChange();price();save();renderPeople();bar();$("f_name").focus()});
function edit(i){const p=people[i];editing=i;$("f_name").value=p.name;$("f_rel").value=p.rel;$("f_age").value=p.age;$("f_gen").value=p.gen;$("f_int").value=p.int;$("f_asked").value=p.asked||"";
  touched=true;relChange();$("f_min").value=p.min===""?0:p.min;$("f_max").value=p.max===""?500:p.max;price();$("addBtn").textContent="Save changes";$("f_name").focus();window.scrollTo(0,0)}
function del(i){const id=people[i].id;people.splice(i,1);delete recs[id];delete picked[id];if(editing!==null){editing=null;$("addBtn").textContent="Add recipient";$("form").reset();touched=false;relChange();price()}save();renderPeople();bar()}
function demo(){people=[
 {id:1,name:"Grandma Jo",rel:"Parent or in-law",age:"65+",gen:"Female",int:"gardening, baking, crime novels",asked:"a new scarf",min:"30",max:"80"},
 {id:2,name:"Max",rel:"Niece or nephew",age:"6-9",gen:"Male",int:"lego, dinosaurs, soccer",asked:"",min:"",max:"50"},
 {id:3,name:"Sam",rel:"Colleague",age:"",gen:"",int:"coffee, hiking",asked:"",min:"20",max:"40"}];recs={};picked={};save();renderPeople();bar()}

// Relationship drives two things: whether age is required, and a suggested price range
// (until the user moves the slider themselves).
function relChange(){const r=rel($("f_rel").value),kid=!!(r&&r.age_required);
  $("f_age").required=kid;$("ageReq").innerHTML=kid?'<i class="req">*</i>':'<span>(optional)</span>';
  if(r&&!touched){$("f_min").value=r.min;$("f_max").value=r.max;price()}
  $("sug").textContent=r?"Suggested for this relationship: $"+r.min+"–$"+r.max+". Adjust to suit.":""}
$("f_rel").addEventListener("change",relChange);

function price(src){const a=$("f_min"),b=$("f_max");if(+a.value>+b.value-5){if(src===a)a.value=Math.max(0,+b.value-5);else b.value=Math.min(500,+a.value+5)}
  $("fill").style.left=(a.value/5)+"%";$("fill").style.right=(100-b.value/5)+"%";$("pv").textContent="$"+a.value+" – $"+b.value+(b.value==="500"?"+":"");
  a.style.zIndex=+a.value>400?3:1;b.style.zIndex=2}
$("f_min").addEventListener("input",e=>{touched=true;price(e.target)});$("f_max").addEventListener("input",e=>{touched=true;price(e.target)});

// ---- Step 2: recommendations, fetched from the server once per recipient
async function ensureRecs(){
  await Promise.all(people.map(async p=>{picked[p.id]=picked[p.id]||[];
    if(recs[p.id]&&!recs[p.id].error)return;
    try{const j=await api("/api/recommendations",{recipient:p}),all=j.picks.concat(j.alternates);
      all.forEach(x=>{P[x.id]=x});
      recs[p.id]={ids:j.picks.map(x=>x.id),pool:all.map(x=>x.id),why:Object.fromEntries(all.map(x=>[x.id,x.why])),missing:j.missing_asked,seen:[]}}
    catch(e){recs[p.id]={error:e.message,ids:[],pool:[],why:{},missing:[],seen:[]}}}));
}
function swap(pid,slot,ev){ev.stopPropagation();const r=recs[pid],list=r.pool.filter(id=>!r.ids.includes(id));
  if(!list.length)return;let nx=list.find(id=>!r.seen.includes(id));if(nx===undefined){r.seen=[];nx=list[0]}
  r.seen.push(r.ids[slot]);picked[pid]=picked[pid].filter(id=>id!==r.ids[slot]);r.ids[slot]=nx;renderRecs();bar()}
function toggle(pid,id){const a=picked[pid];const i=a.indexOf(id);i<0?a.push(id):a.splice(i,1);renderRecs();bar()}
function shopLink(it){return it.url?`<a href="${esc(it.url)}" target="_blank" rel="noopener" onclick="event.stopPropagation()">View in shop ↗</a>`:
  `<a href="#" onclick="event.preventDefault();event.stopPropagation()">View in shop ↗ (sample)</a>`}
function renderRecs(){
  $("recs").innerHTML=people.map((p,i)=>{const r=recs[p.id]||{ids:[],why:{},missing:[]};
   const cards=r.ids.map((id,slot)=>{const it=P[id],on=picked[p.id].includes(id);
    return `<div class="rec ${on?"sel":""}" onclick="toggle(${p.id},'${esc(id)}')">
     <input class="tick" type="checkbox" ${on?"checked":""} aria-label="Select ${esc(it.name)}">
     <button class="swap" onclick="swap(${p.id},${slot},event)">↻ Swap</button>
     <div class="img" style="background:${esc(it.bg)}">${it.image_url?`<img src="${esc(it.image_url)}" alt="">`:esc(it.emoji)}</div>
     <div class="body"><div class="t">${esc(it.name)}</div><div class="why">${esc(r.why[id]||"")}</div>
     <div class="row" style="justify-content:space-between"><span class="p">${money(it.price)}</span><span class="shop">${esc(it.shop)}</span></div>
     ${shopLink(it)}</div></div>`}).join("");
   const miss=r.missing.length?`<p class="miss">Asked for, but not found at this price: ${esc(r.missing.join(", "))}.</p>`:"";
   const body=r.error?`<div class="note err" style="margin:0">${esc(r.error)}</div>`:
     r.ids.length?`<div class="recs">${cards}</div>${miss}`:`<div class="card meta">Nothing found for these interests at this price. Try widening the price range or rewording the interests.</div>${miss}`;
   return `<div class="sec"><h3>${esc(label(p,i))} <span class="meta">· ${esc(desc(p))}</span></h3>${body}</div>`}).join("");
}

// ---- Step 3: basket
function totals(){let n=0,t=0;people.forEach(p=>(picked[p.id]||[]).forEach(id=>{n++;t+=P[id].price}));return{n,t}}
function bar(){const{n,t}=totals();$("bar").classList.toggle("hide",!n||cur===3);$("barTxt").textContent=n+" gift"+(n===1?"":"s")+" selected · "+money(t)}
function renderBasket(){
  const by={};people.forEach((p,i)=>(picked[p.id]||[]).forEach(id=>{const it=P[id];(by[it.shop]=by[it.shop]||[]).push({it,who:label(p,i),bought:BOUGHT[boughtKey(p.id,id)]})}));
  const shops=Object.keys(by),{n,t}=totals();
  const none=people.filter(p=>!(picked[p.id]||[]).length).map(p=>label(p,people.indexOf(p)));
  if(!n){$("basket").innerHTML=`<div class="card meta">Nothing selected yet. Go back to Recommendations and tick some gifts.</div>`;return}
  $("basket").innerHTML=shops.map(s=>{const sub=by[s].reduce((a,x)=>a+x.it.price,0);
   return `<div class="card sec"><h3 style="margin:0 0 8px">${esc(s)}</h3>
   <table><tr><th>Gift</th><th>For</th><th class="r">Price</th><th class="r">Buy</th></tr>${by[s].map(x=>`<tr><td>${x.it.image_url?"":esc(x.it.emoji)+" "}${esc(x.it.name)}</td><td>${esc(x.who)}</td><td class="r">${money(x.it.price)}</td>
   <td class="r">${x.bought?`<span class="bought" title="Order ${esc(x.bought)}">Bought ✓</span>`:x.it.url?`<a href="${esc(x.it.url)}" target="_blank" rel="noopener">Buy at shop ↗</a>`:`<span class="meta">sample</span>`}</td></tr>`).join("")}
   <tr><td colspan="2"><b>Subtotal</b></td><td class="r"><b>${money(sub)}</b></td><td></td></tr></table></div>`}).join("")+
   `<div class="card"><div class="row" style="justify-content:space-between"><div><div class="meta">${n} gift${n===1?"":"s"} from ${shops.length} shop${shops.length===1?"":"s"}, before shipping and tax</div><div class="total">${money(t)}</div></div>
   </div>
   ${none.length?`<p class="meta" style="margin-bottom:0">Still nothing chosen for: ${esc(none.join(", "))}</p>`:""}</div>
   <div id="agentBox"></div>`;
  renderAgent();loadWallet();
}

// ---- Agent checkout (the "save a card in the app" path)
// The buyer saves a card with Stripe, sets a mandate (cap + end date), and approves the
// basket once. The server opens a checkout at North Pole Gift Co, issues a payment token
// capped at that total, and the shop charges it. Every step appears in the activity log.
let WALLET=null,STOCK=null,ACTIVITY=[],LAST=null,stripeJs=null,elements=null,busy=false;
let BOUGHT={};try{BOUGHT=JSON.parse(localStorage.getItem("csa_bought")||"{}")}catch(e){BOUGHT={}}
const boughtKey=(pid,id)=>pid+":"+id;
function markBought(items,order){items.forEach(x=>{BOUGHT[boughtKey(x.pid,x.id)]=order});try{localStorage.setItem("csa_bought",JSON.stringify(BOUGHT))}catch(e){}}
const fmtDate=t=>new Date(t*1000).toLocaleDateString(undefined,{day:"numeric",month:"short",year:"numeric"});
const cents=c=>money(c/100);
function basketItems(){const out=[];people.forEach((p,i)=>(picked[p.id]||[]).forEach(id=>out.push({id,pid:p.id,for:label(p,i),budget_max:p.max===""?null:+p.max,it:P[id],bought:BOUGHT[boughtKey(p.id,id)]})));return out}
function toBuy(){return basketItems().filter(x=>STOCK&&STOCK.has(x.id)&&!x.bought)}
async function loadWallet(){if(!$("agentBox"))return;
  try{if(!STOCK)STOCK=new Set((await api("/demo-shop/products")).products.map(p=>p.id))}catch(e){STOCK=new Set()}
  if(ME){try{WALLET=await api("/api/wallet");ACTIVITY=(await api("/api/wallet/activity")).events}catch(e){WALLET={error:e.message}}}
  else{WALLET=null;ACTIVITY=[]}
  renderAgent()}
function renderAgent(){const box=$("agentBox");if(!box)return;
  const items=basketItems(),buyable=toBuy(),done=items.filter(x=>x.bought).length,other=items.filter(x=>!x.bought&&!(STOCK&&STOCK.has(x.id))).length;
  const total=buyable.reduce((a,x)=>a+Math.round(x.it.price*100),0);
  let h=`<div class="card sec agent"><h3 style="margin:0 0 4px">Let the helper buy it <span class="pill">Stripe sandbox · test card only</span></h3>
   <p class="meta" style="margin:0 0 14px">Your agent pays North Pole Gift Co (a demo seller) with a one-time payment token capped at the exact total. The shop never sees your card, and the agent can't go over the limit you set.</p>`;
  if(!ME){box.innerHTML=h+`<div class="row"><button class="btn" onclick="openAuth('signup')">Create account</button><button class="btn ghost" onclick="openAuth('login')">Sign in</button></div></div>`;return}
  if(!WALLET){box.innerHTML=h+`<p class="meta">Loading…</p></div>`;return}
  if(WALLET.error||!WALLET.ready){box.innerHTML=h+`<div class="note err" style="margin:0">${esc(WALLET.error||"The agent checkout isn't set up on this server yet.")}</div></div>`;return}
  const card=WALLET.card,m=WALLET.mandate;
  h+=`<div class="steps3">
   <div class="step ${card?"done":""}"><b>1 · Card</b>${card?`<div>${esc((card.brand||"card").toUpperCase())} •••• ${esc(card.last4)}</div><button class="lnk" onclick="removeCard()">Remove</button>`:
     `<div class="meta">Saved securely with Stripe.</div><button class="btn sm" onclick="openCard()">Save a card</button>`}</div>
   <div class="step ${m?"done":""}"><b>2 · Mandate</b>${m?`<div>Up to ${cents(m.cap)} until ${fmtDate(m.expires_at)}</div><div class="meta">${cents(m.remaining)} left</div><button class="lnk" onclick="revokeMandate()">Revoke</button>`:
     `<div class="row" style="gap:6px;margin-top:4px"><label class="mini">Cap $<input id="m_cap" type="number" min="1" max="2000" step="1" value="${Math.max(10,Math.ceil(total/1000)*10)}"></label>
      <label class="mini">Until <input id="m_until" type="date" value="${defaultUntil()}"></label></div><button class="btn sm" style="margin-top:6px" onclick="setMandate()">Set mandate</button>`}</div>
   <div class="step ${!buyable.length&&done?"done":""}"><b>3 · Approve</b><div>${buyable.length?`${buyable.length} gift${buyable.length===1?"":"s"} to buy · ${cents(total)}`:done?`All ${done} gift${done===1?"":"s"} bought ✓`:"Nothing to buy yet"}</div>
     ${done&&buyable.length?`<div class="meta">${done} already bought</div>`:""}
     <button class="btn red sm" ${card&&m&&buyable.length&&!busy?"":"disabled"} onclick="approve()">${busy?"Buying…":buyable.length?"Buy all with one approval":"All bought"}</button></div>
  </div>`;
  if(other)h+=`<p class="meta">${other} gift${other===1?" isn't":"s aren't"} stocked by North Pole Gift Co. Buy ${other===1?"it":"those"} at the shop with the links above.</p>`;
  if(LAST)h+=LAST.ok?`<div class="note ok">Paid ${cents(LAST.total)} to ${esc(LAST.seller)}. Order <b>${esc(LAST.order)}</b> confirmed.</div>`:`<div class="note err">${esc(LAST.error)}</div>`;
  if(ACTIVITY.length)h+=`<h3 style="margin:16px 0 6px;font-size:14px">Agent activity</h3><ol class="log">${ACTIVITY.slice(0,12).map(e=>`<li class="${esc(e.kind)}"><span class="t">${new Date(e.at*1000).toLocaleTimeString([], {hour:"2-digit",minute:"2-digit"})}</span>${esc(e.message)}</li>`).join("")}</ol>`;
  box.innerHTML=h+`</div>`}
function defaultUntil(){const d=new Date();d.setDate(d.getDate()+14);return d.toISOString().slice(0,10)}
async function setMandate(){try{await api("/api/wallet/mandate",{cap:$("m_cap").value,expires_on:$("m_until").value});LAST=null}catch(e){LAST={error:e.message}}loadWallet()}
async function revokeMandate(){try{await api("/api/wallet/mandate/revoke",{})}catch(e){}loadWallet()}
async function removeCard(){try{await api("/api/wallet/card/remove",{})}catch(e){}loadWallet()}
function loadStripeJs(){return new Promise((ok,bad)=>{if(window.Stripe)return ok();const s=document.createElement("script");s.src="https://js.stripe.com/v3/";s.onload=ok;s.onerror=()=>bad(new Error("Couldn't load Stripe's card form. Check your connection."));document.head.appendChild(s)})}
async function openCard(){$("cardErr").classList.add("hide");$("cardDlg").showModal();$("cardMount").innerHTML='<p class="meta">Loading the secure card form…</p>';$("cardGo").disabled=true;
  try{await loadStripeJs();stripeJs=stripeJs||Stripe(WALLET.publishable_key);
    const {client_secret}=await api("/api/wallet/setup-intent",{});
    elements=stripeJs.elements({clientSecret:client_secret,appearance:{theme:"stripe",variables:{colorPrimary:"#1f3d2f",borderRadius:"9px"}}});
    $("cardMount").innerHTML="";elements.create("payment",{layout:"tabs"}).mount("#cardMount");$("cardGo").disabled=false}
  catch(e){$("cardErr").textContent=e.message;$("cardErr").classList.remove("hide")}}
$("cardCancel").addEventListener("click",()=>$("cardDlg").close());
$("cardForm").addEventListener("submit",async e=>{e.preventDefault();const go=$("cardGo");go.disabled=true;$("cardErr").classList.add("hide");
  try{const {error,setupIntent}=await stripeJs.confirmSetup({elements,redirect:"if_required"});
    if(error)throw new Error(error.message);
    await api("/api/wallet/card",{setup_intent:setupIntent.id});$("cardDlg").close();loadWallet()}
  catch(err){$("cardErr").textContent=err.message;$("cardErr").classList.remove("hide")}
  finally{go.disabled=false}});
function approve(){const items=toBuy(),total=items.reduce((a,x)=>a+Math.round(x.it.price*100),0),c=WALLET.card;
  $("apList").innerHTML=items.map(x=>`<tr><td>${esc(x.it.name)}</td><td>${esc(x.for)}</td><td class="r">${money(x.it.price)}</td></tr>`).join("")+`<tr><td colspan="2"><b>Total to North Pole Gift Co</b></td><td class="r"><b>${cents(total)}</b></td></tr>`;
  $("apText").innerHTML=`Your agent will create a one-time payment token from your ${esc((c.brand||"card").toUpperCase())} •••• ${esc(c.last4)}, usable only by North Pole Gift Co, for up to <b>${cents(total)}</b>, valid 15 minutes. It counts against your mandate (${cents(WALLET.mandate.remaining)} left).`;
  $("apDlg").showModal()}
$("apCancel").addEventListener("click",()=>$("apDlg").close());
$("apGo").addEventListener("click",async()=>{$("apDlg").close();busy=true;LAST=null;renderAgent();
  const chosen=toBuy(),items=chosen.map(x=>({id:x.id,quantity:1,for:x.for,budget_max:x.budget_max}));
  const key=(crypto.randomUUID?crypto.randomUUID():String(Date.now()+Math.random()));
  try{const j=await api("/api/wallet/purchase",{key,items});LAST={ok:true,...j};markBought(chosen,j.order)}catch(e){LAST={error:e.message}}
  busy=false;renderBasket()});

// ---- Account: sign up, sign in, sign out. The gift list still lives in this browser;
// the account is what a connected wallet will belong to.
let ME=null,authMode="login";
function renderAcct(){$("acct").innerHTML=ME?
  `<span class="who">Signed in as ${esc(ME.email)}</span><button class="lnk light" onclick="signOut()">Sign out</button>`:
  `<button class="lnk light" onclick="openAuth('login')">Sign in</button><button class="btn sm gold" onclick="openAuth('signup')">Create account</button>`}
function openAuth(mode){authMode=mode;const up=mode==="signup";
  $("authTitle").textContent=up?"Create your account":"Sign in";$("authGo").textContent=up?"Create account":"Sign in";
  $("authSwap").textContent=up?"I already have an account":"Create an account instead";
  $("a_pw").autocomplete=up?"new-password":"current-password";
  $("authHint").textContent=up?"Use at least 10 characters. A short phrase works well.":"";
  $("authLead").textContent=up?"Create an account so you can connect a wallet and let the helper buy gifts for you.":"Welcome back.";
  $("authErr").classList.add("hide");$("authDlg").showModal();$("a_email").focus()}
$("authSwap").addEventListener("click",()=>openAuth(authMode==="signup"?"login":"signup"));
$("authCancel").addEventListener("click",()=>$("authDlg").close());
$("authForm").addEventListener("submit",async e=>{e.preventDefault();const go=$("authGo");go.disabled=true;
  try{const j=await api("/api/auth/"+authMode,{email:$("a_email").value.trim(),password:$("a_pw").value});
    ME=j.user;$("authForm").reset();$("authDlg").close();renderAcct();loadWallet()}
  catch(err){$("authErr").textContent=err.message;$("authErr").classList.remove("hide")}
  finally{go.disabled=false}});
async function signOut(){try{await api("/api/auth/logout",{})}catch(e){}ME=null;LAST=null;renderAcct();loadWallet()}
async function loadMe(){try{ME=(await api("/api/auth/me")).user}catch(e){ME=null}renderAcct()}

// ---- Moving between the three steps
async function go(n){if(n>1&&!people.length)return;cur=n;
  [1,2,3].forEach(i=>{$("s"+i).classList.toggle("hide",i!==n);$("tab"+i).classList.toggle("on",i===n)});window.scrollTo(0,0);
  if(n>=2){const waiting=people.some(p=>!recs[p.id]||recs[p.id].error);
    if(waiting)$(n===2?"recs":"basket").innerHTML=`<div class="card meta">Finding gifts…</div>`;
    await ensureRecs();if(cur!==n)return}
  if(n===2)renderRecs();if(n===3)renderBasket();bar()}

// ---- Decorations (original simple shapes)
const D={
gift:'<rect x="8" y="34" width="84" height="58" rx="5" fill="#d8392f"/><rect x="2" y="22" width="96" height="18" rx="4" fill="#e0483d"/><rect x="42" y="22" width="16" height="70" fill="#1f5a4a"/><path d="M50 22C30 0 12 10 26 22ZM50 22C70 0 88 10 74 22Z" fill="none" stroke="#1f5a4a" stroke-width="6"/>',
cane:'<path d="M34 92V36a18 18 0 0 1 36 0v6" fill="none" stroke="#d8392f" stroke-width="14" stroke-linecap="round"/><path d="M34 92V36a18 18 0 0 1 36 0v6" fill="none" stroke="#fff" stroke-width="14" stroke-dasharray="7 13"/>',
holly:'<ellipse cx="30" cy="52" rx="28" ry="13" fill="#3d5a1f" transform="rotate(-25 30 52)"/><ellipse cx="70" cy="52" rx="28" ry="13" fill="#56752a" transform="rotate(25 70 52)"/><circle cx="44" cy="30" r="8" fill="#d8392f"/><circle cx="58" cy="30" r="8" fill="#e0483d"/><circle cx="51" cy="20" r="8" fill="#c22f27"/>',
tree:'<path d="M50 6 76 40H62l20 26H64l22 26H14l22-26H18l20-26H24Z" fill="#1f6b55"/><circle cx="44" cy="44" r="3.5" fill="#f2c14e"/><circle cx="58" cy="60" r="3.5" fill="#e0483d"/><circle cx="40" cy="76" r="3.5" fill="#fff"/><circle cx="62" cy="82" r="3.5" fill="#f2c14e"/>',
sock:'<path d="M34 14h32v42l18 14a14 14 0 0 1-16 22L40 84a12 12 0 0 1-6-11Z" fill="#d8392f"/><rect x="30" y="8" width="40" height="16" rx="5" fill="#f3efe6" stroke="#ddd5c4"/><circle cx="48" cy="44" r="3" fill="#fff"/><circle cx="56" cy="62" r="3" fill="#fff"/><circle cx="68" cy="80" r="3" fill="#fff"/>',
berry:'<path d="M50 96V30M50 70 24 44M50 56 76 30M50 40 34 20" fill="none" stroke="#c9a36a" stroke-width="3"/><circle cx="24" cy="42" r="8" fill="#e0483d"/><circle cx="76" cy="28" r="8" fill="#e0483d"/><circle cx="34" cy="18" r="8" fill="#d8392f"/><circle cx="50" cy="26" r="8" fill="#c22f27"/>',
bauble:'<rect x="43" y="10" width="14" height="10" rx="2" fill="#c9a36a"/><circle cx="50" cy="56" r="36" fill="#1f6b55"/><path d="M16 50q34 16 68 0" fill="none" stroke="#f2c14e" stroke-width="5"/><circle cx="36" cy="70" r="3" fill="#fff"/><circle cx="62" cy="72" r="3" fill="#fff"/>',
mitten:'<path d="M30 40a22 22 0 0 1 44 0v36H30Z" fill="#1f6b55"/><ellipse cx="24" cy="54" rx="10" ry="16" fill="#1f6b55" transform="rotate(-20 24 54)"/><rect x="26" y="72" width="52" height="18" rx="6" fill="#f3efe6" stroke="#ddd5c4"/><path d="M52 44l4 8 8 1-6 6 2 8-8-4-8 4 2-8-6-6 8-1Z" fill="#f2c14e"/>'};
{const seq=["gift","holly","cane","tree","sock","berry","bauble","mitten"],rot=[-8,6,14,-4,10,-12,5,-10];let h="";
for(let i=0;i<40;i++){const k=seq[i%8];h+=`<svg viewBox="0 0 100 100" width="46" height="46" style="transform:rotate(${rot[i%8]}deg)">${D[k]}</svg>`}$("strip").innerHTML=h}
{const T=[["tree",20,24,-12,62],["cane",190,10,18,54],["bauble",330,60,8,50],["holly",100,150,-16,60],["gift",250,180,10,58],["sock",20,270,12,56],["berry",160,300,-10,58],["mitten",320,300,-14,52]];
const svg=`<svg xmlns="http://www.w3.org/2000/svg" width="420" height="400" viewBox="0 0 420 400"><g opacity=".2">`+T.map(([k,x,y,r,z])=>`<g transform="translate(${x} ${y}) rotate(${r} ${z/2} ${z/2}) scale(${z/100})">${D[k]}</g>`).join("")+`</g></svg>`;
document.body.style.backgroundImage=`url("data:image/svg+xml,${encodeURIComponent(svg)}")`}
$("heroart").innerHTML=`<circle cx="110" cy="104" r="92" fill="#faf6ee"/><g transform="translate(52 14) scale(1.2)">${D.tree}</g><g transform="translate(22 112) rotate(-8 35 35) scale(.7)">${D.gift}</g><g transform="translate(128 120) rotate(7 30 30) scale(.6)">${D.gift}</g><g transform="translate(150 60) rotate(18 22 22) scale(.45)">${D.cane}</g><g transform="translate(88 138) scale(.42)">${D.bauble}</g>`;

price();
init();
loadMe();

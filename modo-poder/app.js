const $ = (id)=>document.getElementById(id);
const store = {
  get(k,d=null){ try{ const v=localStorage.getItem(k); return v===null?d:JSON.parse(v)}catch{return d}},
  set(k,v){ localStorage.setItem(k,JSON.stringify(v)); }
};

const SUPABASE_URL = "https://pfbzdktlfdotsgfarhel.supabase.co";
const SUPABASE_PUBLISHABLE_KEY = "sb_publishable_nXkBQxBy18WoOH21matfzg_CQdDCvLi";
const sb = window.supabase?.createClient(SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY, {
  auth: { persistSession:true, autoRefreshToken:true, detectSessionInUrl:true }
});

const nowLocal = new Date();
const todayKey = `${nowLocal.getFullYear()}-${String(nowLocal.getMonth()+1).padStart(2,"0")}-${String(nowLocal.getDate()).padStart(2,"0")}`;
const dayKey = (k)=>`${todayKey}:${k}`;
let currentUser = null;
let cloudTimer = null;
let agendaItems = store.get("agenda",[]);
let serviceWorkerRegistration = null;

const habits = [
  "Levantar no horário planejado",
  "Beber água",
  "Fazer higiene",
  "10 minutos de movimento leve",
  "Cumprir a prioridade principal",
  "Fazer uma ação de renda"
];

const powerMessages = [
  ["Você não precisa sentir vontade para começar.","Visualize a tarefa concluída e execute o primeiro passo agora."],
  ["Disciplina é fazer o essencial antes do confortável.","Escolha uma intenção clara e transforme-a em uma ação mensurável."],
  ["Confiança cresce quando você cumpre o que promete a si mesma.","Imagine o resultado desejado, mas concentre-se no comportamento que depende de você."],
  ["Postura forte é calma, clareza e constância.","Defina o que quer, o que fará hoje e como saberá que avançou."],
  ["Poder pessoal começa pelo autocontrole.","Use a visualização para focar, não para substituir trabalho, estudo ou decisões reais."]
];

function setSyncState(text, state=""){
  const badge=$("syncBadge");
  badge.textContent=text;
  badge.dataset.state=state;
}
function queueDailySync(){
  if(!currentUser) return;
  setSyncState("Sincronizando…","busy");
  clearTimeout(cloudTimer);
  cloudTimer=setTimeout(syncDailyPlan,700);
}
function getDailyPayload(){
  return {
    user_id: currentUser?.id,
    plan_date: todayKey,
    priority_1: $("p1").value.trim() || null,
    priority_2: $("p2").value.trim() || null,
    priority_3: $("p3").value.trim() || null,
    priority_1_done: store.get(dayKey("p1done"),false),
    priority_2_done: store.get(dayKey("p2done"),false),
    priority_3_done: store.get(dayKey("p3done"),false),
    income_action: $("incomeAction").value.trim() || null,
    income_action_done: store.get(dayKey("incomeDone"),false),
    distraction_risk: $("distraction").value.trim() || null,
    discipline_rule: $("disciplineRule").value.trim() || null,
    wins: $("wins")?.value?.trim() || null,
    improve_tomorrow: $("improve")?.value?.trim() || null,
    updated_at: new Date().toISOString()
  };
}
async function syncDailyPlan(){
  if(!currentUser || !sb) return;
  const {error}=await sb.from("mp_daily_plans").upsert(getDailyPayload(),{onConflict:"user_id,plan_date"});
  setSyncState(error?"Erro na nuvem":"Nuvem ✓",error?"error":"ok");
  if(error) console.error(error);
}
async function syncHabit(i,label,isDone){
  if(!currentUser || !sb) return;
  setSyncState("Sincronizando…","busy");
  const {error}=await sb.from("mp_habits").upsert({
    user_id:currentUser.id, habit_date:todayKey, habit_key:`habit${i}`, label, is_done:isDone, updated_at:new Date().toISOString()
  },{onConflict:"user_id,habit_date,habit_key"});
  setSyncState(error?"Erro na nuvem":"Nuvem ✓",error?"error":"ok");
}

function loadToday(){
  ["p1","p2","p3","incomeAction","distraction","disciplineRule"].forEach(id=>{
    const el=$(id); const v=store.get(dayKey(id),null);
    if(v!==null) el.value=v;
    el.addEventListener("input",()=>{store.set(dayKey(id),el.value);queueDailySync();});
  });
  ["p1done","p2done","p3done"].forEach(k=>{
    const cb=document.querySelector(`[data-key="${k}"]`);
    cb.checked=store.get(dayKey(k),false);
    cb.addEventListener("change",()=>{store.set(dayKey(k),cb.checked);refreshStats();queueDailySync();});
  });
  renderIncome(store.get(dayKey("incomeDone"),false));
  $("incomeDone").onclick=()=>{
    const done=!store.get(dayKey("incomeDone"),false);
    store.set(dayKey("incomeDone"),done); renderIncome(done); refreshStats(); queueDailySync();
  };
  $("resetPriorities").onclick=()=>{
    ["p1","p2","p3"].forEach(id=>{$(id).value="";store.set(dayKey(id),"")});
    ["p1done","p2done","p3done"].forEach(k=>store.set(dayKey(k),false));
    document.querySelectorAll(".priority-check").forEach(x=>x.checked=false);
    refreshStats(); queueDailySync();
  };
  $("newPower").onclick=randomPower;
  $("autoPlanBtn").onclick=autoPlanToday;
  randomPower();
}
function hydrateDaily(row){
  if(!row) return;
  const map={p1:"priority_1",p2:"priority_2",p3:"priority_3",incomeAction:"income_action",distraction:"distraction_risk",disciplineRule:"discipline_rule"};
  Object.entries(map).forEach(([id,col])=>{ if(row[col]!==null){$(id).value=row[col]||"";store.set(dayKey(id),row[col]||"");} });
  [["p1done","priority_1_done"],["p2done","priority_2_done"],["p3done","priority_3_done"]].forEach(([k,col])=>{
    store.set(dayKey(k),!!row[col]); const cb=document.querySelector(`[data-key="${k}"]`); if(cb) cb.checked=!!row[col];
  });
  store.set(dayKey("incomeDone"),!!row.income_action_done); renderIncome(!!row.income_action_done);
  if(row.wins!==null){store.set(dayKey("wins"),row.wins||"");$("wins").value=row.wins||"";}
  if(row.improve_tomorrow!==null){store.set(dayKey("improve"),row.improve_tomorrow||"");$("improve").value=row.improve_tomorrow||"";}
}
function renderIncome(done){
  $("incomeStatus").textContent=done?"Concluída hoje.":"Ainda não concluída.";
  $("incomeDone").textContent=done?"Desmarcar":"Marcar como concluída";
}

function renderHabits(){
  const wrap=$("habitsList"); wrap.innerHTML="";
  habits.forEach((h,i)=>{
    const key=dayKey(`habit${i}`); const checked=store.get(key,false);
    const row=document.createElement("div"); row.className="habit-row";
    row.innerHTML=`<label><input type="checkbox" ${checked?"checked":""}><span>${h}</span></label>`;
    const cb=row.querySelector("input");
    cb.onchange=()=>{store.set(key,cb.checked);refreshStats();syncHabit(i,h,cb.checked);};
    wrap.appendChild(row);
  });
}

function getGoals(){return store.get("goals",[])}
function setGoals(v){store.set("goals",v);renderGoals();refreshStats();}
async function addGoal(){
  const title=$("goalTitle").value.trim(); if(!title) return;
  const type=$("goalType").value;
  if(currentUser){
    const {data,error}=await sb.from("mp_goals").insert({user_id:currentUser.id,title,goal_type:type}).select().single();
    if(error){alert("Não foi possível salvar a meta na nuvem.");return;}
    setGoals([...getGoals(),{id:data.id,title:data.title,type:data.goal_type,done:data.is_done,cloud:true}]);
  }else{
    setGoals([...getGoals(),{id:Date.now(),title,type,done:false,cloud:false}]);
  }
  $("goalTitle").value="";
}
function renderGoals(){
  const list=$("goalList"); list.innerHTML="";
  const goals=getGoals();
  if(!goals.length){list.innerHTML='<p class="muted">Nenhuma meta cadastrada ainda.</p>';return}
  goals.forEach(g=>{
    const item=document.createElement("div"); item.className="goal-item"+(g.done?" done":"");
    item.innerHTML=`<div><strong class="goal-name">${escapeHtml(g.title)}</strong><div class="small muted">${labelType(g.type)}</div></div><div class="goal-actions"><button class="secondary toggle">${g.done?"↩":"✓"}</button><button class="secondary del">🗑</button></div>`;
    item.querySelector(".toggle").onclick=async()=>{
      const next=!g.done;
      if(currentUser && g.cloud){const {error}=await sb.from("mp_goals").update({is_done:next,updated_at:new Date().toISOString()}).eq("id",g.id);if(error)return;}
      g.done=next; setGoals(goals);
    };
    item.querySelector(".del").onclick=async()=>{
      if(currentUser && g.cloud){const {error}=await sb.from("mp_goals").delete().eq("id",g.id);if(error)return;}
      setGoals(goals.filter(x=>x.id!==g.id));
    };
    list.appendChild(item);
  });
}
function labelType(t){return t==="diaria"?"Diária":t==="semanal"?"Semanal":"Mensal"}
function escapeHtml(s){return String(s).replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[m]))}

function getAgenda(){return agendaItems}
function saveAgendaLocal(){store.set("agenda",agendaItems)}
async function addAgendaItem(){
  const title=$("agendaTitle").value.trim(); const raw=$("agendaStart").value; if(!title||!raw){alert("Preencha o compromisso e o horário.");return;}
  const startsAt=new Date(raw).toISOString(); const lead=Number($("agendaLead").value||10);
  if(currentUser){
    const {data,error}=await sb.from("mp_agenda").insert({user_id:currentUser.id,title,starts_at:startsAt,remind_minutes_before:lead}).select().single();
    if(error){alert("Não foi possível salvar na agenda.");return;}
    agendaItems.push({id:data.id,title:data.title,starts_at:data.starts_at,lead:data.remind_minutes_before,done:data.is_done,cloud:true});
  }else{
    agendaItems.push({id:Date.now(),title,starts_at:startsAt,lead,done:false,cloud:false});
  }
  saveAgendaLocal(); $("agendaTitle").value=""; $("agendaStart").value=""; renderAgenda();
}
function renderAgenda(){
  const list=$("agendaList"); list.innerHTML="";
  const items=[...getAgenda()].sort((a,b)=>new Date(a.starts_at)-new Date(b.starts_at));
  if(!items.length){list.innerHTML='<p class="muted">Nenhum compromisso cadastrado.</p>';return;}
  items.forEach(a=>{
    const item=document.createElement("div"); item.className="goal-item"+(a.done?" done":"");
    const when=new Date(a.starts_at).toLocaleString("pt-BR",{day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"});
    item.innerHTML=`<div><strong class="goal-name">${escapeHtml(a.title)}</strong><div class="small muted">${when} · lembrete ${a.lead} min antes</div></div><div class="goal-actions"><button class="secondary toggle">${a.done?"↩":"✓"}</button><button class="secondary del">🗑</button></div>`;
    item.querySelector(".toggle").onclick=async()=>{
      const next=!a.done; if(currentUser&&a.cloud){const {error}=await sb.from("mp_agenda").update({is_done:next,updated_at:new Date().toISOString()}).eq("id",a.id);if(error)return;}
      a.done=next; saveAgendaLocal(); renderAgenda();
    };
    item.querySelector(".del").onclick=async()=>{
      if(currentUser&&a.cloud){const {error}=await sb.from("mp_agenda").delete().eq("id",a.id);if(error)return;}
      agendaItems=agendaItems.filter(x=>x.id!==a.id);saveAgendaLocal();renderAgenda();
    };
    list.appendChild(item);
  });
}

function refreshStats(){
  const doneP=["p1done","p2done","p3done"].filter(k=>store.get(dayKey(k),false)).length;
  const doneH=habits.filter((_,i)=>store.get(dayKey(`habit${i}`),false)).length;
  const goals=getGoals(); const doneG=goals.filter(g=>g.done).length;
  const income=store.get(dayKey("incomeDone"),false)?1:0;
  const score=Math.round(((doneP+doneH+income)/(3+habits.length+1))*100);
  $("dailyScore").textContent=score+"%"; $("habitScore").textContent=`${doneH}/${habits.length}`;
  $("statPriorities").textContent=`${doneP}/3`; $("statHabits").textContent=`${doneH}/${habits.length}`; $("statGoals").textContent=doneG;
}
function randomPower(){const [m,i]=powerMessages[Math.floor(Math.random()*powerMessages.length)];$("powerMessage").textContent=m;$("powerIntent").textContent=i;}

function autoPlanToday(){
  const goals=getGoals().filter(g=>!g.done).sort((a,b)=>({diaria:0,semanal:1,mensal:2}[a.type]-({diaria:0,semanal:1,mensal:2}[b.type])));
  const inputs=[$("p1"),$("p2"),$("p3")]; let changed=0;
  inputs.forEach((input,i)=>{if(!input.value.trim()&&goals[i]){input.value=goals[i].title;store.set(dayKey(input.id),input.value);changed++;}});
  if(!$("incomeAction").value.trim()){
    $("incomeAction").value="Executar uma ação concreta que possa gerar renda ou oportunidade.";store.set(dayKey("incomeAction"),$("incomeAction").value);changed++;
  }
  if(!$("distraction").value.trim()){$("distraction").value="Trocar de tarefa antes de terminar a prioridade atual.";store.set(dayKey("distraction"),$("distraction").value);}
  if(changed===0) alert("Seu plano já está preenchido. O aplicativo não sobrescreveu suas escolhas.");
  queueDailySync();
}
function analyzeDay(){
  const p=["p1done","p2done","p3done"].filter(k=>store.get(dayKey(k),false)).length;
  const h=habits.filter((_,i)=>store.get(dayKey(`habit${i}`),false)).length;
  const income=store.get(dayKey("incomeDone"),false);
  const openGoals=getGoals().filter(g=>!g.done).length;
  const parts=[];
  if(p>=2) parts.push("Você avançou bem nas prioridades; preserve esse foco amanhã."); else parts.push("Seu principal ganho virá de reduzir trocas de tarefa e concluir pelo menos duas prioridades.");
  if(h>=4) parts.push("Sua base de hábitos está consistente."); else parts.push("Escolha 2 hábitos-base para garantir todos os dias antes de aumentar a cobrança.");
  if(income) parts.push("A ação de renda foi executada; registre o resultado para saber o que realmente funciona."); else parts.push("Ainda falta uma ação de renda: escolha algo curto, concreto e mensurável.");
  if(openGoals>5) parts.push("Há muitas metas abertas; considere priorizar as que têm maior impacto agora.");
  const risk=$("distraction").value.trim(); if(risk) parts.push(`Risco declarado hoje: ${risk}. Use sua regra de disciplina antes de mudar de tarefa.`);
  $("coachOutput").innerHTML=parts.map(x=>`<p>${escapeHtml(x)}</p>`).join("");
}

function nav(){
  document.querySelectorAll(".nav-btn").forEach(btn=>{btn.onclick=()=>{document.querySelectorAll(".nav-btn").forEach(b=>b.classList.remove("active"));document.querySelectorAll(".page").forEach(p=>p.classList.remove("active"));btn.classList.add("active");$(btn.dataset.page).classList.add("active");window.scrollTo({top:0,behavior:"smooth"});}});
}

function config(){
  const cfg=store.get("config",{name:"",monthlyMoney:"",powerTime:"05:00"});
  $("userName").value=cfg.name||""; $("monthlyMoney").value=cfg.monthlyMoney||""; $("powerTime").value=cfg.powerTime||"05:00";
  if(cfg.name) $("saudacao").textContent=`${cfg.name}, seu dia começa com direção.`;
  $("saveConfig").onclick=async()=>{
    const c={name:$("userName").value.trim(),monthlyMoney:$("monthlyMoney").value,powerTime:$("powerTime").value}; store.set("config",c);
    $("saudacao").textContent=c.name?`${c.name}, seu dia começa com direção.`:"Seu dia começa com direção.";
    if(currentUser){
      const {error}=await sb.from("mp_profiles").upsert({user_id:currentUser.id,display_name:c.name||null,monthly_income_goal:c.monthlyMoney?Number(c.monthlyMoney):null,power_time:c.powerTime||"05:00",updated_at:new Date().toISOString()});
      setSyncState(error?"Erro na nuvem":"Nuvem ✓",error?"error":"ok");
    }
    alert("Configurações salvas.");
  };
}
function review(){
  $("wins").value=store.get(dayKey("wins"),""); $("improve").value=store.get(dayKey("improve"),"");
  $("saveReview").onclick=()=>{store.set(dayKey("wins"),$("wins").value);store.set(dayKey("improve"),$("improve").value);$("reviewSaved").textContent=currentUser?"Revisão salva e enviada para a nuvem.":"Revisão salva neste aparelho.";queueDailySync();};
}

async function enableNotifications(){
  if(!("Notification" in window)){alert("Este navegador não oferece notificações.");return;}
  const p=await Notification.requestPermission();
  if(p==="granted") await showSystemNotification("Modo Poder ⚡","Notificações ativadas. Seus lembretes da agenda poderão aparecer no aparelho.");
  else alert("Permissão de notificação não concedida.");
}
async function showSystemNotification(title,body){
  try{
    if(serviceWorkerRegistration) return serviceWorkerRegistration.showNotification(title,{body,icon:"icon.svg",badge:"icon.svg"});
    if(Notification.permission==="granted") new Notification(title,{body});
  }catch(e){console.error(e);}
}
function checkAgendaReminders(){
  if(!("Notification" in window)||Notification.permission!=="granted") return;
  const now=Date.now();
  getAgenda().filter(a=>!a.done).forEach(a=>{
    const start=new Date(a.starts_at).getTime(); const trigger=start-(Number(a.lead)||0)*60000;
    const key=`agendaNotified:${a.id}:${a.starts_at}`;
    if(now>=trigger && now<=start+5*60000 && !store.get(key,false)){
      store.set(key,true); showSystemNotification("Modo Poder · Agenda",`${a.title} — ${new Date(a.starts_at).toLocaleTimeString("pt-BR",{hour:"2-digit",minute:"2-digit"})}`);
    }
  });
}

function openAuth(){ $("authModal").classList.remove("hidden"); $("authMessage").textContent=""; }
function closeAuth(){ $("authModal").classList.add("hidden"); }
async function sendMagicLink(){
  const email=$("authEmail").value.trim(); if(!email){$("authMessage").textContent="Digite seu e-mail.";return;}
  $("authMessage").textContent="Enviando…";
  const redirectTo=window.location.origin+window.location.pathname;
  const {error}=await sb.auth.signInWithOtp({email,options:{emailRedirectTo:redirectTo}});
  $("authMessage").textContent=error?`Erro: ${error.message}`:"Link enviado. Abra seu e-mail e toque no link para entrar.";
}
function updateAccountUI(){
  if(currentUser){
    $("authBtn").textContent="Sair"; $("accountAction").textContent="Sair da conta"; $("accountText").textContent=`Conectado como ${currentUser.email||"usuário"}. Seus dados podem ser sincronizados entre aparelhos.`; setSyncState("Nuvem ✓","ok");
  }else{
    $("authBtn").textContent="Entrar"; $("accountAction").textContent="Entrar e sincronizar"; $("accountText").textContent="Você está usando apenas este aparelho."; setSyncState("Local","");
  }
}
async function accountAction(){
  if(currentUser){await sb.auth.signOut();currentUser=null;updateAccountUI();}
  else openAuth();
}
async function loadCloudData(){
  if(!currentUser) return;
  setSyncState("Sincronizando…","busy");
  const [{data:profile},{data:daily},{data:cloudHabits},{data:cloudGoals},{data:cloudAgenda}] = await Promise.all([
    sb.from("mp_profiles").select("*").eq("user_id",currentUser.id).maybeSingle(),
    sb.from("mp_daily_plans").select("*").eq("plan_date",todayKey).maybeSingle(),
    sb.from("mp_habits").select("*").eq("habit_date",todayKey),
    sb.from("mp_goals").select("*").order("created_at",{ascending:true}),
    sb.from("mp_agenda").select("*").order("starts_at",{ascending:true})
  ]);

  if(profile){
    const cfg={name:profile.display_name||"",monthlyMoney:profile.monthly_income_goal??"",powerTime:(profile.power_time||"05:00").slice(0,5)};store.set("config",cfg);$("userName").value=cfg.name;$("monthlyMoney").value=cfg.monthlyMoney;$("powerTime").value=cfg.powerTime;if(cfg.name)$("saudacao").textContent=`${cfg.name}, seu dia começa com direção.`;
  }
  if(daily) hydrateDaily(daily); else await syncDailyPlan();

  if(cloudHabits?.length){cloudHabits.forEach(h=>store.set(dayKey(h.habit_key),!!h.is_done));}
  else {for(let i=0;i<habits.length;i++) if(store.get(dayKey(`habit${i}`),false)) await syncHabit(i,habits[i],true);}

  if(cloudGoals?.length){setGoals(cloudGoals.map(g=>({id:g.id,title:g.title,type:g.goal_type,done:g.is_done,cloud:true})));}
  else {
    const local=getGoals();
    if(local.length){const {data}=await sb.from("mp_goals").insert(local.map(g=>({user_id:currentUser.id,title:g.title,goal_type:g.type,is_done:!!g.done}))).select();if(data)setGoals(data.map(g=>({id:g.id,title:g.title,type:g.goal_type,done:g.is_done,cloud:true})));}
  }

  if(cloudAgenda?.length){agendaItems=cloudAgenda.map(a=>({id:a.id,title:a.title,starts_at:a.starts_at,lead:a.remind_minutes_before,done:a.is_done,cloud:true}));saveAgendaLocal();}
  else if(agendaItems.length){const {data}=await sb.from("mp_agenda").insert(agendaItems.map(a=>({user_id:currentUser.id,title:a.title,starts_at:a.starts_at,remind_minutes_before:a.lead||10,is_done:!!a.done}))).select();if(data){agendaItems=data.map(a=>({id:a.id,title:a.title,starts_at:a.starts_at,lead:a.remind_minutes_before,done:a.is_done,cloud:true}));saveAgendaLocal();}}

  renderHabits();renderGoals();renderAgenda();refreshStats();setSyncState("Nuvem ✓","ok");
}
async function bootstrapAuth(){
  if(!sb){setSyncState("Local","");return;}
  const {data:{session}}=await sb.auth.getSession(); currentUser=session?.user||null; updateAccountUI(); if(currentUser) await loadCloudData();
  sb.auth.onAuthStateChange(async(_event,session)=>{const previous=currentUser?.id;currentUser=session?.user||null;updateAccountUI();if(currentUser&&currentUser.id!==previous){closeAuth();await loadCloudData();}});
}

$("addGoal").onclick=addGoal; $("addAgenda").onclick=addAgendaItem; $("coachBtn").onclick=analyzeDay; $("notifyBtn").onclick=enableNotifications;
$("authBtn").onclick=accountAction; $("accountAction").onclick=accountAction; $("closeAuth").onclick=closeAuth; $("sendMagicLink").onclick=sendMagicLink;
$("authModal").addEventListener("click",e=>{if(e.target===$("authModal"))closeAuth();});

let deferredPrompt;
window.addEventListener("beforeinstallprompt",e=>{e.preventDefault();deferredPrompt=e;$("installBtn").classList.remove("hidden");});
$("installBtn").onclick=async()=>{if(!deferredPrompt)return;deferredPrompt.prompt();await deferredPrompt.userChoice;deferredPrompt=null;$("installBtn").classList.add("hidden");};
if("serviceWorker" in navigator){window.addEventListener("load",async()=>{serviceWorkerRegistration=await navigator.serviceWorker.register("sw.js");});}

loadToday();renderHabits();renderGoals();renderAgenda();refreshStats();nav();config();review();bootstrapAuth();
setInterval(checkAgendaReminders,30000);document.addEventListener("visibilitychange",()=>{if(!document.hidden)checkAgendaReminders();});

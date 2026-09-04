const $ = (id)=>document.getElementById(id);
const store = {
  get(k,d=null){ try{ const v=localStorage.getItem(k); return v===null?d:JSON.parse(v)}catch{return d}},
  set(k,v){ localStorage.setItem(k,JSON.stringify(v)); }
};
const todayKey = new Date().toISOString().slice(0,10);

function dayKey(k){ return `${todayKey}:${k}`; }

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

function loadToday(){
  ["p1","p2","p3","incomeAction","distraction","disciplineRule"].forEach(id=>{
    const el=$(id); const v=store.get(dayKey(id),null);
    if(v!==null) el.value=v;
    el.addEventListener("input",()=>store.set(dayKey(id),el.value));
  });
  ["p1done","p2done","p3done"].forEach((k)=>{
    const cb=document.querySelector(`[data-key="${k}"]`);
    cb.checked=store.get(dayKey(k),false);
    cb.addEventListener("change",()=>{store.set(dayKey(k),cb.checked);refreshStats();});
  });
  const incomeDone=store.get(dayKey("incomeDone"),false);
  renderIncome(incomeDone);

  $("incomeDone").onclick=()=>{
    const now=!store.get(dayKey("incomeDone"),false);
    store.set(dayKey("incomeDone"),now); renderIncome(now); refreshStats();
  };
  $("resetPriorities").onclick=()=>{
    ["p1","p2","p3"].forEach(id=>{$(id).value="";store.set(dayKey(id),"")});
    ["p1done","p2done","p3done"].forEach(k=>store.set(dayKey(k),false));
    document.querySelectorAll(".priority-check").forEach(x=>x.checked=false);
    refreshStats();
  };
  $("newPower").onclick=randomPower;
  randomPower();
}
function renderIncome(done){
  $("incomeStatus").textContent=done?"Concluída hoje.":"Ainda não concluída.";
  $("incomeDone").textContent=done?"Desmarcar":"Marcar como concluída";
}

function renderHabits(){
  const wrap=$("habitsList"); wrap.innerHTML="";
  habits.forEach((h,i)=>{
    const key=dayKey(`habit${i}`);
    const checked=store.get(key,false);
    const row=document.createElement("div"); row.className="habit-row";
    row.innerHTML=`<label><input type="checkbox" ${checked?"checked":""}><span>${h}</span></label>`;
    const cb=row.querySelector("input");
    cb.onchange=()=>{store.set(key,cb.checked);refreshStats();};
    wrap.appendChild(row);
  });
}

function getGoals(){return store.get("goals",[])}
function setGoals(v){store.set("goals",v);renderGoals();refreshStats();}
function renderGoals(){
  const list=$("goalList"); list.innerHTML="";
  const goals=getGoals();
  if(!goals.length){list.innerHTML='<p class="muted">Nenhuma meta cadastrada ainda.</p>';return}
  goals.forEach(g=>{
    const item=document.createElement("div"); item.className="goal-item"+(g.done?" done":"");
    item.innerHTML=`
      <div><strong class="goal-name">${escapeHtml(g.title)}</strong><div class="small muted">${labelType(g.type)}</div></div>
      <div class="goal-actions">
        <button class="secondary toggle">${g.done?"↩":"✓"}</button>
        <button class="secondary del">🗑</button>
      </div>`;
    item.querySelector(".toggle").onclick=()=>{g.done=!g.done;setGoals(goals)};
    item.querySelector(".del").onclick=()=>setGoals(goals.filter(x=>x.id!==g.id));
    list.appendChild(item);
  })
}
function labelType(t){return t==="diaria"?"Diária":t==="semanal"?"Semanal":"Mensal"}
function escapeHtml(s){return String(s).replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[m]))}

function refreshStats(){
  const doneP=["p1done","p2done","p3done"].filter(k=>store.get(dayKey(k),false)).length;
  const doneH=habits.filter((_,i)=>store.get(dayKey(`habit${i}`),false)).length;
  const goals=getGoals(); const doneG=goals.filter(g=>g.done).length;
  const income=store.get(dayKey("incomeDone"),false)?1:0;
  const score=Math.round(((doneP+doneH+income)/(3+habits.length+1))*100);

  $("dailyScore").textContent=score+"%";
  $("habitScore").textContent=`${doneH}/${habits.length}`;
  $("statPriorities").textContent=`${doneP}/3`;
  $("statHabits").textContent=`${doneH}/${habits.length}`;
  $("statGoals").textContent=doneG;
}

function randomPower(){
  const [m,i]=powerMessages[Math.floor(Math.random()*powerMessages.length)];
  $("powerMessage").textContent=m; $("powerIntent").textContent=i;
}

function nav(){
  document.querySelectorAll(".nav-btn").forEach(btn=>{
    btn.onclick=()=>{
      document.querySelectorAll(".nav-btn").forEach(b=>b.classList.remove("active"));
      document.querySelectorAll(".page").forEach(p=>p.classList.remove("active"));
      btn.classList.add("active"); $(btn.dataset.page).classList.add("active");
      window.scrollTo({top:0,behavior:"smooth"});
    }
  })
}

function config(){
  const cfg=store.get("config",{name:"",monthlyMoney:"",powerTime:"05:00"});
  $("userName").value=cfg.name||"";
  $("monthlyMoney").value=cfg.monthlyMoney||"";
  $("powerTime").value=cfg.powerTime||"05:00";
  if(cfg.name) $("saudacao").textContent=`${cfg.name}, seu dia começa com direção.`;
  $("saveConfig").onclick=()=>{
    const c={name:$("userName").value.trim(),monthlyMoney:$("monthlyMoney").value,powerTime:$("powerTime").value};
    store.set("config",c);
    $("saudacao").textContent=c.name?`${c.name}, seu dia começa com direção.`:"Seu dia começa com direção.";
    alert("Configurações salvas.");
  }
}

function review(){
  $("wins").value=store.get(dayKey("wins"),"");
  $("improve").value=store.get(dayKey("improve"),"");
  $("saveReview").onclick=()=>{
    store.set(dayKey("wins"),$("wins").value);
    store.set(dayKey("improve"),$("improve").value);
    $("reviewSaved").textContent="Revisão salva neste aparelho.";
  }
}

$("addGoal").onclick=()=>{
  const title=$("goalTitle").value.trim(); if(!title) return;
  const goals=getGoals();
  goals.push({id:Date.now(),title,type:$("goalType").value,done:false});
  setGoals(goals); $("goalTitle").value="";
};

async function enableNotifications(){
  if(!("Notification" in window)){ alert("Este navegador não oferece notificações."); return; }
  const p=await Notification.requestPermission();
  if(p==="granted"){
    new Notification("Modo Poder ⚡",{body:"Notificações ativadas. Seu foco continua nas ações reais do dia."});
  }else{
    alert("Permissão de notificação não concedida.");
  }
}
$("notifyBtn").onclick=enableNotifications;

let deferredPrompt;
window.addEventListener("beforeinstallprompt",(e)=>{
  e.preventDefault(); deferredPrompt=e; $("installBtn").classList.remove("hidden");
});
$("installBtn").onclick=async()=>{
  if(!deferredPrompt) return;
  deferredPrompt.prompt(); await deferredPrompt.userChoice; deferredPrompt=null; $("installBtn").classList.add("hidden");
};

if("serviceWorker" in navigator){
  window.addEventListener("load",()=>navigator.serviceWorker.register("sw.js"));
}

loadToday();
renderHabits();
renderGoals();
refreshStats();
nav();
config();
review();

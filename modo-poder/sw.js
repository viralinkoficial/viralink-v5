const CACHE="modo-poder-v6";
const ASSETS=["./","./index.html","./styles.css","./app.js","./push.js","./manifest.json","./icon.svg"];
self.addEventListener("install",e=>{self.skipWaiting();e.waitUntil(caches.open(CACHE).then(c=>c.addAll(ASSETS)))});
self.addEventListener("activate",e=>e.waitUntil(Promise.all([caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k)))),self.clients.claim()])));
self.addEventListener("fetch",e=>{if(e.request.method!=="GET")return;e.respondWith(caches.match(e.request).then(r=>r||fetch(e.request).then(res=>{if(new URL(e.request.url).origin===self.location.origin){const copy=res.clone();caches.open(CACHE).then(c=>c.put(e.request,copy))}return res}).catch(()=>caches.match("./index.html"))))});

self.addEventListener("push",event=>{
  let payload={title:"Modo Poder ⚡",body:"Você tem um lembrete.",url:"./"};
  try{if(event.data)payload={...payload,...event.data.json()}}catch{if(event.data)payload.body=event.data.text()}
  event.waitUntil(self.registration.showNotification(payload.title,{
    body:payload.body,
    icon:"./icon.svg",
    badge:"./icon.svg",
    tag:payload.tag||"modo-poder-reminder",
    renotify:true,
    data:{url:payload.url||"./"}
  }));
});
self.addEventListener("notificationclick",event=>{
  event.notification.close();
  const target=new URL(event.notification.data?.url||"./",self.location.origin).href;
  event.waitUntil(self.clients.matchAll({type:"window",includeUncontrolled:true}).then(list=>{
    for(const client of list){if("focus" in client){client.navigate(target);return client.focus()}}
    if(self.clients.openWindow)return self.clients.openWindow(target);
  }));
});

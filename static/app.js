const $=id=>document.getElementById(id);
let liveCoordinates = null;
let liveLocationLabel = "Your live GPS location";
function locationQuery(){
  if(liveCoordinates) return `lat=${encodeURIComponent(liveCoordinates.latitude)}&lon=${encodeURIComponent(liveCoordinates.longitude)}&label=${encodeURIComponent(liveLocationLabel)}`;
  return `city=${encodeURIComponent($("city").value)}`;
}
function useMyLocation(){
  if(!navigator.geolocation){
    $("weather-status").textContent="Your browser does not support location access.";
    return;
  }
  $("weather-status").textContent="Requesting location permission…";
  navigator.geolocation.getCurrentPosition(async pos=>{
    liveCoordinates={latitude:pos.coords.latitude,longitude:pos.coords.longitude};
    liveLocationLabel="Your live GPS location";
    $("precise-location").textContent=`GPS: ${liveCoordinates.latitude.toFixed(5)}, ${liveCoordinates.longitude.toFixed(5)} · Resolving address…`;
    try {
      const rr=await fetch(`/api/reverse-geocode?lat=${liveCoordinates.latitude}&lon=${liveCoordinates.longitude}`);
      const rd=await rr.json();
      if(rr.ok && rd.address){
        liveLocationLabel=rd.address;
        $("precise-location").textContent=`${rd.address} · GPS ${liveCoordinates.latitude.toFixed(5)}, ${liveCoordinates.longitude.toFixed(5)} · ${rd.source}`;
      } else {
        $("precise-location").textContent=`GPS ${liveCoordinates.latitude.toFixed(5)}, ${liveCoordinates.longitude.toFixed(5)} · Address lookup unavailable`;
      }
    } catch(e) {
      $("precise-location").textContent=`GPS ${liveCoordinates.latitude.toFixed(5)}, ${liveCoordinates.longitude.toFixed(5)}`;
    }
    $("weather-status").textContent="Location found. Loading nearby weather and air quality…";
    await loadAll();
  },err=>{
    const messages={1:"Location permission denied. Allow location access in your browser, or search by city.",2:"Your location could not be determined. Try again or search by city.",3:"Location request timed out. Try again."};
    $("weather-status").textContent=messages[err.code]||"Location unavailable. You can search by city.";
  },{enableHighAccuracy:true,timeout:15000,maximumAge:300000});
}
async function loadAll(){await loadWeather();await loadLiveAir();await loadNearestStation();await loadAirStatus();await loadHistory()}


async function loadNearestStation(){
  const status=$("station-status");
  const details=$("station-details");
  if(!liveCoordinates){
    status.textContent="Click Use my live location to search for physical monitoring stations near your GPS coordinates.";
    details.classList.add("hidden"); return;
  }
  status.textContent="Searching for the nearest OpenAQ monitoring station within 25 km…";
  try{
    const r=await fetch(`/api/nearest-station?lat=${liveCoordinates.latitude}&lon=${liveCoordinates.longitude}`);
    const d=await r.json();
    if(d.status==="key_required"){
      status.textContent=d.message+" GPS and modelled AQI continue working. Configure the key in .env and restart Flask.";
      details.classList.add("hidden"); return;
    }
    if(d.status!=="available"){
      status.textContent=d.message||"No station data available.";
      details.classList.add("hidden"); return;
    }
    details.classList.remove("hidden");
    $("station-name").textContent=d.station.name||"Monitoring station";
    const km=(Number(d.station.distance_m||0)/1000).toFixed(2);
    $("station-distance").textContent=`${d.station.city||""} · ${km} km from your GPS location · Station last update: ${d.station.last_updated?.local||d.station.last_updated?.utc||"not supplied"}`;
    $("station-readings").innerHTML=d.readings.length?d.readings.map(x=>`<div class="pollutant"><span>${x.parameter}</span><b>${x.value??"—"}</b><span>${x.unit||""} · ${x.datetime||"time unavailable"}</span></div>`).join(""):"<p>No latest sensor values returned by this station.</p>";
    $("station-note").textContent=d.note+" Source: "+d.source;
    status.textContent="● Nearest station found";
  }catch(e){status.textContent="Station lookup unavailable: "+e.message;details.classList.add("hidden")}
}

async function loadLiveAir(){
  $("air-live-status").textContent="Fetching air-quality model…";
  try{
    const r=await fetch("/api/air-quality-live?"+locationQuery());
    const d=await r.json(); if(!r.ok) throw Error(d.error||"Air-quality data unavailable");
    $("live-aqi").textContent=d.aqi;
    $("live-category").textContent=d.category;
    $("live-category").className="aqi-category "+d.category_class;
    $("live-source").textContent=`${d.city}, ${d.country||""} · Model timestamp: ${d.timestamp||"not supplied"} · ${d.aqi_scale}`;
    $("pollutant-grid").innerHTML=Object.entries(d.pollutants).map(([k,v])=>`<div class="pollutant"><span>${k}</span><b>${v===null||v===undefined?"—":Number(v).toFixed(1)}</b><span>µg/m³</span></div>`).join("");
    $("health-advice").innerHTML=d.advice.map(x=>`<li>${x}</li>`).join("");
    $("manage-advice").innerHTML=d.manage.map(x=>`<li>${x}</li>`).join("");
    $("air-limitations").textContent=d.limitations+" Source: "+d.source+". Model-grid estimates can differ from local monitoring stations.";
    $("air-live-status").textContent="● Data available · "+new Date().toLocaleTimeString();
  }catch(e){
    $("air-live-status").textContent="Unavailable";
    $("live-aqi").textContent="—"; $("live-category").textContent="No current data";
    $("live-source").textContent=e.message+" Please retry; no readings are fabricated.";
    $("health-advice").innerHTML="<li>Precautions will appear when a valid air-quality result is available.</li>";
    $("manage-advice").innerHTML="<li>Check your local official air-quality authority for current conditions.</li>";
  }
}

async function loadWeather(){
  $("weather-status").textContent="Fetching live weather…";
  try{
    const r=await fetch("/api/weather?"+locationQuery());
    const d=await r.json();if(!r.ok)throw Error(d.error||"Weather unavailable");
    const c=d.current;
    $("temp").textContent=c.temperature_2m??"—";
    $("humidity").textContent=(c.relative_humidity_2m??"—")+"%";
    $("wind").textContent=c.wind_speed_10m??"—";
    $("rain").textContent=c.precipitation??"—";
    $("weather-status").textContent="● Live · "+d.city+" · "+new Date(d.updated_at).toLocaleTimeString();
  }catch(e){$("weather-status").textContent="Weather unavailable: "+e.message}
}
async function loadAirStatus(){
 try{const r=await fetch("/api/air-quality?city="+encodeURIComponent($("city").value));const d=await r.json();
 $("aq-status").textContent=d.status==="unavailable"?"Live OpenAQ readings are currently unavailable. "+d.message:(d.message||"OpenAQ connected.");
 }catch(e){$("aq-status").textContent="OpenAQ status unavailable."}
}
async function predict(){
 const body={city:$("city").value,pm25:$("pm25").value,pm10:$("pm10").value,no2:$("no2").value,o3:$("o3").value};
 const r=await fetch("/api/predict",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
 const d=await r.json();const box=$("result");box.classList.remove("hidden");
 if(!r.ok){box.textContent=d.error||"Could not calculate.";return}
 box.innerHTML=`<div class="eyebrow">INDICATIVE AQI · NOT A LIVE STATION READING</div><strong>${d.aqi}</strong> &nbsp; ${d.category}<p>${d.advisory}</p><small>Model note: ${d.model_status}</small>`;
 loadHistory();
}
async function loadHistory(){
 const r=await fetch("/api/history");const rows=await r.json();
 $("history-body").innerHTML=rows.length?rows.map(x=>`<tr><td>${new Date(x.created_at).toLocaleString()}</td><td>${x.city}</td><td>${x.aqi}</td><td>${x.category}</td></tr>`).join(""):'<tr><td colspan="4">No scenarios saved yet.</td></tr>';
}
$("city").addEventListener("input",()=>{liveCoordinates=null;liveLocationLabel="Your live GPS location";$("precise-location").textContent="City search: "+$("city").value;});
loadAll();setInterval(loadWeather,600000);setInterval(loadLiveAir,600000);


// AirWatch interactive guardian and command-center controls.
const guardianTips = [
  "Personal protocol: check the latest AQI before outdoor exercise. When air quality is unhealthy, reduce intense outdoor activity and follow local health guidance.",
  "Indoor protocol: keep outdoor smoke and dust out when pollution is high. A properly sized HEPA air cleaner can reduce indoor particles.",
  "Community protocol: never burn waste, avoid unnecessary vehicle idling, and choose public transport, walking or cycling when conditions allow."
];
function showToast(message){
  const el=$("toast"); if(!el) return;
  el.textContent=message; el.classList.add("show");
  clearTimeout(window.__airwatchToastTimer);
  window.__airwatchToastTimer=setTimeout(()=>el.classList.remove("show"),2800);
}
function toggleGuardian(){
  const widget=$("guardian-widget");
  widget.classList.toggle("open");
  if(widget.classList.contains("open")){
    const hour=new Date().getHours();
    const greeting=hour<12?"Good morning":hour<17?"Good afternoon":"Good evening";
    $("guardian-message").textContent=`${greeting!==" "?greeting+", ":""}I'm Aero, your AirWatch guardian. Tap a field-guide protocol below or run a fresh scan.`;
  }
}
function showGuardianTip(index){
  $("guardian-widget").classList.add("open");
  $("guardian-message").textContent=guardianTips[index] || guardianTips[0];
  showToast("AERO // FIELD GUIDE UPDATED");
}
const originalLoadAll=loadAll;
loadAll=async function(){
  showToast("AIRWATCH // SCANNING ENVIRONMENT DATA");
  await originalLoadAll();
};
$("city").addEventListener("keydown",event=>{
  if(event.key==="Enter"){
    liveCoordinates=null;
    liveLocationLabel="Your live GPS location";
    $("precise-location").textContent="City search: "+$("city").value;
    loadAll();
  }
});
// Highlight the active section as the user scrolls.
if("IntersectionObserver" in window){
  const sections=[...document.querySelectorAll("main section[id]")];
  const navLinks=[...document.querySelectorAll("nav a[href^='#']")];
  const observer=new IntersectionObserver(entries=>{
    entries.forEach(entry=>{
      if(entry.isIntersecting){
        navLinks.forEach(a=>a.classList.toggle("active",a.getAttribute("href")==="#"+entry.target.id));
      }
    });
  },{rootMargin:"-25% 0px -65% 0px"});
  sections.forEach(section=>observer.observe(section));
}


// ChatGPT-connected Aero (or local AQI-aware fallback when no OpenAI key is set).
function toggleGuardian(){
  const widget=$("guardian-widget");
  widget.classList.toggle("open");
  if(widget.classList.contains("open")) setTimeout(()=>$("aero-input")?.focus(),120);
}
function appendAeroBubble(text,who="aero"){
  const body=$("aero-chat-body");
  const bubble=document.createElement("div");
  bubble.className="chat-bubble "+(who==="user"?"user-bubble":"aero-bubble");
  bubble.textContent=text;
  body.appendChild(bubble);
  body.scrollTop=body.scrollHeight;
  return bubble;
}
function askAeroPrompt(text){
  $("aero-input").value=text;
  $("aero-input").focus();
}
let aeroRequestInFlight = false;
async function sendAeroMessage(event){
  event?.preventDefault();
  if(aeroRequestInFlight) return;
  const input=$("aero-input");
  const message=input.value.trim();
  if(!message) return;
  aeroRequestInFlight=true;
  input.value="";
  appendAeroBubble(message,"user");
  const pending=appendAeroBubble("Aero is checking the latest AQI context…","aero");
  $("aero-send").disabled=true;
  input.disabled=true;
  const controller=new AbortController();
  const requestTimer=setTimeout(()=>controller.abort(),45000);
  try{
    const context={
      aqi:$("live-aqi")?.textContent && $("live-aqi").textContent!=="—" ? $("live-aqi").textContent : null,
      category:$("live-category")?.textContent || "not available",
      location:$("precise-location")?.textContent || $("city")?.value || "selected location"
    };
    const r=await fetch("/api/assistant",{
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({message,context}),
      signal:controller.signal
    });
    const d=await r.json();
    pending.textContent=(r.ok && d.answer)?d.answer:(d.error||"I couldn't connect just now. Please try again.");
    $("aero-mode").textContent=d.mode ? `${d.mode} · AQI-aware context` : "Aero assistant · retry available";
  }catch(err){
    pending.textContent=err.name==="AbortError"
      ?"Aero took longer than 45 seconds. Please retry; local AQI precautions remain available."
      :"I couldn't reach the assistant service. Please check your connection and try again.";
    $("aero-mode").textContent="Aero · connection issue";
  }finally{
    clearTimeout(requestTimer);
    aeroRequestInFlight=false;
    $("aero-send").disabled=false;
    input.disabled=false;
    $("aero-chat-body").scrollTop=$("aero-chat-body").scrollHeight;
    input.focus();
  }
}

// Field-guide cards can open Aero with a relevant precaution.
function showGuardianTip(index){
  const tips=[
    "Personal protocol: check the latest AQI before outdoor exercise. If air quality is unhealthy, reduce intense outdoor activity and follow local public-health guidance.",
    "Indoor protocol: keep outdoor smoke and dust out during pollution peaks. A properly sized HEPA air cleaner can reduce indoor particles.",
    "Community protocol: avoid waste burning and vehicle idling; choose shared or public transport when practical."
  ];
  const widget=$("guardian-widget");
  if(!widget.classList.contains("open")) widget.classList.add("open");
  appendAeroBubble(tips[index]||tips[0],"aero");
}

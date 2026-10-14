"use strict";
const $=id=>document.getElementById(id);
const colors={SVR:"#367cb5",TOR:"#c15d62",FFW:"#8666af",early:"#008b88",late:"#d69e41"};
const labels={documented_by_expiration:"By expiration",first_documented_after_expiration:"First after expiration",no_candidate_lsr:"No candidate found",needs_review:"Needs review"};
const fmt=x=>x===null||x===undefined?"—":Number(x).toLocaleString("en-US");
const esc=x=>String(x??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const time=x=>x?new Date(x).toLocaleString("en-US",{timeZone:"America/Chicago",month:"short",day:"numeric",hour:"numeric",minute:"2-digit"}):"Unknown";
const minutes=x=>x==null?"—":Math.abs(x)<60?Math.round(x)+" min":(x/60).toFixed(1)+" hr";
const stamp=x=>x?new Date(x).valueOf():NaN;
let d,selected,filtered=[],page=0,map,polygonLayer,reportLayer;
function metric(name,num,definition){return '<article class="metric"><div class="metric-label" title="'+esc(definition)+'">'+esc(name)+' ⓘ</div><strong>'+esc(num)+'</strong><small>'+esc(definition)+'</small></article>'}
function metrics(){
 const o=d.overview;
 $("metrics").innerHTML=[
 metric("Warnings analyzed",fmt(o.warnings),"Distinct WFO LIX SVR, TOR and FFW warning events issued in 2025."),
 metric("Candidate documented",fmt(o.documented),"Warnings with a strictly screened candidate LSR and usable source-product timestamp."),
 metric("First documented late",fmt(o.late_first),"First linked candidate product time is after warning expiration."),
 metric("No candidate found",fmt(o.not_matched),"No compatible source LSR identified, not an official unverified count."),
 metric("Median publication lag",minutes(o.median_delay_minutes),"Median event-to-product proxy minutes, unique matched candidate LSRs."),
 metric("Late share",o.late_percent_of_documented==null?"—":o.late_percent_of_documented+"%","First-late warnings / all warnings with timestamped candidate LSRs.")
 ].join("");
}
const layout=(x={})=>({font:{family:"DM Sans",size:11,color:"#607484"},margin:{l:48,r:12,t:12,b:45},paper_bgcolor:"rgba(0,0,0,0)",plot_bgcolor:"rgba(0,0,0,0)",showlegend:false,...x});
const cfg={responsive:true,displaylogo:false,toImageButtonOptions:{format:"svg",filename:"lix-2025-analysis",scale:2}};
function chart(id,traces,settings={}){if(window.Plotly)Plotly.newPlot(id,traces,layout(settings),cfg);else $(id).textContent="Interactive charts need the Plotly library."}
function charts(){
 const states=["documented_by_expiration","first_documented_after_expiration","needs_review","no_candidate_lsr"];
 chart("statusChart",[{type:"pie",hole:.58,labels:states.map(s=>labels[s]),values:states.map(s=>d.warnings.filter(w=>w.classification===s).length),marker:{colors:[colors.early,colors.late,"#c57d99","#9baab5"]}}],{margin:{l:5,r:5,t:5,b:5},showlegend:true,legend:{orientation:"h",y:-.13,font:{size:10}}});
 const win=[0,1,3,6,12,24,48],total=d.overview.warnings;
 const nums=win.map(h=>h===0?d.warnings.filter(w=>w.classification==="documented_by_expiration").length:d.overview.windows[h]);
 chart("windowChart",[{type:"bar",x:win.map(h=>h?"+"+h+"h":"Expiry"),y:nums.map(n=>total?100*n/total:0),customdata:nums,marker:{color:"#238f9d"},hovertemplate:"%{x}: %{y:.1f}% (%{customdata} warnings)<extra></extra>"}],{yaxis:{title:"% of all warnings",range:[0,100]}});
 const idset=new Set(d.associations.filter(a=>a.eligibility==="candidate").map(a=>a.report_id));
 const rs=d.reports.filter(r=>idset.has(r.id)&&Number.isFinite(r.delay_minutes)&&r.delay_minutes>=0);
 const edges=[0,30,60,180,360,720,1440,2880,Infinity],bins=["0–30m","30–60m","1–3h","3–6h","6–12h","12–24h","24–48h",">48h"];
 chart("delayChart",[{type:"bar",x:bins,y:bins.map((_,i)=>rs.filter(r=>r.delay_minutes>=edges[i]&&r.delay_minutes<edges[i+1]).length),marker:{color:"#3c8eac"}}],{yaxis:{title:"Unique candidate reports"},xaxis:{tickangle:-20}});
 const x=[0,.5,1,3,6,12,24,48,72];
 chart("cumulativeChart",[{type:"scatter",mode:"lines+markers",x,y:x.map(h=>rs.length?100*rs.filter(r=>r.delay_minutes<=h*60).length/rs.length:0),line:{color:colors.early,width:3,shape:"hv"},marker:{size:6}}],{xaxis:{title:"Hours after occurrence"},yaxis:{title:"% of candidate reports",range:[0,100]}});
 const wlookup=new Map(d.warnings.map(w=>[w.id,w.type])),rlookup=new Map(d.reports.map(r=>[r.id,r])),typeDelays={SVR:[],TOR:[],FFW:[]},seen=new Set();
 for(const a of d.associations){if(a.eligibility!=="candidate")continue;const t=wlookup.get(a.warning_id),r=rlookup.get(a.report_id),key=a.report_id+"/"+t;if(seen.has(key))continue;seen.add(key);if(t&&r?.delay_minutes!=null)typeDelays[t].push(r.delay_minutes/60);}
 const median=arr=>{let q=[...arr].sort((a,b)=>a-b);return q.length?q[Math.floor(q.length/2)]:0};
 chart("typeChart",[{type:"bar",orientation:"h",y:["FFW","TOR","SVR"],x:["FFW","TOR","SVR"].map(t=>median(typeDelays[t])),marker:{color:[colors.FFW,colors.TOR,colors.SVR]},customdata:["FFW","TOR","SVR"].map(t=>typeDelays[t].length),hovertemplate:"%{y}: %{x:.1f} hours, %{customdata} candidate LSRs<extra></extra>"}],{xaxis:{title:"Median hours (lower median if even n)"},margin:{l:50,r:20,t:10,b:45}});
 const times=[[0,5],[6,11],[12,17],[18,23]],groups=times.map(([lo,hi])=>d.warnings.filter(w=>w.hour_local>=lo&&w.hour_local<=hi));
 chart("hourChart",[{type:"bar",x:["Midnight–5","6AM–11","Noon–5","6PM–11"],y:groups.map(g=>{let n=g.filter(w=>w.first_lsr).length;return n?100*g.filter(w=>w.classification==="first_documented_after_expiration").length/n:0}),marker:{color:colors.late}}],{yaxis:{title:"% late among documented",range:[0,100]}});
}
function options(){
 for(let m=1;m<=12;m++)$("monthFilter").add(new Option(new Date(2025,m-1).toLocaleString("en",{month:"long"}),m));
 [...new Set(d.associations.map(a=>a.county).filter(Boolean))].sort().forEach(c=>$("countyFilter").add(new Option(c,c)));
}
function subset(){
 const typ=$("typeFilter").value,month=$("monthFilter").value,status=$("statusFilter").value,county=$("countyFilter").value,delay=$("delayFilter").value,search=$("searchFilter").value.toLowerCase();
 const assoc=new Map();for(const a of d.associations){if(!assoc.has(a.warning_id))assoc.set(a.warning_id,[]);assoc.get(a.warning_id).push(a);}
 return d.warnings.filter(w=>{
  const aa=assoc.get(w.id)||[];
  if(typ&&typ!==w.type)return false;if(month&&+month!==w.month)return false;if(status&&status!==w.classification)return false;
  if(county&&!aa.some(a=>a.county===county))return false;
  if(delay){let v=w.first_after_expiry_minutes;if(delay==="later"){if(v==null||v<=2880)return false;}else if(v==null||v>+delay*60)return false;}
  if(search&&![w.id,w.type,w.ugc,...aa.map(a=>a.county)].join(" ").toLowerCase().includes(search))return false;return true;
 }).sort((a,b)=>b.issued.localeCompare(a.issued));
}
function table(){
 filtered=subset();page=Math.max(0,Math.min(page,Math.ceil(filtered.length/25)-1));
 $("tableCount").textContent=fmt(filtered.length)+" / "+fmt(d.warnings.length)+" warnings · click a row";
 const rows=filtered.slice(page*25,page*25+25);
 $("warningRows").innerHTML=rows.map(w=>'<tr data-id="'+esc(w.id)+'"><td><b>'+esc(w.id)+'</b></td><td><span class="pill '+esc(w.type)+'">'+w.type+'</span></td><td>'+esc(w.issued_local)+'</td><td>'+esc(w.expired_local)+'</td><td>'+w.strict_reports+'</td><td>'+esc(minutes(w.first_after_expiry_minutes))+'</td><td><span class="status '+esc(w.classification)+'">'+esc(labels[w.classification])+'</span></td><td title="'+esc(w.flags.join(", "))+'">'+(w.flags.length?"⚠ "+w.flags.length:"—")+'</td></tr>').join("")||'<tr><td colspan="8" style="text-align:center;padding:25px">No matching warnings.</td></tr>';
 $("warningRows").querySelectorAll("tr[data-id]").forEach(tr=>tr.addEventListener("click",()=>select(tr.dataset.id)));
 $("pageLabel").textContent="Page "+(page+1)+" / "+Math.max(1,Math.ceil(filtered.length/25));
 $("prevPage").disabled=page<=0;$("nextPage").disabled=(page+1)*25>=filtered.length;
}
function select(id){
 selected=d.warnings.find(w=>w.id===id);if(!selected)return;const w=selected;
 const aa=d.associations.filter(a=>a.warning_id===id).sort((a,b)=>a.occurred.localeCompare(b.occurred));
 const rr=new Map(d.reports.map(r=>[r.id,r]));
 const start=stamp(w.issued),end=stamp(w.expired),tail=Math.max(end+7200000,...aa.map(a=>stamp(a.disseminated)).filter(Number.isFinite));
 const pos=t=>Math.max(0,Math.min(100,100*(stamp(t)-start)/Math.max(1800000,tail-start)));
 let tl='<div class="timeline"><div class="timeline-bar" style="left:0;width:'+pos(w.expired)+'%"></div>';
 tl+='<div class="timeline-point issue" style="left:0"><span>Issued '+esc(time(w.issued))+'</span></div><div class="timeline-point expire" style="left:'+pos(w.expired)+'%"><span>Expired '+esc(time(w.expired))+'</span></div>';
 for(const a of aa){tl+='<div class="timeline-point occur" style="left:'+pos(a.occurred)+'%;bottom:34px"><span>Event '+esc(time(a.occurred))+'</span></div>';if(a.disseminated)tl+='<div class="timeline-point pub" style="left:'+pos(a.disseminated)+'%"><span>Product '+esc(time(a.disseminated))+'</span></div>';}
 tl+='</div><div class="timeline-key"><span><b>Blue:</b> warning period</span><span><b>Teal:</b> occurrence</span><span><b>Gold:</b> linked product time</span></div>';
 let cards=aa.map(a=>{const r=rr.get(a.report_id)||{};return '<div class="report-card"><b>'+esc(r.type||"LSR")+'</b> · '+esc(r.city)+', '+esc(r.county)+' · '+esc(a.eligibility)+'<div class="report-meta"><span>Event: '+esc(time(a.occurred))+'</span><span>Product: '+esc(time(a.disseminated))+'</span><span>Mag: '+esc(r.magnitude??"—")+'</span></div><p>'+esc(r.remarks)+'</p>'+(r.source_url?'<a target="_blank" rel="noopener" href="'+esc(r.source_url)+'">Original source ↗</a>':"")+'</div>'}).join("");
 $("warningDetail").innerHTML='<div class="detail-head"><div><span class="eyebrow">INDIVIDUAL WARNING CHRONOLOGY</span><h3>'+esc(w.id)+'</h3><p>'+esc(labels[w.classification])+' · '+esc(w.flags.join("; ")||"No recorded QC flags")+'</p></div><a class="export-link" target="_blank" rel="noopener" href="'+esc(w.source_url)+'">↗ IEM archive</a></div>'+
 '<div class="detail-grid"><div><small>Issued · Central</small><strong>'+esc(w.issued_local)+'</strong></div><div><small>Expires · Central</small><strong>'+esc(w.expired_local)+'</strong></div><div><small>First source time − expiry</small><strong>'+minutes(w.first_after_expiry_minutes)+'</strong></div><div><small>Candidate / review LSRs</small><strong>'+w.strict_reports+' / '+w.review_reports+'</strong></div></div>'+
 '<h3 style="margin-top:24px">Chronology</h3>'+tl+'<h3>Linked reports ('+aa.length+')</h3><div class="report-list">'+(cards||'<p class="micro">No compatible report in the archive.</p>')+'</div>';
 if(map&&polygonLayer){polygonLayer.eachLayer(layer=>{let active=layer.options.warningId===w.id;layer.setStyle({weight:active?3:1,fillOpacity:active?.17:.015,opacity:active?1:.25});if(active&&layer.getBounds().isValid())map.fitBounds(layer.getBounds().pad(.35),{maxZoom:10});});}
}
function exportCsv(){
 const keys=["id","type","issued","expired","classification","strict_reports","review_reports","first_lsr","first_after_expiry_minutes","flags"];
 const q=x=>'"'+String(x??"").replace(/"/g,'""')+'"';
 const contents=[keys.join(","),...filtered.map(w=>keys.map(k=>q(k==="flags"?w.flags.join(";"):w[k])).join(","))].join("\n");
 const uri=URL.createObjectURL(new Blob([contents],{type:"text/csv"}));const a=document.createElement("a");a.href=uri;a.download="lix-2025-filtered.csv";a.click();setTimeout(()=>URL.revokeObjectURL(uri),5000);
}
function initMap(){
 if(!window.L){$("map").textContent="Map library unavailable (network required).";return;}
 map=L.map("map").setView([30.45,-90.15],8);
 const a=L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",{maxZoom:18,attribution:"© OpenStreetMap contributors · CARTO"}),b=L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",{maxZoom:18,attribution:"© OpenStreetMap contributors"});
 let errors=0,failover=false;a.on("tileerror",()=>{if(++errors>=5&&!failover){failover=true;map.removeLayer(a);b.addTo(map);}});a.addTo(map);
 polygonLayer=L.layerGroup().addTo(map);reportLayer=L.layerGroup().addTo(map);
 for(const w of d.warnings){try{L.geoJSON({type:"Feature",geometry:w.geometry,properties:{}},{style:{color:colors[w.type],weight:1,opacity:.55,fillOpacity:.04},onEachFeature:(_,l)=>{l.options.warningId=w.id;l.bindPopup('<b>'+esc(w.id)+'</b><p>'+esc(w.issued_local)+'<br>'+esc(labels[w.classification])+'</p>');l.on("click",()=>select(w.id));}}).addTo(polygonLayer);}catch(e){console.warn("Invalid geometry",w.id,e);}}
 const linked=new Map(d.associations.map(a=>[a.report_id,a]));for(const r of d.reports){if(r.lat==null||r.lon==null)continue;const assoc=linked.get(r.id),w=d.warnings.find(x=>x.id===assoc?.warning_id);const late=w&&r.disseminated&&stamp(r.disseminated)>stamp(w.expired);const point=L.circleMarker([r.lat,r.lon],{radius:5,weight:1,color:"#fff",fillColor:late?colors.late:colors.early,fillOpacity:.9});point.bindPopup('<b>'+esc(r.type)+'</b><p>'+esc(r.city)+', '+esc(r.county)+'<br>Occurred: '+esc(time(r.occurred))+'<br>Product: '+esc(time(r.disseminated))+'</p><p>'+esc(r.remarks)+'</p>');point.addTo(reportLayer);}
 $("polygonToggle").addEventListener("change",e=>e.target.checked?polygonLayer.addTo(map):map.removeLayer(polygonLayer));
 $("reportToggle").addEventListener("change",e=>e.target.checked?reportLayer.addTo(map):map.removeLayer(reportLayer));
 $("resetMap").addEventListener("click",()=>{map.setView([30.45,-90.15],8);polygonLayer.eachLayer(l=>l.setStyle({weight:1,opacity:.55,fillOpacity:.04}));});
}
function bind(){
 for(const id of ["typeFilter","monthFilter","statusFilter","countyFilter","delayFilter"]){$(id).addEventListener("change",()=>{page=0;table();});}
 $("searchFilter").addEventListener("input",()=>{page=0;table();});
 $("prevPage").addEventListener("click",()=>{--page;table();});
 $("nextPage").addEventListener("click",()=>{++page;table();});
 $("filteredExport").addEventListener("click",exportCsv);
}
async function start(){
 try{
 const res=await fetch("data/results.json",{cache:"no-cache"});if(!res.ok)throw Error("The data-build workflow has not published real 2025 archive results (HTTP "+res.status+").");
 d=await res.json();if(!d.warnings?.length||d.metadata.year!==2025)throw Error("Archive is empty or not for 2025");
 $("buildstatus").textContent="2025 archive · generated "+time(d.metadata.generated_utc);
 metrics();charts();options();bind();table();initMap();
 }catch(err){console.error(err);$("buildstatus").textContent="Archive unavailable";$("metrics").innerHTML='<div class="alert" role="alert"><strong>Real data unavailable</strong><span>'+esc(err.message)+' This website never substitutes fake sample statistics. <a href="https://github.com/mefferso/2025_stormdata_verification/actions">Check build logs ↗</a></span></div>';$("tableCount").textContent="Data could not be loaded.";}
}
document.addEventListener("DOMContentLoaded",start);

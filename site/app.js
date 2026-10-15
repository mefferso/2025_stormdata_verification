"use strict";
const $=id=>document.getElementById(id);
const COLORS={SVR:"#29739c",FFW:"#8061aa",within8:"#087e80",beyond24:"#bd7d18",beyond48:"#d45c25",beyond96:"#b64255",verylate:"#70439a",uncertain:"#82919d"};
const BINS=["0–1h",">1–3h",">3–8h",">8–12h",">12–24h",">24–48h",">48–72h",">72–96h",">96h"];
const WARNING_LABELS={candidate_within_8:"First LSR within 8h",candidate_after_8:"First LSR after 8h",candidate_untimed:"Candidate, time uncertain",needs_review:"Needs review",no_candidate_lsr:"No candidate found"};
const REPORT_LABELS={candidate:"Candidate support",overlap_review:"Overlapping warnings · review",needs_review:"Evidence needs review",unassociated:"No matching warning"};
const TIMING_LABELS={archive_confirmed:"First IEM text product located",uncertain_correction:"Conflicting correction · uncertain",uncertain_dst:"Ambiguous local time · review",proxy_only:"GeoJSON product proxy only",missing:"No publication time"};
const esc=value=>String(value??"").replace(/[&<>"']/g,ch=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
const num=value=>value==null?"—":Number(value).toLocaleString("en-US");
const pct=(numerator,denominator)=>denominator?`${(100*numerator/denominator).toFixed(1)}%`:"—";
const hours=minutes=>minutes==null?"—":`${(minutes/60).toFixed(1)}h`;
const when=value=>value?new Date(value).toLocaleString("en-US",{timeZone:"America/Chicago",year:"numeric",month:"short",day:"numeric",hour:"numeric",minute:"2-digit",timeZoneName:"short"}):"Unknown";
const monthOf=value=>value?Number(new Intl.DateTimeFormat("en-US",{timeZone:"America/Chicago",month:"numeric"}).format(new Date(value))):null;
const stamp=value=>value?new Date(value).getTime():NaN;
const safeUrl=value=>/^https:\/\/(?:mesonet\.agron\.iastate\.edu|www\.weather\.gov)\//.test(value||"")?value:"";
let data,reportPage=0,warningPage=0,filteredReports=[],filteredWarnings=[];
let map,markersLayer,polygonLayer,selectedPolygon,initialBounds;
const markers=new Map(),warningPolygons=new Map();

function notice(id,message){const node=$(id);if(node)node.innerHTML=`<div class="component-notice" role="status">${esc(message)}</div>`;}
function isolate(name,run,onError){try{run();}catch(error){console.error(`${name} failed`,error);onError?.(error);}}
function metric(title,value,detail,definition){return `<article class="metric"><div class="metric-label">${esc(title)} <span class="info" title="${esc(definition)}">ⓘ</span></div><strong>${esc(value)}</strong><small>${esc(detail)}</small></article>`;}
function showMetrics(){
 const o=data.overview,den=o.reliably_timed_lsrs;
 $("metrics").innerHTML=[
  metric("SVR-related source LSRs",num(o.source_svr_lsrs),"Unique 2025 LIX event records","Hail, thunderstorm wind gust, or thunderstorm wind damage LSRs after source deduplication; association is not required."),
  metric("FFW-related source LSRs",num(o.source_ffw_lsrs),"Unique 2025 flash-flood LSRs","Flash-flood type LSRs after source deduplication; association is not required."),
  metric("Candidate associated LSRs",num(o.associated_lsrs),`${num(o.overlap_review_lsrs)} more overlap case(s) need review`,"Unique LSRs with one unambiguous candidate warning. Overlapping candidate warnings have no primary attribution and are reported separately."),
  metric("Issued within 8 hours",`${num(o.within_8)} · ${pct(o.within_8,den)}`,`of ${num(den)} reliably timed associated LSRs`,"First matching raw LSR product at or before eight hours after original warning issuance, divided by reliably timed candidate LSRs."),
  metric("Issued beyond 8 hours",`${num(o.beyond_8)} · ${pct(o.beyond_8,den)}`,`of ${num(den)} reliably timed associated LSRs`,"First matching raw LSR product more than eight hours after original warning issuance, divided by reliably timed candidate LSRs."),
  metric("Median reporting delay",o.median_delay_hours==null?"—":`${o.median_delay_hours.toFixed(2)}h`,`original warning → first IEM text product`,"Median issuance-to-first-product interval among uniquely attributed, archive-confirmed LSRs with nonnegative delays.")
 ].join("");
 $("timingCoverage").innerHTML=`<b>Timing coverage:</b> ${num(o.reliably_timed_lsrs)} of ${num(o.associated_lsrs)} candidate LSRs contribute to timing percentages. ${num(o.timing_unknown)} have uncertain or missing first-product times; ${num(o.pre_warning)} were issued before the warning. ${num(o.other_review_lsrs)} additional LSRs need evidence review. Archive-confirmed first-product coverage among candidate LSRs: ${esc(o.archive_confirmed_share_of_associated)}%.`;
}
const plotLayout=(extra={})=>({font:{family:"system-ui, sans-serif",size:12,color:"#4e6474"},margin:{l:53,r:22,t:22,b:55},paper_bgcolor:"rgba(0,0,0,0)",plot_bgcolor:"rgba(0,0,0,0)",hoverlabel:{bgcolor:"#143044",font:{color:"#fff"}},...extra});
const plotConfig={responsive:true,displaylogo:false,toImageButtonOptions:{format:"svg",filename:"lix-2025-reporting-delay"}};
function plot(id,traces,layout,emptyMessage){
 if(!window.Plotly){notice(id,"Chart unavailable: Plotly did not load.");return Promise.resolve();}
 if(!traces.length||traces.every(trace=>!trace.x?.length&&!trace.y?.length)){notice(id,emptyMessage||"No reliable timing data for this chart.");return Promise.resolve();}
 try{return Promise.resolve(Plotly.newPlot(id,traces,plotLayout(layout),plotConfig)).catch(error=>{console.error(`${id} rendering failed`,error);notice(id,"This chart could not be rendered.");});}
 catch(error){console.error(`${id} rendering failed`,error);notice(id,"This chart could not be rendered.");return Promise.resolve();}
}
function chartTask(id,prepare){isolate(`Chart ${id}`,prepare,()=>notice(id,"Chart data could not be prepared."));}
function drawCharts(){
 const by=data.by_phenomenon, kinds=["SVR","FFW"];
 const sample=`SVR: ${num(by.SVR.reliably_timed_lsrs)} · FFW: ${num(by.FFW.reliably_timed_lsrs)} reliably timed LSRs`;
 for(const id of ["distributionDenominator","eightHourDenominator","cumulativeDenominator"])$(id).textContent=sample;
 $("warningDenominator").textContent=`${num(data.overview.warnings)} distinct warning episodes (SVR ${num(data.warnings.filter(w=>w.type==="SVR").length)}, FFW ${num(data.warnings.filter(w=>w.type==="FFW").length)})`;
 chartTask("distributionChart",()=>plot("distributionChart",kinds.map(kind=>({type:"bar",name:kind,x:BINS,y:BINS.map(label=>by[kind].bins[label]),marker:{color:COLORS[kind]},customdata:BINS.map(label=>by[kind].reliably_timed_lsrs?pct(by[kind].bins[label],by[kind].reliably_timed_lsrs):"—"),hovertemplate:"%{x}<br>%{y} "+kind+" LSRs (%{customdata})<extra></extra>"})),{barmode:"group",showlegend:true,legend:{orientation:"h",y:1.16},xaxis:{tickangle:-35},yaxis:{title:"Unique LSRs",rangemode:"tozero"},shapes:[{type:"line",x0:2.5,x1:2.5,y0:0,y1:1,yref:"paper",line:{color:"#bc4a50",width:2,dash:"dash"}}]}));
 chartTask("eightHourChart",()=>plot("eightHourChart",[
  {type:"bar",name:"≤8 hours",x:kinds,y:kinds.map(k=>by[k].within_8),marker:{color:COLORS.within8},text:kinds.map(k=>`${by[k].within_8} / ${by[k].reliably_timed_lsrs}`),textposition:"inside",hovertemplate:"%{x}: %{y} within 8h<extra></extra>"},
  {type:"bar",name:">8 hours",x:kinds,y:kinds.map(k=>by[k].beyond_8),marker:{color:COLORS.beyond24},text:kinds.map(k=>`${by[k].beyond_8} / ${by[k].reliably_timed_lsrs}`),textposition:"inside",hovertemplate:"%{x}: %{y} beyond 8h<extra></extra>"}
 ],{barmode:"stack",showlegend:true,legend:{orientation:"h",y:1.2},yaxis:{title:"Reliably timed LSRs",rangemode:"tozero"}}));
 chartTask("cumulativeChart",()=>plot("cumulativeChart",kinds.map(kind=>{const x=[1,3,8,12,24,48,72,96],den=by[kind].reliably_timed_lsrs;return {type:"scatter",mode:"lines+markers",name:kind,x,y:x.map(h=>den?100*by[kind].cumulative[String(h)]/den:null),customdata:x.map(h=>`${by[kind].cumulative[String(h)]} / ${den}`),line:{color:COLORS[kind],width:3,shape:"hv"},marker:{size:7},hovertemplate:"By %{x}h: %{y:.1f}% (%{customdata})<extra>"+kind+"</extra>"};}),{showlegend:true,legend:{orientation:"h",y:1.2},xaxis:{title:"Hours after warning issuance",tickvals:[1,3,8,12,24,48,72,96]},yaxis:{title:"% of reliably timed LSRs",range:[0,102]},shapes:[{type:"line",x0:8,x1:8,y0:0,y1:1,yref:"paper",line:{color:"#bc4a50",width:2,dash:"dash"}}]}));
 chartTask("longDelayChart",()=>{const labels=[">24h",">48h",">72h",">96h"],hours=[24,48,72,96];const promise=plot("longDelayChart",kinds.map(kind=>({type:"bar",orientation:"h",name:kind,y:labels,x:hours.map(h=>by[kind][`beyond_${h}`]),marker:{color:COLORS[kind]},customdata:hours,hovertemplate:"%{y}: %{x} "+kind+" LSRs<extra>Click to inspect</extra>"})),{barmode:"group",showlegend:true,legend:{orientation:"h",y:1.22},xaxis:{title:"Unique LSRs"},margin:{l:70,r:20,t:22,b:55}});promise.then(()=>{const node=$("longDelayChart");if(node.on)node.on("plotly_click",event=>{const threshold=event.points?.[0]?.customdata;if(threshold){$("reportDelay").value=`beyond${threshold}`;reportPage=0;renderReports();$("reports").scrollIntoView({behavior:"smooth"});}});});});
 chartTask("warningChart",()=>{const labels=["First ≤8h","First >8h","Candidate untimed","Needs review","No candidate"],states=["candidate_within_8","candidate_after_8","candidate_untimed","needs_review","no_candidate_lsr"];plot("warningChart",kinds.map(kind=>({type:"bar",name:kind,x:labels,y:states.map(state=>data.warnings.filter(w=>w.type===kind&&w.classification===state).length),marker:{color:COLORS[kind]},hovertemplate:"%{x}: %{y} "+kind+" warnings<extra></extra>"})),{barmode:"group",showlegend:true,legend:{orientation:"h",y:1.2},xaxis:{tickangle:-24},yaxis:{title:"Distinct warnings"}});});
}
function populateOptions(){
 for(let month=1;month<=12;month++)$("reportMonth").add(new Option(new Date(2025,month-1,1).toLocaleString("en-US",{month:"long"}),String(month)));
 [...new Set(data.reports.map(r=>r.county).filter(Boolean))].sort((a,b)=>a.localeCompare(b)).forEach(county=>$("reportCounty").add(new Option(county,county)));
}
function delayMatch(report,value){const d=report.delay_minutes;if(!value)return true;if(value==="uncertain")return d==null||report.timing_status!=="archive_confirmed";if(value==="prewarning")return d!=null&&d<0;if(d==null||d<0)return false;if(value==="within8")return d<=480;if(value==="beyond8")return d>480;const threshold=Number(value.replace("beyond",""));return Number.isFinite(threshold)&&d>threshold*60;}
function reportSubset(){
 const type=$("reportType").value,month=$("reportMonth").value,county=$("reportCounty").value,delay=$("reportDelay").value,status=$("reportStatus").value,search=$("reportSearch").value.trim().toLowerCase();
 const list=data.reports.filter(r=>(!type||r.phenomenon===type)&&(!month||monthOf(r.occurred)===Number(month))&&(!county||r.county===county)&&(!status||r.association_status===status)&&delayMatch(r,delay)&&(!search||[r.id,r.type,r.city,r.county,r.remarks,r.primary_warning_id,...r.possible_warning_ids].join(" ").toLowerCase().includes(search)));
 const sort=$("reportSort").value;
 list.sort((a,b)=>sort==="delay_asc"?(a.delay_minutes??Infinity)-(b.delay_minutes??Infinity):sort==="occurred_desc"?stamp(b.occurred)-stamp(a.occurred):sort==="occurred_asc"?stamp(a.occurred)-stamp(b.occurred):(b.delay_minutes??-Infinity)-(a.delay_minutes??-Infinity));
 return list;
}
function timingCell(report){if(report.first_issued)return esc(when(report.first_issued));if(report.proxy_issued)return `<span title="GeoJSON product link; not verified as first issuance">Uncertain · proxy ${esc(when(report.proxy_issued))}</span>`;return "Unknown";}
function renderReports(){
 filteredReports=reportSubset();reportPage=Math.min(reportPage,Math.max(0,Math.ceil(filteredReports.length/25)-1));
 $("reportCount").textContent=`${num(filteredReports.length)} / ${num(data.reports.length)} unique LSRs · ${num(data.overview.associated_lsrs)} candidate associated in full study`;
 const rows=filteredReports.slice(reportPage*25,reportPage*25+25);
 $("reportRows").innerHTML=rows.map(r=>`<tr data-id="${esc(r.id)}"><td><span class="pill ${esc(r.phenomenon)}">${esc(r.phenomenon)}</span></td><td>${esc(r.type)}</td><td>${esc(r.county)}</td><td>${esc(when(r.occurred))}</td><td>${esc(r.primary_warning_id||r.possible_warning_ids.join("; ")||"—")}</td><td>${esc(when(r.warning_issued))}</td><td>${timingCell(r)}</td><td class="delay-value">${esc(hours(r.delay_minutes))}</td><td>${esc(r.delay_bin||"Unknown / review")}</td><td><span class="status">${esc(TIMING_LABELS[r.timing_status])}</span><small>${esc(REPORT_LABELS[r.association_status])}</small></td><td>${safeUrl(r.earliest_source_url||r.source_url)?`<a href="${esc(safeUrl(r.earliest_source_url||r.source_url))}" target="_blank" rel="noopener">IEM ↗</a>`:"—"}</td></tr>`).join("")||'<tr><td colspan="11" class="empty-row">No LSRs match these filters.</td></tr>';
 $("reportRows").querySelectorAll("tr[data-id]").forEach(row=>row.addEventListener("click",event=>{if(event.target.closest("a"))return;selectReport(row.dataset.id,true);}));
 $("reportPage").textContent=`Page ${reportPage+1} / ${Math.max(1,Math.ceil(filteredReports.length/25))}`;
 $("reportPrev").disabled=reportPage===0;$("reportNext").disabled=(reportPage+1)*25>=filteredReports.length;
}
function reportDetails(report){
 const links=report.possible_warning_ids.map(id=>{const warning=data.warnings.find(w=>w.id===id);return `<li><button type="button" data-warning="${esc(id)}" class="text-button">${esc(id)}</button> · issued ${esc(when(warning?.issued))} · <a href="${esc(safeUrl(warning?.source_url))}" target="_blank" rel="noopener">warning source ↗</a></li>`;}).join("");
 const provenance=report.raw_provenance.map(p=>`<li>${esc(when(p.issued))} · <a href="${esc(safeUrl(p.source_url))}" target="_blank" rel="noopener">raw LSR text ↗</a>${p.archive_url?` · <a href="${esc(safeUrl(p.archive_url))}" target="_blank" rel="noopener">monthly archive ↗</a>`:""}<small>SHA-256 ${esc(p.text_sha256.slice(0,16))}… · ZIP entry ${esc(p.archive_entry)}</small></li>`).join("");
 return `<div class="detail-head"><div><span class="eyebrow">LSR EVIDENCE &amp; PROVENANCE</span><h3>${esc(report.type)} · ${esc(report.city)}, ${esc(report.county)}</h3><p>${esc(REPORT_LABELS[report.association_status])} · ${esc(TIMING_LABELS[report.timing_status])}</p></div><span class="pill ${esc(report.phenomenon)}">${esc(report.phenomenon)}</span></div>
 <div class="detail-grid"><div><small>Reported event</small><strong>${esc(when(report.occurred))}</strong></div><div><small>Original warning issuance</small><strong>${esc(when(report.warning_issued))}</strong></div><div><small>Earliest confirmed LSR issuance</small><strong>${esc(when(report.first_issued))}</strong></div><div><small>Hours after warning</small><strong>${esc(hours(report.delay_minutes))}</strong></div></div>
 ${report.first_issued?"":`<p class="review-note">First issuance is uncertain or missing. ${report.proxy_issued?`The GeoJSON-linked product time is ${esc(when(report.proxy_issued))}; it is not used in the delay percentages.`:"No source-product time is available."}</p>`}
 ${report.delay_minutes!=null&&report.delay_minutes<0?'<p class="review-note">This LSR product predates the warning. Its negative delay is excluded from the post-warning distribution.</p>':""}
 <h4>Report remarks</h4><p class="remarks">${esc(report.remarks||"No remarks in source record.")}</p><div class="detail-columns"><div><h4>Warning attribution</h4>${links?`<ul>${links}</ul>`:'<p>No temporally and spatially eligible warning was identified.</p>'}</div><div><h4>Matched raw text products</h4>${provenance?`<ul>${provenance}</ul>`:'<p>No exact raw text match was established.</p>'}</div></div><p class="micro">${esc(report.flags.join(" · ")||"No additional QC flags.")}</p>`;
}
function selectReport(id,focusMap=false){const report=data.reports.find(r=>r.id===id);if(!report)return;$("reportDetail").innerHTML=reportDetails(report);$("reportDetail").querySelectorAll("[data-warning]").forEach(button=>button.addEventListener("click",()=>{selectWarning(button.dataset.warning,true);$("warnings").scrollIntoView({behavior:"smooth"});}));if(map&&focusMap)focusReportOnMap(report);}
function warningSubset(){const type=$("warningType").value,status=$("warningStatus").value,search=$("warningSearch").value.trim().toLowerCase();return data.warnings.filter(w=>(!type||w.type===type)&&(!status||w.classification===status)&&(!search||[w.id,w.vtec_id,w.ugc].join(" ").toLowerCase().includes(search))).sort((a,b)=>b.issued.localeCompare(a.issued));}
function renderWarnings(){
 filteredWarnings=warningSubset();warningPage=Math.min(warningPage,Math.max(0,Math.ceil(filteredWarnings.length/25)-1));$("warningCount").textContent=`${num(filteredWarnings.length)} / ${num(data.warnings.length)} distinct warnings`;
 const rows=filteredWarnings.slice(warningPage*25,warningPage*25+25);
 $("warningRows").innerHTML=rows.map(w=>`<tr data-id="${esc(w.id)}"><td><b>${esc(w.id)}</b></td><td><span class="pill ${esc(w.type)}">${esc(w.type)}</span></td><td>${esc(when(w.issued))}</td><td>${esc(when(w.expired))}</td><td>${num(w.candidate_lsr_count)}</td><td>${num(w.review_lsr_count)}</td><td>${esc(hours(w.first_supporting_delay_minutes))}</td><td>${esc(WARNING_LABELS[w.classification])}</td></tr>`).join("")||'<tr><td colspan="8" class="empty-row">No warnings match these filters.</td></tr>';
 $("warningRows").querySelectorAll("tr[data-id]").forEach(row=>row.addEventListener("click",()=>selectWarning(row.dataset.id,true)));
 $("warningPage").textContent=`Page ${warningPage+1} / ${Math.max(1,Math.ceil(filteredWarnings.length/25))}`;$("warningPrev").disabled=warningPage===0;$("warningNext").disabled=(warningPage+1)*25>=filteredWarnings.length;
}
function selectWarning(id,focusMap=false){
 const warning=data.warnings.find(w=>w.id===id);if(!warning)return;
 const pairs=data.associations.filter(a=>a.warning_id===id),lookup=new Map(data.reports.map(r=>[r.id,r]));
 const items=pairs.map(a=>{const r=lookup.get(a.report_id);return `<li><button class="text-button" data-report="${esc(r.id)}" type="button">${esc(r.type)} · ${esc(r.county)}</button> · ${esc(when(r.occurred))} · ${esc(a.attribution)} · ${esc(hours(r.delay_minutes))}</li>`;}).join("");
 $("warningDetail").innerHTML=`<div class="detail-head"><div><span class="eyebrow">DISTINCT WARNING EPISODE</span><h3>${esc(warning.id)}</h3><p>${esc(WARNING_LABELS[warning.classification])}</p></div><a class="export-link" target="_blank" rel="noopener" href="${esc(safeUrl(warning.source_url))}">Archived warning ↗</a></div><div class="detail-grid"><div><small>Original issue</small><strong>${esc(when(warning.issued))}</strong></div><div><small>Polygon validity end</small><strong>${esc(when(warning.expired))}</strong></div><div><small>Candidate LSRs</small><strong>${num(warning.candidate_lsr_count)}</strong></div><div><small>First reliable LSR delay</small><strong>${esc(hours(warning.first_supporting_delay_minutes))}</strong></div></div><p class="micro">VTEC number ${esc(warning.vtec_id)} · ${esc(warning.flags.join(" · ")||"No additional QC flags")}</p><h4>Spatially and temporally linked reports (${pairs.length})</h4>${items?`<ul class="linked-list">${items}</ul>`:'<p>No compatible source LSR was identified; this does not determine official warning verification.</p>'}`;
 $("warningDetail").querySelectorAll("[data-report]").forEach(button=>button.addEventListener("click",()=>{selectReport(button.dataset.report,true);$("reports").scrollIntoView({behavior:"smooth"});}));
 if(map&&focusMap)focusWarningOnMap(warning);
}
function csvDownload(rows,fields,filename){const q=value=>{let v=Array.isArray(value)?value.join("; "):String(value??"");if(/^[=+@\-]/.test(v))v="'"+v;return '"'+v.replace(/"/g,'""')+'"';};const content=[fields.join(","),...rows.map(row=>fields.map(key=>q(row[key])).join(","))].join("\n");const url=URL.createObjectURL(new Blob([content],{type:"text/csv"}));const anchor=document.createElement("a");anchor.href=url;anchor.download=filename;anchor.click();setTimeout(()=>URL.revokeObjectURL(url),5000);}
function bindExplorer(){
 populateOptions();for(const id of ["reportType","reportMonth","reportCounty","reportDelay","reportStatus","reportSort"])$(id).addEventListener("change",()=>{reportPage=0;renderReports();});$("reportSearch").addEventListener("input",()=>{reportPage=0;renderReports();});
 $("reportPrev").addEventListener("click",()=>{reportPage--;renderReports();});$("reportNext").addEventListener("click",()=>{reportPage++;renderReports();});
 $("reportExport").addEventListener("click",()=>csvDownload(filteredReports,["id","phenomenon","type","county","city","occurred","primary_warning_id","warning_issued","first_issued","proxy_issued","timing_status","delay_minutes","delay_bin","association_status","source_url","earliest_source_url","remarks"],"lix-2025-filtered-lsrs.csv"));
 $("resetReportFilters").addEventListener("click",()=>{for(const id of ["reportType","reportMonth","reportCounty","reportDelay","reportStatus"])$(id).value="";$("reportSort").value="delay_desc";$("reportSearch").value="";reportPage=0;renderReports();});
 for(const id of ["warningType","warningStatus"])$(id).addEventListener("change",()=>{warningPage=0;renderWarnings();});$("warningSearch").addEventListener("input",()=>{warningPage=0;renderWarnings();});
 $("warningPrev").addEventListener("click",()=>{warningPage--;renderWarnings();});$("warningNext").addEventListener("click",()=>{warningPage++;renderWarnings();});
 $("resetWarningFilters").addEventListener("click",()=>{$("warningType").value="";$("warningStatus").value="";$("warningSearch").value="";warningPage=0;renderWarnings();});
 renderReports();renderWarnings();
}
function markerColor(report){const delay=report.delay_minutes;if(report.association_status!=="candidate"||report.timing_status!=="archive_confirmed"||delay==null||delay<0)return COLORS.uncertain;if(delay<=480)return COLORS.within8;if(delay<=1440)return COLORS.beyond24;if(delay<=2880)return COLORS.beyond48;if(delay<=5760)return COLORS.beyond96;return COLORS.verylate;}
function markerIcon(report,active=false){const color=markerColor(report),shape=report.phenomenon==="FFW"?'<path d="M15 2L28 15 15 28 2 15Z"/>':'<circle cx="15" cy="15" r="12"/>';return L.divIcon({className:`lsr-icon ${active?"selected":""}`,html:`<svg viewBox="0 0 30 30" role="img" aria-label="${esc(report.phenomenon)} LSR"><g fill="${color}" stroke="#fff" stroke-width="2.5">${shape}</g></svg>`,iconSize:[30,30],iconAnchor:[15,15],popupAnchor:[0,-15]});}
function mapPopup(report){const warning=data.warnings.find(w=>w.id===report.primary_warning_id);const source=safeUrl(report.earliest_source_url||report.source_url);const possible=report.possible_warning_ids.map(id=>{const item=data.warnings.find(w=>w.id===id);return item?`<li>${esc(id)} · issued ${esc(when(item.issued))} · <a href="${esc(safeUrl(item.source_url))}" target="_blank" rel="noopener">source ↗</a></li>`:"";}).join("");return `<div class="map-popup"><b>${esc(report.phenomenon)} · ${esc(report.type)}</b><p>${esc(report.city)}, ${esc(report.county)}<br>Occurred: ${esc(when(report.occurred))}<br>Attribution: ${esc(REPORT_LABELS[report.association_status])}<br>First raw LSR: ${esc(report.first_issued?when(report.first_issued):"Uncertain / missing")}${!report.first_issued&&report.proxy_issued?`<br>GeoJSON proxy: ${esc(when(report.proxy_issued))}`:""}<br>Delay: ${esc(hours(report.delay_minutes))}</p>${possible?`<b>Possible warnings</b><ul>${possible}</ul>`:""}<p>${esc(report.remarks)}</p>${source?`<a href="${esc(source)}" target="_blank" rel="noopener">Archived LSR ↗</a>`:""}</div>`;}
function createMap(){
 if(!window.L){notice("map","Map unavailable: Leaflet did not load.");return;}
 map=L.map("map",{zoomControl:true,preferCanvas:false});map.createPane("warnings");map.getPane("warnings").style.zIndex=410;
 const osm=L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png",{maxZoom:19,attribution:"© OpenStreetMap contributors"});
 const esri=L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",{maxZoom:16,attribution:"Tiles © Esri"});let tileErrors=0,fallback=false;
 osm.on("tileerror",()=>{if(++tileErrors>=2&&!fallback){fallback=true;console.warn("OpenStreetMap tiles failed; switching to Esri");map.removeLayer(osm);esri.addTo(map);}});
 esri.on("tileerror",()=>{notice("mapStatus","Basemap unavailable here. Report markers and polygons remain usable.");console.error("Esri fallback tile failed");});osm.addTo(map);
 polygonLayer=L.featureGroup();
 for(const warning of data.warnings){try{if(!warning.geometry||!["Polygon","MultiPolygon"].includes(warning.geometry.type))continue;const layer=L.geoJSON({type:"Feature",geometry:warning.geometry,properties:{}},{pane:"warnings",style:{color:COLORS[warning.type],weight:1.1,opacity:.5,fillOpacity:.035}});layer.bindPopup(`<b>${esc(warning.id)}</b><br>Issued ${esc(when(warning.issued))}<br>${esc(WARNING_LABELS[warning.classification])}`);layer.on("click",()=>selectWarning(warning.id,true));warningPolygons.set(warning.id,layer);layer.addTo(polygonLayer);}catch(error){console.warn("Warning geometry skipped",warning.id,error);}}
 selectedPolygon=L.featureGroup().addTo(map);
 markersLayer=window.L.markerClusterGroup?L.markerClusterGroup({showCoverageOnHover:false,spiderfyOnMaxZoom:true,maxClusterRadius:38,disableClusteringAtZoom:11}):L.featureGroup();
 markersLayer.addTo(map);
 const georeports=data.reports.filter(r=>r.association_status!=="unassociated"&&r.lat!=null&&r.lon!=null&&Number.isFinite(+r.lat)&&Number.isFinite(+r.lon));
 for(const report of georeports){const marker=L.marker([+report.lat,+report.lon],{icon:markerIcon(report),title:`${report.phenomenon} ${report.type} · ${report.county}`});marker.bindPopup(mapPopup(report),{maxWidth:330});marker.on("click",()=>selectReport(report.id,false));markers.set(report.id,marker);}
 initialBounds=L.latLngBounds(georeports.map(r=>[+r.lat,+r.lon]));if(!initialBounds.isValid()&&polygonLayer.getLayers().length)initialBounds.extend(polygonLayer.getBounds());
 if(initialBounds.isValid())map.fitBounds(initialBounds.pad(.08),{maxZoom:9,padding:[18,18]});else map.setView([30.45,-90.15],8);
 const refresh=()=>{markersLayer.clearLayers();for(const report of georeports){if((report.phenomenon==="SVR"&&!$("mapSVR").checked)||(report.phenomenon==="FFW"&&!$("mapFFW").checked)||!delayMatch(report,$("mapDelay").value))continue;markersLayer.addLayer(markers.get(report.id));}if($("mapPolygons").checked)polygonLayer.addTo(map);else map.removeLayer(polygonLayer);};
 for(const id of ["mapSVR","mapFFW","mapPolygons","mapDelay"])$(id).addEventListener("change",refresh);
 $("resetMapFilters").addEventListener("click",()=>{$("mapSVR").checked=true;$("mapFFW").checked=true;$("mapPolygons").checked=false;$("mapDelay").value="";refresh();});
 $("resetMap").addEventListener("click",()=>{selectedPolygon.clearLayers();for(const [id,marker] of markers){const r=data.reports.find(item=>item.id===id);marker.setIcon(markerIcon(r));}if(initialBounds.isValid())map.fitBounds(initialBounds.pad(.08),{maxZoom:9,padding:[18,18]});});
 refresh();if(window.ResizeObserver)new ResizeObserver(()=>map.invalidateSize()).observe($("map"));setTimeout(()=>map.invalidateSize(),0);
 window.dashboardDiagnostics={map,markersLayer,polygonLayer,markers,refresh,initialBounds};
}
function highlightWarningPolygon(warning){if(!map)return;selectedPolygon.clearLayers();const polygon=warningPolygons.get(warning.id);if(polygon){const focused=L.geoJSON({type:"Feature",geometry:warning.geometry,properties:{}},{pane:"warnings",style:{color:COLORS[warning.type],weight:3,opacity:1,fillOpacity:.16}});focused.addTo(selectedPolygon);}}
function focusReportOnMap(report){const marker=markers.get(report.id);if(!marker)return;$("mapSVR").checked=true;$("mapFFW").checked=true;$("mapDelay").value="";window.dashboardDiagnostics.refresh();for(const [id,item] of markers){const r=data.reports.find(row=>row.id===id);item.setIcon(markerIcon(r,id===report.id));}const warning=data.warnings.find(w=>w.id===report.primary_warning_id);if(warning)highlightWarningPolygon(warning);else selectedPolygon.clearLayers();if(markersLayer.zoomToShowLayer)markersLayer.zoomToShowLayer(marker,()=>{marker.openPopup();map.panTo(marker.getLatLng());});else{map.setView(marker.getLatLng(),Math.max(map.getZoom(),10));marker.openPopup();}}
function focusWarningOnMap(warning){if(!map)return;$("mapSVR").checked=true;$("mapFFW").checked=true;$("mapDelay").value="";window.dashboardDiagnostics.refresh();highlightWarningPolygon(warning);const linked=data.associations.filter(a=>a.warning_id===warning.id).map(a=>data.reports.find(r=>r.id===a.report_id)).filter(Boolean);for(const [id,marker] of markers){const r=data.reports.find(row=>row.id===id);marker.setIcon(markerIcon(r,linked.some(item=>item.id===id)));}const bounds=L.latLngBounds(linked.filter(r=>r.lat!=null&&r.lon!=null).map(r=>[+r.lat,+r.lon]));if(bounds.isValid())map.fitBounds(bounds.pad(.35),{maxZoom:10});else{const polygon=warningPolygons.get(warning.id);if(polygon?.getBounds().isValid())map.fitBounds(polygon.getBounds().pad(.3),{maxZoom:10});}}
async function start(){
 try{const response=await fetch("data/results.json",{cache:"no-cache"});if(!response.ok)throw Error(`HTTP ${response.status} while loading results.json`);try{data=await response.json();}catch(error){throw Error(`Invalid results.json: ${error.message}`);}if(data.metadata?.year!==2025||!Array.isArray(data.reports)||!Array.isArray(data.warnings)||!Array.isArray(data.associations)||!data.by_phenomenon||data.warnings.some(w=>!["SVR","FFW"].includes(w.type)))throw Error("Published 2025 report data failed schema checks.");}
 catch(error){console.error("Dashboard data retrieval failed",error);$("buildstatus").textContent="Archive unavailable";notice("metrics",`Data could not be loaded: ${error.message}`);for(const id of ["distributionChart","eightHourChart","cumulativeChart","longDelayChart","warningChart","reportDetail","warningDetail","map"])notice(id,"Unavailable because archive data could not be loaded.");$("reportCount").textContent="LSR data unavailable";$("warningCount").textContent="Warning data unavailable";return;}
 $("buildstatus").textContent=`2025 archive · rebuilt ${when(data.metadata.generated_utc)}`;
 isolate("Overview",showMetrics,()=>notice("metrics","Overview metrics could not be rendered."));
 isolate("Charts",drawCharts,()=>{for(const id of ["distributionChart","eightHourChart","cumulativeChart","longDelayChart","warningChart"])notice(id,"Chart data could not be prepared.");});
 isolate("Explorers",bindExplorer,()=>{$("reportCount").textContent="LSR Explorer could not be rendered";$("warningCount").textContent="Warning Explorer could not be rendered";});
 isolate("Map",createMap,()=>notice("map","Geographic delay map could not be rendered."));
}
document.addEventListener("DOMContentLoaded",start);

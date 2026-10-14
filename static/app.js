const $ = (id) => document.getElementById(id);
let lastResult = null;
const colors = ["#4263b8","#17836c","#bd7b28","#8458b5","#c34e69","#287f9e","#68758a"];
const examples = [
  {name:"Job A",arrival_time:0,cpu_burst:5,priority:2,memory_mb:256,holds:[],requests:[]},
  {name:"Job B",arrival_time:1,cpu_burst:3,priority:1,memory_mb:384,holds:[],requests:[]},
  {name:"Job C",arrival_time:2,cpu_burst:4,priority:3,memory_mb:192,holds:[],requests:[]}
];
function esc(s){return String(s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
function splitResources(v){return v.split(",").map(x=>x.trim()).filter(Boolean);}
function addRow(job={name:`Job ${$("jobRows").children.length+1}`,arrival_time:0,cpu_burst:4,priority:1,memory_mb:128,holds:[],requests:[]}){
  const tr=document.createElement("tr");
  tr.innerHTML=`
    <td><input aria-label="Job name" data-k="name" value="${esc(job.name)}" required></td>
    <td><input aria-label="Arrival time" data-k="arrival_time" type="number" min="0" value="${job.arrival_time}"></td>
    <td><input aria-label="CPU burst" data-k="cpu_burst" type="number" min="1" value="${job.cpu_burst}"></td>
    <td><input aria-label="Priority" data-k="priority" type="number" min="0" value="${job.priority}"></td>
    <td><input aria-label="Memory MB" data-k="memory_mb" type="number" min="1" value="${job.memory_mb}"></td>
    <td><input class="resource-input" aria-label="Resources held" data-k="holds" value="${esc((job.holds||[]).join(", "))}" placeholder="e.g. Printer"></td>
    <td><input class="resource-input" aria-label="Resources requested" data-k="requests" value="${esc((job.requests||[]).join(", "))}" placeholder="e.g. Scanner"></td>
    <td><button class="button remove" type="button" title="Remove job">×</button></td>`;
  tr.querySelector(".remove").addEventListener("click",()=>{tr.remove();});
  $("jobRows").appendChild(tr);
}
function loadExamples(){ $("jobRows").innerHTML=""; examples.forEach(addRow); $("algorithm").value="FCFS"; $("quantum").value=2; $("memory").value=1024; $("errorBox").classList.add("hidden"); }
function readJobs(){
  return [...$("jobRows").querySelectorAll("tr")].map(tr=>{
    const obj={};
    tr.querySelectorAll("[data-k]").forEach(input=>{
      const k=input.dataset.k;
      if(k==="name") obj[k]=input.value.trim();
      else if(k==="holds"||k==="requests") obj[k]=splitResources(input.value);
      else obj[k]=Number(input.value);
    });
    return obj;
  });
}
function showError(msg){$("errorBox").textContent=msg;$("errorBox").classList.remove("hidden");}
async function runSimulation(){
  $("errorBox").classList.add("hidden");
  const jobs=readJobs();
  if(!jobs.length){showError("Add at least one job.");return;}
  if(jobs.some(j=>!j.name||!Number.isFinite(j.cpu_burst)||j.cpu_burst<1||j.arrival_time<0||j.memory_mb<1)){showError("Check job names and numeric fields. CPU burst and memory must be positive.");return;}
  const body={algorithm:$("algorithm").value,quantum:Number($("quantum").value),total_memory_mb:Number($("memory").value),jobs};
  $("runBtn").disabled=true;$("runBtn").textContent="Simulating…";
  try{
    const res=await fetch("/api/simulate",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
    const data=await res.json();
    if(!res.ok) throw new Error(data.detail||"Could not run simulation.");
    lastResult=data;render(data);
  }catch(e){showError(e.message||"Unable to reach the server. Is FastAPI running?");}
  finally{$("runBtn").disabled=false;$("runBtn").textContent="Run simulation";}
}
function metric(label,value,detail){return `<div class="metric"><div class="label">${label}</div><div class="value">${value}</div><div class="detail">${detail}</div></div>`;}
function statusClass(s){return s.toLowerCase().replaceAll(" ","-");}
function render(data){
  $("results").classList.remove("hidden");$("algorithmBadge").textContent=data.algorithm+(data.algorithm==="Round Robin"?` · q=${data.quantum}`:"");
  const m=data.metrics;
  $("metrics").innerHTML=[
    metric("CPU utilization",`${m.cpu_utilization_percent}%`,"Simulated busy time / elapsed time"),
    metric("Memory allocated",`${m.memory_allocated_mb} MB`,`Capacity: ${data.total_memory_mb} MB`),
    metric("Memory remaining",`${m.memory_remaining_mb} MB`,"After simulation allocations are released"),
    metric("Jobs completed",m.completed_jobs,`of ${data.jobs.length} submitted`),
    metric("Deadlocked jobs",m.deadlocked_jobs,"Cycle-based detection")
  ].join("");
  $("resultRows").innerHTML=data.jobs.map(j=>{
    let recovery="—";
    if(["Deadlocked","Waiting for resource","Waiting","Waiting for memory"].includes(j.status)){
      recovery=`<div class="recovery-actions"><button class="button secondary" onclick="recoverJob('${j.id}','cancel')">Cancel</button><button class="button secondary" onclick="recoverJob('${j.id}','rollback')">Roll back</button></div>`;
    } else if(j.recovery) recovery=esc(j.recovery);
    return `<tr><td><strong>${esc(j.name)}</strong><br><span class="muted">${j.id}</span></td><td><span class="status ${statusClass(j.status)}">${esc(j.status)}</span></td><td>${j.cpu_burst}</td><td>${j.memory_mb} MB</td><td>${j.waiting_time??"—"}</td><td>${j.turnaround_time??"—"}</td><td>${recovery}</td></tr>`;
  }).join("");
  const graph=Object.entries(data.wait_for_graph||{});
  $("graph").innerHTML=graph.length?graph.map(([from,tos])=>`<div class="graph-line"><span class="node">${esc(from)}</span><span class="arrow">→</span><span>${tos.length?tos.map(t=>`<span class="node">${esc(t)}</span>`).join(", "):'<span class="muted">no dependency</span>'}</span></div>`).join(""):'<p class="muted">No active dependencies.</p>';
  $("deadlockNotice").innerHTML=data.deadlock_cycles?.length?`<div class="notice"><strong>Deadlock detected.</strong> Cycle(s): ${data.deadlock_cycles.map(c=>c.map(esc).join(" → ")).join("; ")}. Cancel or roll back a job to release its resources.</div>`:'<div class="success-notice">No wait-for cycle detected in this run.</div>';
  const total=Math.max(1,...data.timeline.map(s=>s.end));
  $("timeline").innerHTML=data.timeline.length?data.timeline.map(s=>{
    const width=Math.max(.5,(s.end-s.start)/total*100);
    const color=s.kind==="idle"?"#aeb7c7":colors[Number((s.job_id||"J1").replace("J","")-1)%colors.length];
    return `<div class="segment ${s.kind==="idle"?"idle":""}" style="width:${width}%;background:${color}" title="${esc(s.job_name)}: ${s.start}–${s.end}">${width>5?esc(s.job_name):""}</div>`;
  }).join(""):'<span class="muted">No CPU timeline segments.</span>';
  $("timelineScale").innerHTML=`<span>0</span><span>${Math.round(total/2)} time units</span><span>${total} time units</span>`;
  $("events").innerHTML=data.events.length?data.events.map(e=>{
    if(e.type==="allocate")return `<div class="event"><strong>t=${e.time}</strong> · ${esc(e.job_id)} allocated ${e.memory_mb} MB</div>`;
    if(e.type==="release")return `<div class="event"><strong>t=${e.time}</strong> · ${esc(e.job_id)} released ${e.memory_mb} MB</div>`;
    return `<div class="event"><strong>${esc(e.type)}</strong> · ${esc(e.job_id)} ${esc(e.action||"")}</div>`;
  }).join(""):'<span class="muted">No events recorded.</span>';
  $("results").scrollIntoView({behavior:"smooth",block:"start"});
}
async function recoverJob(job_id,action){
  try{
    const res=await fetch("/api/recover",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({job_id,action})});
    const data=await res.json();if(!res.ok)throw new Error(data.detail||"Recovery failed.");
    lastResult=data;render(data);
  }catch(e){showError(e.message);}
}
$("addJobBtn").addEventListener("click",()=>addRow());
$("resetBtn").addEventListener("click",loadExamples);
$("runBtn").addEventListener("click",runSimulation);
loadExamples();

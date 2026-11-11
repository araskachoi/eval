'use strict';
const el = id => document.getElementById(id);
let current = null;
let historySignature = '';
async function api(path, data) {
  const response = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json','X-Eval-Control':'1'}, body:JSON.stringify(data)});
  if(response.status===401) { el('workspace').hidden=true; el('login').hidden=false; historySignature=''; }
  if (!response.ok) throw new Error(response.status === 401 ? 'Your connection expired. Get a new one-time code to reconnect.' : 'Could not open this recording. Reconnect or check that it is still available.');
  return response.json();
}
function text(tag, value, parent) { const node = document.createElement(tag); node.textContent = value; parent.append(node); return node; }
const number = value => value == null ? 'Unavailable' : value.toLocaleString();
const outcome = value => value === 'Ungraded' ? 'Not evaluated — no checks were recorded.' : value === 'Passed supplied checks' ? 'All recorded checks passed.' : value === 'Failed' ? 'A recorded check failed.' : 'A check could not run.';
const when = value => new Date(value * 1000).toLocaleString([], {dateStyle:'medium', timeStyle:'short'});
async function safe(action) { el('error').textContent=''; try { await action(); } catch(error) { el('error').textContent=error.message; } }
async function openRecording(id) { show(await api('/control',{action:'report',recording_id:id})); }
function show(report) {
  current=report;
  const p=report.presentation, f=p.metrics, labels=p.agents;
  el('analysis').hidden=false;
  el('report-title').textContent=p.title;
  el('source').textContent=f.source;
  el('description').textContent=p.description;
  el('identity').textContent=`${when(report.recording.started)} · ${f.coverage} · ${f.model}`;
  el('metrics').replaceChildren();
  for (const [label,value] of [['Total tokens',f.tokens],['Elapsed time',f.elapsed],[f.cost_label,f.cost],['Cached input',f.cache],['Cached output',f.cached_output],['Lines',f.lines]]) {
    const box=text('div','',el('metrics')); box.className='metric';
    const display=text('strong',label==='Lines' && value!=='Unavailable'?'':value,box);
    if(label==='Lines' && value!=='Unavailable') {
      display.className='line-changes';
      const added=text('span',`+${f.lines_added}`,display); added.className='added';
      const removed=text('span',`−${f.lines_removed}`,display); removed.className='removed';
      display.setAttribute('aria-label',`${f.lines_added} lines added, ${f.lines_removed} lines removed`);
    }
    text('span',label,box);
  }
  const nodes=report.executions;
  const multiple=nodes.length>1;
  if(!multiple) el('sort').value='own_tokens';
  const hasHierarchy=multiple && nodes.some(n=>nodes.some(parent=>parent.id===n.parent_id));
  el('view-label').hidden=!hasHierarchy;
  if(!hasHierarchy) el('view').value='ranked';
  const sortable = [...el('sort').options].filter(option => {
    option.disabled = new Set(nodes.map(n=>n[option.value])).size<2;
    return !option.disabled;
  });
  el('sort-label').hidden=!multiple || !sortable.length;
  if(el('sort').selectedOptions[0].disabled && sortable.length) el('sort').value=sortable[0].value;
  el('agent-controls').hidden=!multiple || (!hasHierarchy && !sortable.length);
  el('single-agent').textContent=nodes.length===1 ? 'Only one agent action was recorded, so there is nothing to group or rank.' : nodes.length===0 ? 'No agent activity was received. Usage is unavailable.' : '';
  drawTree();
  el('models').replaceChildren();
  if(report.recording.source==='controlled-simulation') {
    text('p','No AI model ran. These counters come from a scripted fixture; its pricing profile is not a model name.',el('models'));
  } else {
    text('p','Exact model IDs are shown only when reported by a response or harness event. An alias is not expanded into an assumed snapshot version. Unknown usage remains unattributed.',el('models'));
    if(!report.models.length) text('p','No model identity or usage has been received.',el('models'));
    for(const row of report.models) {
      const item=text('div','',el('models')); item.className='model-usage';
      text('strong',row.model||'Model not reported',item);
      text('p',`${row.harness==='codex'?'Codex':row.harness==='claude-code'?'Claude Code':row.harness||'Harness not reported'} · ${row.provider==='openai'?'OpenAI':row.provider==='anthropic'?'Anthropic':row.provider||'Provider not reported'} · ${row.model_source==='response'?'Reported by provider response':row.model_source==='harness'?'Reported by harness':'Identity unavailable'}${row.adapter?' · '+row.adapter:''}`,item);
      text('p',`${number(row.tokens)} tokens · ${number(row.counter_complete.cached?row.totals.cached:null)} cached input · Estimated USD unavailable${row.usage_complete?'':' · Partial usage'}`,item);
    }
  }
  el('warnings').replaceChildren();
  for(const warning of report.warnings) text('li',warning,el('warnings'));
  el('security').replaceChildren();
  const reasons={prompt_injection:'possible prompt injection',sensitive_data:'sensitive data',unapproved_origin:'unverified prompt origin',inspection_error:'security inspection failed',policy_mismatch:'security policy mismatch'};
  for(const item of report.security) text('p',`${item.action==='block'?'MAGEN blocked a proposal':'Security inspection allowed a proposal'}${item.reasons.length?': '+item.reasons.map(r=>reasons[r]||'security policy').join(', '):''}.`,el('security'));
  el('outcome').textContent=outcome(report.outcome); el('checks').replaceChildren();
  const checkNames={coordinates:'Invalid location handling',display:'Weather display',timeout:'Timeout handling',auth:'Invalid API key handling',rate_limit:'Rate limit handling',unavailable:'Service outage handling',malformed:'Invalid response handling',units:'Temperature conversion'};
  for(const item of report.assessments) text('p',`${checkNames[item.check]||item.check}: ${item.status} · ${item.grader} · ${item.scope} · ${item.provenance}`,el('checks'));
  el('findings').replaceChildren();
  const top=nodes.filter(n=>n.own_tokens!=null).sort((a,b)=>b.own_tokens-a.own_tokens)[0];
  if(top) text('p',nodes.length===1 ? `${labels[top.id]} used ${number(top.own_tokens)} tokens.` : `${labels[top.id]} used the most tokens: ${number(top.own_tokens)} for its own work.`,el('findings'));
  text('p',report.tool_failures ? `${number(report.tool_failures)} tool call(s) failed. This alone does not establish whether the task succeeded.` : 'No failed tool calls were recorded.',el('findings'));
  el('related').replaceChildren();
  const recordings=report.task_summary.attempts;
  if(recordings.length>1) {
    text('h3','Other recordings of this task',el('related'));
    text('p','These are separate measurement windows for the same task, not subagents. Passing the recorded checks does not prove the whole application works.',el('related'));
    for(const [index,record] of recordings.entries()) {
      const button=text('button',`Recording ${index+1} · ${record.outcome==='Passed supplied checks'?'Checks passed':record.outcome==='Failed'?'Check failed':'Not fully evaluated'}`,el('related'));
      button.disabled=record.recording_id===report.recording.id;
      button.onclick=()=>safe(()=>openRecording(record.recording_id));
    }
  }
  el('diagnostics').textContent=JSON.stringify({application:report.recording.application,recording_id:report.recording.id,task_id:report.recording.task_id,chat_id:report.recording.thread_id,analysis_version:report.analysis_version,models:report.models,executions:report.executions},null,2);
  el('analysis').scrollIntoView({block:'start'});
}
function drawTree() {
  el('tree').replaceChildren(); if(!current) return;
  const key=el('sort').value;
  const nodes=[...current.executions].sort((a,b)=>(b[key]??-1)-(a[key]??-1));
  const labels=current.presentation.agents;
  const visited=new Set();
  const nested=el('view').value==='tree';
  el('comparison').textContent=nodes.length>1 ? `${nested?'Grouped under the agent that started them':'Listed from highest to lowest'} · ${el('sort').selectedOptions[0].textContent}. Tokens are each agent's own usage; child usage is not added again.` : '';
  function append(node,parent) {
    if(visited.has(node.id)) return;
    visited.add(node.id);
    const detail=text('details','',parent); detail.className='agent';
    const measured=key==='tool_ms' ? `${number(node.tool_ms)} ms in tools` : key==='failures' ? `${number(node.failures)} failed tool calls` : `${number(node.own_tokens)} tokens`;
    text('summary',`${labels[node.id]} · ${measured} · ${node.status==='running'?'Still running when last observed':node.status==='completed'?'Completed':node.status==='failed'?'Failed':node.status==='interrupted'?'Interrupted':'Status unknown'}`,detail);
    if(node.parent_id) text('p',`Started by: ${labels[node.parent_id]||'an agent outside this recording'}`,detail);
    text('p',`Tokens for this agent: ${number(node.own_tokens)} · Failed tool calls: ${number(node.failures)} · Recorded tool time: ${number(node.tool_ms)} ms`,detail);
    for(const row of node.models) text('p',`${row.fixture_profile?'Simulation profile: '+row.fixture_profile:row.model||'Model not reported'} · ${number(row.tokens)} tokens${row.harness?' · '+row.harness:''}`,detail);
    if(nested) {
      const children=text('div','',parent); children.className='agent-children';
      for(const child of nodes.filter(n=>n.parent_id===node.id)) append(child,children);
    }
  }
  for(const node of nodes.filter(n=>!nested||!nodes.some(p=>p.id===n.parent_id))) append(node,el('tree'));
  for(const node of nodes) append(node,el('tree'));
}
function historyRow(record,parent) {
  const row=text('div','',parent); row.className='recording';
  const info=text('div','',row);
  text('strong',record.title,info);
  text('p',`${when(record.started)} · ${record.finished===null?'Recording':'Finished'}`,info);
  const button=text('button','View recording',row);
  button.onclick=()=>safe(()=>openRecording(record.id));
}
async function refresh() {
  const status=await api('/control',{action:'status'});
  const build=status.application;
  if(build) el('app-version').textContent=`Local Eval ${build.version} · ${build.release_id==='development'?'Development checkout':build.release_id}`;
  if(status.updating) el('state').textContent='App update in progress. New recordings are temporarily paused.';
  const signature=JSON.stringify([status.recordings,status.updating]);
  if(signature===historySignature) return;
  historySignature=signature;
  const active=status.recordings.find(r=>r.finished===null);
  el('state').textContent=status.updating ? 'App update in progress. New recordings are temporarily paused.' : active ? 'A measurement window is open. Live desktop capture remains unverified.' : 'No measurement window is open.';
  for(const id of ['history','sample-history','sample-archive']) el(id).replaceChildren();
  const real=status.recordings.filter(r=>r.source!=='controlled-simulation');
  if(!real.length) text('p','No live recordings yet. You can explore the labeled samples below.',el('history'));
  for(const record of real) historyRow(record,el('history'));
  const samples=status.recordings.filter(r=>r.source==='controlled-simulation');
  const latestTasks=new Map();
  for(const record of samples) if(!latestTasks.has(record.sample_case||'legacy')) latestTasks.set(record.sample_case||'legacy',record.task_id);
  let archived=0;
  for(const record of samples) {
    const recent=latestTasks.get(record.sample_case||'legacy')===record.task_id;
    historyRow(record,el(recent?'sample-history':'sample-archive'));
    if(!recent) archived++;
  }
  el('archive-label').textContent=`Earlier sample copies (${archived} recordings)`;
  el('samples').hidden=!samples.length;
}
 el('login-form').onsubmit=event=>{event.preventDefault();safe(async()=>{await api('/session',{code:el('code').value});el('code').value='';el('login').hidden=true;el('workspace').hidden=false;await refresh();});};
 el('sort').onchange=drawTree;
 el('view').onchange=drawTree;
 refresh().then(()=>{el('login').hidden=true;el('workspace').hidden=false;}).catch(()=>{});
 setInterval(()=>{if(!el('workspace').hidden) safe(refresh);},5000);

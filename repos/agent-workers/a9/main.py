import os, json, glob
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

LOG_DIR = "/opt/ai-native/logs/llm_calls/"
app = FastAPI(title="LLM Call Log Viewer")

class CallEntry(BaseModel):
    req_id: str
    call_id: str
    agent_id: str = ""
    task_type: str = ""
    model: str = ""
    status: str = ""
    timestamp: str = ""
    duration_ms: int = 0
    tokens_total: int = 0

async def scan_all_logs(agent: str = "", task_type: str = "", status: str = "") -> List[CallEntry]:
    results = []
    if not os.path.isdir(LOG_DIR):
        return results
    for req_dir in sorted(os.listdir(LOG_DIR)):
        d = os.path.join(LOG_DIR, req_dir)
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith('.json'):
                continue
            fp = os.path.join(d, fn)
            try:
                with open(fp) as f:
                    data = json.load(f)
            except Exception:
                continue
            entry = CallEntry(
                req_id=req_dir, call_id=fn[:-5],
                agent_id=data.get("agent_id", ""),
                task_type=data.get("task_type", ""),
                model=data.get("model", ""),
                status=data.get("status", ""),
                timestamp=data.get("timestamp", ""),
                duration_ms=data.get("duration_ms", 0),
                tokens_total=data.get("tokens", {}).get("total", 0),
            )
            if agent and entry.agent_id != agent:
                continue
            if task_type and entry.task_type != task_type:
                continue
            if status and entry.status != status:
                continue
            results.append(entry)
    return results

def get_call_detail(req_id: str, call_id: str) -> dict:
    fp = os.path.join(LOG_DIR, req_id, f"{call_id}.json")
    if not os.path.isfile(fp):
        raise HTTPException(404, "Not found")
    with open(fp) as f:
        return json.load(f)

def get_all_agents() -> list:
    agents = set()
    if not os.path.isdir(LOG_DIR):
        return []
    for req_dir in os.listdir(LOG_DIR):
        d = os.path.join(LOG_DIR, req_dir)
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            if not fn.endswith('.json'):
                continue
            try:
                with open(os.path.join(d, fn)) as f:
                    a = json.load(f).get("agent_id", "")
                if a:
                    agents.add(a)
            except Exception:
                pass
    return sorted(agents)

@app.get("/api/llm-calls")
async def list_calls(agent: str = "", task_type: str = "", status: str = ""):
    return await scan_all_logs(agent, task_type, status)

@app.get("/api/llm-calls/{req_id}")
async def list_req_calls(req_id: str):
    return await scan_all_logs("", "", "")

@app.get("/api/llm-calls/{req_id}/{call_id}")
async def get_call(req_id: str, call_id: str):
    return get_call_detail(req_id, call_id)

@app.get("/api/agents")
async def list_agents():
    return get_all_agents()

@app.get("/", response_class=HTMLResponse)
async def index():
    html = '''<!DOCTYPE html><html lang="zh"><head><meta charset="UTF-8"><title>LLM Calls Viewer</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:"Segoe UI",system-ui,sans-serif;background:#1a1a2e;color:#e0e0e0;display:flex;height:100vh}
#sidebar{width:260px;background:#16213e;overflow-y:auto;border-right:1px solid #0f3460;padding:10px}
#sidebar h2{font-size:14px;padding:8px 4px;color:#e94560;border-bottom:1px solid #0f3460;margin-bottom:8px}
#sidebar .req-item{padding:6px 8px;cursor:pointer;border-radius:4px;font-size:12px;margin:2px 0}
#sidebar .req-item:hover{background:#0f3460}
#sidebar .req-item.active{background:#e94560;color:#fff}
.req-id{font-family:monospace;font-size:11px}
.req-count{color:#8899aa;font-size:10px}
#main{flex:1;display:flex;flex-direction:column;overflow:hidden}
#toolbar{display:flex;gap:8px;padding:10px 16px;background:#16213e;border-bottom:1px solid #0f3460;flex-wrap:wrap}
#toolbar select,#toolbar input{padding:6px 10px;border-radius:4px;border:1px solid #0f3460;background:#1a1a2e;color:#e0e0e0;font-size:12px}
#toolbar select:focus,#toolbar input:focus{outline:none;border-color:#e94560}
#stats{padding:8px 16px;font-size:11px;color:#8899aa}
#table-wrap{flex:1;overflow:auto;padding:0 16px 16px}
table{width:100%;border-collapse:collapse;font-size:12px}
th{position:sticky;top:0;background:#16213e;padding:8px 10px;text-align:left;font-weight:600;color:#e94560;z-index:1}
td{padding:6px 10px;border-bottom:1px solid #0f3460}
tr:hover{background:#0f3460;cursor:pointer}
tr.expanded{background:#0f3460}
.status-ok{color:#4ecca3}.status-fail{color:#e94560}
.detail-row{display:none}
.detail-row.show{display:table-row}
.detail-cell{padding:16px;background:#0a0a1a}
.detail-cell pre{background:#111;padding:12px;border-radius:4px;overflow:auto;max-height:400px;font-size:11px;white-space:pre-wrap;word-break:break-all;font-family:"Cascadia Code","Fira Code",monospace;color:#a8d8ea}
.detail-label{color:#e94560;font-weight:600;margin:8px 0 4px}
</style></head><body>
<div id="sidebar"><h2>Requirements</h2><div id="req-list"></div></div>
<div id="main">
<div id="toolbar">
<select id="filter-agent"><option value="">All Agents</option></select>
<input id="filter-task" placeholder="task_type">
<select id="filter-status"><option value="">All Status</option><option value="success">success</option><option value="error">error</option></select>
<button onclick="loadCalls()" style="padding:6px 12px;border-radius:4px;border:none;background:#e94560;color:#fff;cursor:pointer;font-size:12px">Refresh</button>
</div>
<div id="stats"></div><div id="table-wrap"><table><thead><tr><th>Req ID</th><th>Call ID</th><th>Agent</th><th>Task</th><th>Model</th><th>Status</th><th>Duration</th><th>Tokens</th><th>Time</th></tr></thead><tbody id="tbody"></tbody></table></div></div>
<script>
let allCalls=[];
async function loadCalls(){
    const a=document.getElementById('filter-agent').value;
    const t=document.getElementById('filter-task').value;
    const s=document.getElementById('filter-status').value;
    const p=new URLSearchParams();
    if(a)p.set('agent',a);if(t)p.set('task_type',t);if(s)p.set('status',s);
    const r=await fetch('/api/llm-calls?'+p.toString());
    allCalls=await r.json();
    renderTable(allCalls);
    renderSidebar(allCalls);
    document.getElementById('stats').textContent=allCalls.length+' calls';
}
function renderTable(calls){
    const tb=document.getElementById('tbody');
    tb.innerHTML=calls.map((c,i)=>'<tr onclick="toggleDetail('+i+')" id="row'+i+'"><td>'+c.req_id+'</td><td>'+c.call_id.substring(0,8)+'...</td><td>'+c.agent_id+'</td><td>'+c.task_type+'</td><td style="font-size:10px">'+c.model+'</td><td class="'+(c.status==='success'?'status-ok':'status-fail')+'">'+c.status+'</td><td>'+(c.duration_ms/1000).toFixed(1)+'s</td><td>'+c.tokens_total+'</td><td style="font-size:10px">'+c.timestamp+'</td></tr><tr class="detail-row" id="det'+i+'"><td colspan="9" class="detail-cell"><div id="content'+i+'">Loading...</div></td></tr>').join('');
}
async function toggleDetail(i){
    const row=document.getElementById('det'+i);
    const content=document.getElementById('content'+i);
    if(row.classList.contains('show')){
        row.classList.remove('show');
        document.getElementById('row'+i).classList.remove('expanded');
    }else{
        row.classList.add('show');
        document.getElementById('row'+i).classList.add('expanded');
        const c=allCalls[i];
        const r=await fetch('/api/llm-calls/'+c.req_id+'/'+c.call_id);
        const d=await r.json();
        let tokensHtml='';
        if(d.tokens)tokensHtml='<div class="detail-label">Tokens: prompt='+d.tokens.prompt+' completion='+d.tokens.completion+' total='+d.tokens.total+'</div>';
        let promptText=d.prompt||'';
        try{const p=JSON.parse(promptText);promptText=JSON.stringify(p,null,2)}catch(e){}
        let respText=d.response||'';
        try{const p=JSON.parse(respText);respText=JSON.stringify(p,null,2)}catch(e){}
        content.innerHTML=tokensHtml+'<div class="detail-label">Prompt ('+(promptText.length>1000?(promptText.length/1000).toFixed(0)+'k':'')+')</div><pre>'+escapeHtml(promptText.substring(0,5000))+'</pre><div class="detail-label">Response ('+(respText.length>1000?(respText.length/1000).toFixed(0)+'k':'')+')</div><pre>'+escapeHtml(respText.substring(0,20000))+'</pre>';
    }
}
function escapeHtml(t){return t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}
function renderSidebar(calls){
    const map={};
    calls.forEach(c=>{if(!map[c.req_id])map[c.req_id]={count:0,agents:new Set()};map[c.req_id].count++;map[c.req_id].agents.add(c.agent_id)});
    const list=document.getElementById('req-list');
    const filter=document.getElementById('filter-agent').value;
    list.innerHTML=Object.entries(map).sort().map(([id,info])=>{
        const active=filter&&info.agents.has(filter)?' active':'';
        return '<div class="req-item'+active+'" onclick="document.getElementById(\'filter-agent\').value=\''+Array.from(info.agents)[0]+'\';loadCalls()"><div class="req-id">'+id+'</div><div class="req-count">'+info.count+' calls | '+Array.from(info.agents).join(', ')+'</div></div>';
    }).join('');
}
async function loadAgents(){
    const r=await fetch('/api/agents');
    const agents=await r.json();
    const sel=document.getElementById('filter-agent');
    agents.forEach(a=>{const o=document.createElement('option');o.value=a;o.textContent=a;sel.appendChild(o)});
}
loadAgents();loadCalls();
</script></body></html>'''
    return html

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8400)

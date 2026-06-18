#!/usr/bin/env python3
"""
Mender Artifact Bundle GUI
Web-based helper to package Docker Compose projects into Mender artifacts.

Usage:
    pip install pyyaml
    python bundle-gui.py [--port 8888] [--no-browser]
"""

import argparse
import http.server
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import uuid
import webbrowser
from pathlib import Path
from urllib.parse import urlparse, parse_qs

try:
    import yaml
except ImportError:
    print("Missing dependency: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

# ── Native file picker ────────────────────────────────────────────────────────

def browse_dialog(dialog_type: str, title: str, initial_dir: str, filetypes: list) -> str:
    result = [""]
    def _run():
        try:
            import tkinter as tk
            from tkinter import filedialog
        except ImportError:
            result[0] = "__unavailable__"; return
        root = tk.Tk(); root.withdraw(); root.wm_attributes("-topmost", True)
        start = initial_dir if initial_dir and os.path.exists(initial_dir) else os.path.expanduser("~")
        ft = [(f[0], f[1]) for f in filetypes] if filetypes else [("All", "*")]
        if dialog_type == "directory":
            result[0] = filedialog.askdirectory(title=title, initialdir=start) or ""
        elif dialog_type == "save":
            result[0] = filedialog.asksaveasfilename(title=title, initialdir=start,
                defaultextension=".yml", filetypes=ft) or ""
        else:
            result[0] = filedialog.askopenfilename(title=title, initialdir=start, filetypes=ft) or ""
        root.destroy()
    t = threading.Thread(target=_run, daemon=True); t.start(); t.join(timeout=120)
    return result[0]

# ── Job registry ──────────────────────────────────────────────────────────────

_jobs: dict = {}

# ── HTML ──────────────────────────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mender Bundle GUI</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,sans-serif;background:#f0f2f5;color:#222;min-height:100vh}
header{background:#1a3a5c;color:#fff;padding:.85rem 2rem;display:flex;align-items:center;gap:1rem}
header h1{font-size:1.05rem;font-weight:600}
header p{font-size:.78rem;opacity:.7;margin-top:.1rem}
main{max-width:1200px;margin:1.5rem auto;padding:0 1rem;display:flex;flex-direction:column;gap:1.25rem}
.card{background:#fff;border-radius:8px;padding:1.25rem;box-shadow:0 1px 4px rgba(0,0,0,.08)}
.card-title{font-size:.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.09em;color:#999;margin-bottom:1rem;display:flex;align-items:center;gap:.5rem}
.card-title span{flex:1}
label{display:block;font-size:.8rem;font-weight:500;margin-bottom:.25rem;color:#444}
input,select,textarea{width:100%;padding:.42rem .7rem;border:1px solid #d0d0d0;border-radius:5px;font-size:.86rem;background:#fff;font-family:inherit}
input,select{margin-bottom:.8rem}
textarea{resize:vertical}
input:focus,select:focus,textarea:focus{outline:none;border-color:#1a3a5c;box-shadow:0 0 0 2px rgba(26,58,92,.12)}
.row2{display:grid;grid-template-columns:1fr 1fr;gap:1rem}
.row3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:1rem}
button{padding:.4rem 1rem;border:none;border-radius:5px;font-size:.84rem;font-weight:500;cursor:pointer;transition:background .15s;white-space:nowrap}
.btn-primary{background:#1a3a5c;color:#fff}.btn-primary:hover{background:#142e4a}
.btn-primary:disabled{background:#a0a0a0;cursor:not-allowed}
.btn-ghost{background:#f0f2f5;color:#333;border:1px solid #d0d0d0}.btn-ghost:hover{background:#e4e6ea}
.btn-danger{background:#fff0f0;color:#c0392b;border:1px solid #f5c6cb}.btn-danger:hover{background:#ffe0e0}
.btn-sm{padding:.28rem .65rem;font-size:.78rem}.btn-xs{padding:.18rem .45rem;font-size:.73rem}
.flex{display:flex;gap:.4rem;align-items:center}
.flex input,.flex select{margin:0;flex:1}

/* Import bar */
.import-bar{background:#f7f8fa;border:1px solid #e4e7ea;border-radius:6px;padding:.75rem 1rem;margin-bottom:1rem;display:flex;align-items:center;gap:.6rem;flex-wrap:wrap}
.import-bar label{margin:0;font-size:.8rem;color:#666;white-space:nowrap}
.import-bar input{margin:0;flex:1;min-width:200px}

/* Editor split */
.editor-split{display:grid;grid-template-columns:1fr 1fr;gap:1rem}
@media(max-width:900px){.editor-split{grid-template-columns:1fr}}
.pane-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:.5rem}
.pane-label{font-size:.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:#aaa}
.pane-acts{display:flex;gap:.3rem}
.builder-pane{overflow-y:auto;max-height:540px;padding-right:.25rem}
.yaml-editor{width:100%;height:520px;font-family:'Cascadia Code',Consolas,monospace;font-size:.76rem;line-height:1.5;border:1px solid #d0d0d0;border-radius:5px;padding:.75rem;background:#1e1e1e;color:#d4d4d4;tab-size:2;resize:none}
.yaml-editor:focus{outline:none;border-color:#1a3a5c;box-shadow:0 0 0 2px rgba(26,58,92,.12)}

/* Service cards */
.svc-card{border:1px solid #e0e4ea;border-radius:6px;margin-bottom:.7rem;overflow:hidden}
.svc-card-head{display:flex;align-items:center;gap:.5rem;background:#f7f8fa;padding:.5rem .8rem;cursor:pointer;user-select:none}
.svc-card-label{flex:1;font-weight:600;font-size:.85rem}
.svc-card-body{padding:.85rem;display:none}
.svc-card-body.open{display:block}
.sec-label{font-size:.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.07em;color:#bbb;margin:.7rem 0 .3rem}
.kv-row{display:grid;grid-template-columns:1fr 1fr auto;gap:.35rem;align-items:center;margin-bottom:.3rem}
.kv-row input{margin:0}

/* Dockerfile tabs */
.df-tabs{display:flex;border-bottom:2px solid #eee;margin-bottom:.75rem;overflow-x:auto;flex-wrap:nowrap}
.df-tab{padding:.38rem .9rem;cursor:pointer;font-size:.82rem;font-weight:500;color:#999;border-bottom:2px solid transparent;margin-bottom:-2px;white-space:nowrap;transition:color .15s}
.df-tab.active{color:#1a3a5c;border-bottom-color:#1a3a5c}
.df-panel{display:none}.df-panel.active{display:block}
.df-path{font-size:.78rem;color:#888;font-family:monospace;margin-bottom:.5rem;display:flex;align-items:center;gap:.4rem}
.df-editor{width:100%;height:280px;font-family:'Cascadia Code',Consolas,monospace;font-size:.76rem;line-height:1.5;border:1px solid #d0d0d0;border-radius:5px;padding:.7rem;background:#1e1e1e;color:#d4d4d4;tab-size:4;resize:vertical}

/* Directory tree */
.dir-tree{font-family:monospace;font-size:.8rem;line-height:1.75;background:#f7f8fa;border:1px solid #eee;border-radius:5px;padding:.75rem;min-height:60px;white-space:pre}
.tree-dir{color:#1a3a5c;font-weight:600}
.tree-new{color:#27ae60}
.tree-note{color:#bbb;font-style:italic}

/* Image combobox */
.img-wrap{display:flex;gap:.35rem;align-items:center;margin-bottom:.8rem}
.img-wrap input{margin:0;flex:1}
.img-combo{position:relative;flex:1}
.img-combo input{margin:0;width:100%}
.img-dropdown{position:absolute;top:calc(100% + 2px);left:0;right:0;background:#fff;border:1px solid #c8d0da;border-radius:6px;box-shadow:0 6px 18px rgba(0,0,0,.12);z-index:200;max-height:220px;overflow-y:auto;list-style:none;display:none}
.img-dropdown.open{display:block}
.img-group-label{padding:.28rem .75rem;font-size:.66rem;font-weight:700;text-transform:uppercase;letter-spacing:.07em;color:#aaa;background:#f7f8fa;border-bottom:1px solid #eee;position:sticky;top:0}
.img-option{padding:.35rem .75rem;font-size:.82rem;cursor:pointer;font-family:monospace;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.img-option:hover,.img-option.focused{background:#eef2ff;color:#1a3a5c}
.img-msg{padding:.5rem .75rem;font-size:.8rem;color:#aaa;font-style:italic}

/* Build log */
.log{background:#1e1e1e;color:#d4d4d4;font-family:'Cascadia Code',Consolas,monospace;font-size:.76rem;padding:.9rem;border-radius:5px;height:360px;overflow-y:auto;white-space:pre-wrap;word-break:break-all;line-height:1.5}
.log .ok{color:#4ec9b0}.log .err{color:#f48771}.log .info{color:#9cdcfe}
.status-bar{display:flex;align-items:center;gap:.6rem;margin-top:.6rem;font-size:.84rem}
.dot{width:9px;height:9px;border-radius:50%;background:#bbb;flex-shrink:0}
.dot.running{background:#e67e22;animation:pulse 1s infinite}
.dot.success{background:#27ae60}.dot.error{background:#e74c3c}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
.hidden{display:none}
.divider{border:none;border-top:1px solid #eee;margin:.3rem 0 .9rem}
.notice{font-size:.78rem;color:#999;margin-top:-.4rem;margin-bottom:.8rem}
.badge{padding:.13rem .4rem;border-radius:3px;font-size:.7rem;font-weight:700;text-transform:uppercase}
.badge-image{background:#d4edda;color:#1e7e34}.badge-build{background:#cce5ff;color:#004085}.badge-tar{background:#fff3cd;color:#856404}
</style>
</head>
<body>
<header>
  <div>
    <h1>Mender Bundle GUI</h1>
    <p>Compose editor · Dockerfiles · Mender artifact packaging</p>
  </div>
</header>
<main>

<!-- ── Compose Project Editor ── -->
<div class="card">
  <div class="card-title"><span>Compose Project</span></div>

  <div class="import-bar">
    <label>Import existing</label>
    <input id="importPath" type="text" placeholder="/path/to/docker-compose.yml">
    <button class="btn-ghost btn-sm" onclick="browse('importPath','file','Select docker-compose.yml',[['YAML','*.yml *.yaml'],['All','*']])">&#128193;</button>
    <button class="btn-primary btn-sm" onclick="importCompose()">Import &#8594;</button>
  </div>

  <div class="editor-split">
    <!-- Visual builder -->
    <div>
      <div class="pane-head">
        <span class="pane-label">Services</span>
        <button class="btn-ghost btn-sm" onclick="addServiceCard()">+ Add Service</button>
      </div>
      <div class="builder-pane">
        <div id="svcCards"></div>
        <hr class="divider">
        <div class="pane-head" style="margin-bottom:.5rem">
          <span class="pane-label">Networks</span>
          <button class="btn-ghost btn-sm" onclick="addNetRow()">+ Add Network</button>
        </div>
        <div id="netRows"></div>
      </div>
    </div>

    <!-- YAML editor -->
    <div>
      <div class="pane-head">
        <span class="pane-label">docker-compose.yml</span>
        <div class="pane-acts">
          <button class="btn-ghost btn-sm" title="Regenerate from visual builder" onclick="refreshYaml()">&#8635; Refresh</button>
          <button class="btn-ghost btn-sm" title="Parse YAML and update visual builder" onclick="applyYaml()">&#8595; Apply</button>
          <button class="btn-ghost btn-sm" onclick="saveYamlToFile()">&#128190; Save</button>
        </div>
      </div>
      <textarea class="yaml-editor" id="yamlEditor" spellcheck="false"
        onkeydown="yamlTabKey(event)" oninput="onYamlEdit()"></textarea>
      <div id="yamlSaveRow" class="flex hidden" style="margin-top:.4rem">
        <input id="yamlSavePath" type="text" placeholder="/path/to/docker-compose.yml" style="margin:0">
        <button class="btn-ghost btn-sm" onclick="browse('yamlSavePath','save','Save docker-compose.yml',[['YAML','*.yml *.yaml']])">&#128193;</button>
        <button class="btn-primary btn-sm" onclick="doSaveYaml()">Save</button>
        <button class="btn-ghost btn-sm" onclick="hide('yamlSaveRow')">&#x2715;</button>
      </div>
    </div>
  </div>
</div>

<!-- ── Dockerfiles ── -->
<div class="card hidden" id="dockerfilesCard">
  <div class="card-title"><span>Dockerfiles</span></div>
  <div class="df-tabs" id="dfTabs"></div>
  <div id="dfPanels"></div>
</div>

<!-- ── Directory structure ── -->
<div class="card">
  <div class="card-title"><span>Project Structure</span></div>
  <div class="row2">
    <div>
      <div class="pane-head"><span class="pane-label">Source</span></div>
      <div class="dir-tree" id="sourceTree"><span class="tree-note">No compose file loaded yet</span></div>
    </div>
    <div>
      <div class="pane-head"><span class="pane-label">Mender Output</span></div>
      <div class="dir-tree" id="outputTree"><span class="tree-note">Configure output directory below</span></div>
    </div>
  </div>
</div>

<!-- ── Build configuration ── -->
<div class="card">
  <div class="card-title"><span>Build &amp; Artifact Configuration</span></div>
  <label>Target Architecture</label>
  <select id="architecture">
    <option value="linux/arm64">linux/arm64 — 64-bit ARM</option>
    <option value="linux/amd64">linux/amd64 — x86-64</option>
    <option value="linux/arm/v7">linux/arm/v7 — 32-bit ARMv7</option>
    <option value="linux/arm/v6">linux/arm/v6 — 32-bit ARMv6</option>
  </select>
  <hr class="divider">
  <div class="row2">
    <div>
      <label>Artifact Name</label>
      <input id="artifactName" type="text" placeholder="my-project-v1.0.0">
    </div>
    <div>
      <label>Project Name <small>(a-z 0-9 _ -)</small></label>
      <input id="projectName" type="text" placeholder="my-project">
    </div>
  </div>
  <div class="row2">
    <div>
      <label>Device Type</label>
      <input id="deviceType" type="text" placeholder="automotive-infotainment-lite">
    </div>
    <div>
      <label>Output Directory</label>
      <div class="flex" style="margin-bottom:.8rem">
        <input id="outputDir" type="text" placeholder="/tmp/mender-bundle" style="margin:0" oninput="updateTrees()">
        <button class="btn-ghost btn-sm" onclick="browse('outputDir','directory','Select output directory')">&#128193;</button>
      </div>
    </div>
  </div>
  <p class="notice">Images → output-dir/images/ &nbsp;|&nbsp; Manifest → output-dir/manifests/</p>
  <button class="btn-primary" id="buildBtn" onclick="startBuild()">&#9654; Build &amp; Bundle</button>
</div>

<!-- ── Build output ── -->
<div class="card hidden" id="logCard">
  <div class="card-title"><span>Build Output</span></div>
  <div class="log" id="log"></div>
  <div class="status-bar">
    <div class="dot" id="statusDot"></div>
    <span id="statusText">Starting…</span>
  </div>
</div>

</main>
<script>
// ── Global state ──────────────────────────────────────────────────────────────
let _svcSeq = 0, _netSeq = 0;
let _localImages = null;
const _remoteImages = {};
let _yamlDirty = false;   // true when textarea was manually edited

// ── Image combobox ────────────────────────────────────────────────────────────
async function initImageCombo(id) {
  if (!_localImages) {
    try { const r = await fetch('/images/local'); _localImages = await r.json(); }
    catch(_) { _localImages = []; }
  }
  renderDrop(id, _localImages, _remoteImages[id] || []);
}
function filterImages(id, val) {
  const v = val.toLowerCase();
  renderDrop(id, (_localImages||[]).filter(i=>!v||i.toLowerCase().includes(v)),
                 (_remoteImages[id]||[]).filter(i=>!v||i.toLowerCase().includes(v)));
  openDrop(id);
}
async function searchRemote(id) {
  const term = document.getElementById(`sc-image-${id}`).value.trim();
  if (!term) { alert('Type a search term first'); return; }
  const ul = document.getElementById(`imgdrop-${id}`);
  ul.innerHTML = '<li class="img-msg">Searching Docker Hub…</li>'; openDrop(id);
  try {
    const r = await fetch(`/images/search?q=${encodeURIComponent(term)}`);
    _remoteImages[id] = await r.json(); filterImages(id, term);
  } catch(_) { ul.innerHTML = '<li class="img-msg">Search failed</li>'; }
}
function renderDrop(id, locals, remotes) {
  const ul = document.getElementById(`imgdrop-${id}`); if (!ul) return;
  ul.innerHTML = '';
  const grp = (label, items) => {
    if (!items.length) return;
    const g = document.createElement('li'); g.className='img-group-label'; g.textContent=label; ul.appendChild(g);
    items.forEach(img => { const li=document.createElement('li'); li.className='img-option'; li.textContent=img; li.onmousedown=()=>selectImage(id,img); ul.appendChild(li); });
  };
  grp('Local', locals); grp('Docker Hub', remotes);
  if (!locals.length && !remotes.length) {
    const li=document.createElement('li'); li.className='img-msg'; li.textContent='No results — try Search Hub'; ul.appendChild(li);
  }
}
function selectImage(id, img) { document.getElementById(`sc-image-${id}`).value=img; closeDrop(id); onChange(); }
function openDrop(id)  { document.getElementById(`imgdrop-${id}`)?.classList.add('open'); }
function closeDrop(id) { document.getElementById(`imgdrop-${id}`)?.classList.remove('open'); }
function navigateDrop(e, id) {
  const ul=document.getElementById(`imgdrop-${id}`); if(!ul) return;
  const items=[...ul.querySelectorAll('.img-option')], cur=ul.querySelector('.focused');
  if (e.key==='ArrowDown'||e.key==='ArrowUp') {
    e.preventDefault();
    let i=items.indexOf(cur); i=e.key==='ArrowDown'?Math.min(i+1,items.length-1):Math.max(i-1,0);
    items.forEach(x=>x.classList.remove('focused')); items[i]?.classList.add('focused'); items[i]?.scrollIntoView({block:'nearest'});
  } else if (e.key==='Enter'&&cur) { e.preventDefault(); selectImage(id, cur.textContent); }
  else if (e.key==='Escape') closeDrop(id);
}

// ── File picker ───────────────────────────────────────────────────────────────
async function browse(targetId, type, title, filetypes) {
  const cur = document.getElementById(targetId)?.value?.trim();
  const initialDir = cur ? (type==='directory' ? cur : cur.replace(/\/[^/]+$/,'')) : '';
  try {
    const r = await fetch('/browse', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({type, title, initialDir, filetypes: filetypes||[]})});
    const {path, error} = await r.json();
    if (error) { alert('Picker error: '+error); return; }
    if (path) { document.getElementById(targetId).value = path; onChange(); }
  } catch(e) { alert('Browse failed: '+e.message); }
}

// ── Service cards ─────────────────────────────────────────────────────────────
function addServiceCard(prefill={}) {
  const id = ++_svcSeq;
  const d = document.createElement('div');
  d.className='svc-card'; d.id=`sc-${id}`;
  d.innerHTML = `
    <div class="svc-card-head" onclick="toggleCard(${id})">
      <span class="svc-card-label" id="sc-label-${id}">${prefill.name||'Service '+id}</span>
      <span class="badge ${prefill.type==='build'?'badge-build':prefill.type==='tar'?'badge-tar':'badge-image'}" id="sc-badge-${id}">${prefill.type||'image'}</span>
      <button class="btn-danger btn-xs" onclick="event.stopPropagation();removeCard(${id})">Remove</button>
    </div>
    <div class="svc-card-body ${prefill._open!==false?'open':''}" id="sc-body-${id}">
      <div class="row2">
        <div><label>Service Name</label>
          <input type="text" id="sc-name-${id}" placeholder="my-service" value="${prefill.name||''}"
            oninput="document.getElementById('sc-label-${id}').textContent=this.value||'Service ${id}';onChange()">
        </div>
        <div><label>Type</label>
          <select id="sc-type-${id}" onchange="toggleSvcType(${id});onChange()">
            <option value="image" ${prefill.type==='image'||!prefill.type?'selected':''}>Image (local or registry)</option>
            <option value="build" ${prefill.type==='build'?'selected':''}>Dockerfile Build</option>
            <option value="tar"   ${prefill.type==='tar'?'selected':''}>Pre-exported Tar</option>
          </select>
        </div>
      </div>

      <div id="sc-image-fields-${id}" class="${prefill.type==='build'?'hidden':''}">
        <label>Image</label>
        <div class="img-wrap">
          <div class="img-combo">
            <input type="text" id="sc-image-${id}" placeholder="Type to filter or search…"
              value="${prefill.image||''}" autocomplete="off"
              oninput="filterImages(${id},this.value);onChange()"
              onfocus="openDrop(${id})" onblur="setTimeout(()=>closeDrop(${id}),160)"
              onkeydown="navigateDrop(event,${id})">
            <ul class="img-dropdown" id="imgdrop-${id}"></ul>
          </div>
          <button class="btn-ghost btn-sm" onclick="searchRemote(${id})">&#128269; Hub</button>
        </div>
      </div>

      <div id="sc-build-fields-${id}" class="${prefill.type==='build'?'':'hidden'}">
        <div class="row2">
          <div><label>Build Context Path</label>
            <div class="flex" style="margin-bottom:.8rem">
              <input type="text" id="sc-ctx-${id}" placeholder="./my-service" style="margin:0"
                value="${prefill.context||''}" oninput="onChange()">
              <button class="btn-ghost btn-sm" onclick="browse('sc-ctx-${id}','directory','Select build context')">&#128193;</button>
            </div>
          </div>
          <div><label>Dockerfile (optional)</label>
            <div class="flex" style="margin-bottom:.8rem">
              <input type="text" id="sc-df-${id}" placeholder="Dockerfile" style="margin:0"
                value="${prefill.dockerfile||''}" oninput="onChange()">
              <button class="btn-ghost btn-sm" onclick="browse('sc-df-${id}','file','Select Dockerfile',[['Dockerfile','Dockerfile*'],['All','*']])">&#128193;</button>
            </div>
          </div>
        </div>
        <label>Image Tag (for export &amp; compose reference)</label>
        <input type="text" id="sc-tag-${id}" placeholder="${prefill.name||'my-service'}:latest"
          value="${prefill.tag||''}" oninput="onChange()">
      </div>

      <div id="sc-tar-fields-${id}" class="${prefill.type==='tar'?'':'hidden'}">
        <label>Tar File Path</label>
        <div class="flex" style="margin-bottom:.8rem">
          <input type="text" id="sc-tar-${id}" placeholder="/path/to/image.tar" style="margin:0"
            value="${prefill.tarPath||''}" oninput="onChange()">
          <button class="btn-ghost btn-sm" onclick="browse('sc-tar-${id}','file','Select image tar',[['Tar','*.tar'],['All','*']])">&#128193;</button>
        </div>
        <label>Image Tag (embedded in tar / compose reference)</label>
        <input type="text" id="sc-tartag-${id}" placeholder="${prefill.name||'my-service'}:latest"
          value="${prefill.tag||''}" oninput="onChange()">
      </div>

      <div class="row2">
        <div><label>Container Name</label>
          <input type="text" id="sc-cname-${id}" placeholder="${prefill.name||'my-service'}"
            value="${prefill.containerName||''}" oninput="onChange()">
        </div>
        <div><label>Restart Policy</label>
          <select id="sc-restart-${id}" onchange="onChange()">
            ${['unless-stopped','always','on-failure','no'].map(v=>`<option value="${v}" ${(prefill.restart||'unless-stopped')===v?'selected':''}>${v}</option>`).join('')}
          </select>
        </div>
      </div>

      <div class="sec-label">Environment Variables</div>
      <div id="sc-envs-${id}"></div>
      <button class="btn-ghost btn-xs" onclick="addKV('sc-envs-${id}','KEY','value')" style="margin-bottom:.5rem">+ Add Env Var</button>

      <div class="sec-label">Volumes (host:container)</div>
      <div id="sc-vols-${id}"></div>
      <button class="btn-ghost btn-xs" onclick="addKV('sc-vols-${id}','/host/path','/container/path')" style="margin-bottom:.5rem">+ Add Volume</button>

      <div class="sec-label">Networks</div>
      <input type="text" id="sc-nets-${id}" placeholder="net1, net2" style="margin-bottom:0"
        value="${(prefill.networks||[]).join(', ')}" oninput="onChange()">
    </div>`;
  document.getElementById('svcCards').appendChild(d);

  // prefill env vars
  (prefill.envVars||[]).forEach(e => { addKV(`sc-envs-${id}`, 'KEY', 'value', e.key, e.value); });
  (prefill.volumes||[]).forEach(v => { addKV(`sc-vols-${id}`, '/host/path', '/container/path', v.host, v.container); });

  initImageCombo(id);
  updateDockerfileTabs();
  return id;
}

function removeCard(id) {
  document.getElementById(`sc-${id}`).remove();
  updateDockerfileTabs(); onChange();
}
function toggleCard(id) { document.getElementById(`sc-body-${id}`).classList.toggle('open'); }
function toggleSvcType(id) {
  const type = document.getElementById(`sc-type-${id}`).value;
  document.getElementById(`sc-image-fields-${id}`).classList.toggle('hidden', type!=='image');
  document.getElementById(`sc-build-fields-${id}`).classList.toggle('hidden', type!=='build');
  document.getElementById(`sc-tar-fields-${id}`).classList.toggle('hidden', type!=='tar');
  const cls = type==='build'?'badge-build':type==='tar'?'badge-tar':'badge-image';
  document.getElementById(`sc-badge-${id}`).className=`badge ${cls}`;
  document.getElementById(`sc-badge-${id}`).textContent=type;
  updateDockerfileTabs();
}
function addKV(cid, phK, phV, valK='', valV='') {
  const row=document.createElement('div'); row.className='kv-row';
  row.innerHTML=`<input type="text" placeholder="${phK}" value="${valK}" style="margin:0" oninput="onChange()">
                 <input type="text" placeholder="${phV}" value="${valV}" style="margin:0" oninput="onChange()">
                 <button class="btn-danger btn-xs" onclick="this.parentElement.remove();onChange()">×</button>`;
  document.getElementById(cid).appendChild(row);
}
function addNetRow(prefill={}) {
  const id=++_netSeq, row=document.createElement('div');
  row.id=`nr-${id}`;
  row.style='display:grid;grid-template-columns:1fr 110px 90px auto;gap:.35rem;align-items:center;margin-bottom:.35rem';
  row.innerHTML=`<input type="text" placeholder="network-name" value="${prefill.name||''}" style="margin:0" oninput="onChange()">
                 <select style="margin:0" onchange="onChange()">${['bridge','host','overlay'].map(v=>`<option ${prefill.driver===v?'selected':''}>${v}</option>`).join('')}</select>
                 <select style="margin:0" onchange="onChange()"><option value="0" ${!prefill.external?'selected':''}>owned</option><option value="1" ${prefill.external?'selected':''}>external</option></select>
                 <button class="btn-danger btn-xs" onclick="document.getElementById('nr-${id}').remove();onChange()">×</button>`;
  document.getElementById('netRows').appendChild(row);
}

// ── Collect form state ────────────────────────────────────────────────────────
function collectServices() {
  return [...document.querySelectorAll('.svc-card')].map(card => {
    const id = card.id.replace('sc-','');
    const type = document.getElementById(`sc-type-${id}`).value;
    const tag = type==='tar'
      ? (document.getElementById(`sc-tartag-${id}`)?.value.trim() || '')
      : (document.getElementById(`sc-tag-${id}`)?.value.trim() || '');
    return {
      name:          document.getElementById(`sc-name-${id}`).value.trim(),
      type,
      image:         document.getElementById(`sc-image-${id}`)?.value.trim() || '',
      context:       document.getElementById(`sc-ctx-${id}`)?.value.trim() || '',
      dockerfile:    document.getElementById(`sc-df-${id}`)?.value.trim() || '',
      tag,
      tarPath:       document.getElementById(`sc-tar-${id}`)?.value.trim() || '',
      containerName: document.getElementById(`sc-cname-${id}`).value.trim(),
      restart:       document.getElementById(`sc-restart-${id}`).value,
      envVars:  [...document.querySelectorAll(`#sc-envs-${id} .kv-row`)].map(r=>{const[k,v]=r.querySelectorAll('input');return{key:k.value.trim(),value:v.value.trim()};}).filter(e=>e.key),
      volumes:  [...document.querySelectorAll(`#sc-vols-${id} .kv-row`)].map(r=>{const[k,v]=r.querySelectorAll('input');return{host:k.value.trim(),container:v.value.trim()};}).filter(v=>v.host),
      networks: document.getElementById(`sc-nets-${id}`).value.split(',').map(s=>s.trim()).filter(Boolean),
    };
  });
}
function collectNetworks() {
  return [...document.querySelectorAll('#netRows > div')].map(row=>{
    const[ni]=row.querySelectorAll('input'), [ds,es]=row.querySelectorAll('select');
    return {name:ni.value.trim(), driver:ds.value, external:es.value==='1'};
  }).filter(n=>n.name);
}

// ── YAML sync ────────────────────────────────────────────────────────────────
let _yamlTimer = null;
function onChange() {
  clearTimeout(_yamlTimer);
  _yamlTimer = setTimeout(() => { refreshYaml(); updateTrees(); }, 300);
}
function onYamlEdit() { _yamlDirty = true; updateTrees(); }

function refreshYaml() {
  _yamlDirty = false;
  const doc = buildYamlDoc(collectServices(), collectNetworks());
  document.getElementById('yamlEditor').value = jsYaml(doc, 0).trim();
}

async function applyYaml() {
  const content = document.getElementById('yamlEditor').value.trim();
  if (!content) return;
  try {
    const r = await fetch('/parse-yaml', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({content})});
    const {services, networks, error} = await r.json();
    if (error) { alert('YAML parse error: '+error); return; }
    rebuildFromParsed(services, networks);
  } catch(e) { alert('Request failed: '+e.message); }
}

function saveYamlToFile() {
  const row = document.getElementById('yamlSaveRow');
  row.classList.toggle('hidden');
  if (!row.classList.contains('hidden')) {
    const imp = document.getElementById('importPath').value.trim();
    if (imp) document.getElementById('yamlSavePath').value = imp;
  }
}
async function doSaveYaml() {
  const path = document.getElementById('yamlSavePath').value.trim();
  const content = document.getElementById('yamlEditor').value;
  if (!path) { alert('Enter a save path'); return; }
  try {
    const r = await fetch('/write-file', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({path, content})});
    const {error} = await r.json();
    if (error) { alert('Save error: '+error); return; }
    hide('yamlSaveRow');
    document.getElementById('importPath').value = path;
    updateTrees();
  } catch(e) { alert('Save failed: '+e.message); }
}

// ── Import ────────────────────────────────────────────────────────────────────
async function importCompose() {
  const path = document.getElementById('importPath').value.trim();
  if (!path) { alert('Enter a path to docker-compose.yml'); return; }
  try {
    const r = await fetch('/read-file', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({path})});
    const {content, error} = await r.json();
    if (error) { alert('Read error: '+error); return; }

    // Fill YAML editor
    document.getElementById('yamlEditor').value = content;
    _yamlDirty = false;

    // Parse and populate visual builder
    const r2 = await fetch('/parse-yaml', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({content})});
    const {services, networks, error: e2} = await r2.json();
    if (e2) { alert('Parse error: '+e2); return; }
    rebuildFromParsed(services, networks);

    // Auto-fill artifact settings from file path
    const parts = path.replace(/\\/g,'/').split('/');
    const dir   = parts.slice(0,-1).join('/');
    const guess = parts.slice(-3,-2)[0] || parts.slice(-2,-1)[0] || 'my-project';
    const slug  = guess.replace(/[^a-zA-Z0-9_-]/g,'-');
    if (!document.getElementById('projectName').value)  document.getElementById('projectName').value = slug;
    if (!document.getElementById('artifactName').value) document.getElementById('artifactName').value = slug+'-v1.0.0';
    if (!document.getElementById('outputDir').value)    document.getElementById('outputDir').value = dir+'/mender-output';

    updateTrees();
  } catch(e) { alert('Import failed: '+e.message); }
}

function rebuildFromParsed(services, networks) {
  // Clear existing cards and networks
  document.getElementById('svcCards').innerHTML = '';
  document.getElementById('netRows').innerHTML = '';
  _svcSeq = 0; _netSeq = 0;

  services.forEach(svc => addServiceCard({...svc, _open: false}));
  networks.forEach(net => addNetRow(net));
  refreshYaml();
  updateDockerfileTabs();
}

// ── Dockerfile tabs ───────────────────────────────────────────────────────────
const _dfContents = {};   // {cardId: string}

function updateDockerfileTabs() {
  const buildSvcs = [...document.querySelectorAll('.svc-card')].filter(card => {
    const id = card.id.replace('sc-','');
    return document.getElementById(`sc-type-${id}`)?.value === 'build';
  });

  const card = document.getElementById('dockerfilesCard');
  if (!buildSvcs.length) { card.classList.add('hidden'); return; }
  card.classList.remove('hidden');

  const tabsEl   = document.getElementById('dfTabs');
  const panelsEl = document.getElementById('dfPanels');
  const existingIds = new Set([...tabsEl.querySelectorAll('[data-svcid]')].map(t=>t.dataset.svcid));
  const currentIds  = new Set(buildSvcs.map(c=>c.id.replace('sc-','')));

  // Remove stale tabs
  existingIds.forEach(id => {
    if (!currentIds.has(id)) {
      tabsEl.querySelector(`[data-svcid="${id}"]`)?.remove();
      panelsEl.querySelector(`[data-svcid="${id}"]`)?.remove();
    }
  });

  // Add new tabs
  buildSvcs.forEach((card, i) => {
    const id  = card.id.replace('sc-','');
    const name = document.getElementById(`sc-name-${id}`)?.value || `Service ${id}`;
    if (!existingIds.has(id)) {
      const tab = document.createElement('div');
      tab.className = 'df-tab' + (i===0?' active':'');
      tab.dataset.svcid = id;
      tab.textContent = name;
      tab.onclick = () => switchDfTab(id);
      tabsEl.appendChild(tab);

      const panel = document.createElement('div');
      panel.className = 'df-panel' + (i===0?' active':'');
      panel.dataset.svcid = id;
      panel.innerHTML = `
        <div class="df-path">
          <span id="df-path-${id}">No context set</span>
          <button class="btn-ghost btn-xs" onclick="loadDockerfile(${id})">&#8635; Load</button>
          <button class="btn-ghost btn-xs" onclick="saveDockerfile(${id})">&#128190; Save to disk</button>
        </div>
        <textarea class="df-editor" id="df-editor-${id}" placeholder="# Dockerfile&#10;FROM ...&#10;"
          spellcheck="false" onkeydown="dfTabKey(event)">${_dfContents[id]||''}</textarea>`;
      panelsEl.appendChild(panel);
    } else {
      // Update tab label
      tabsEl.querySelector(`[data-svcid="${id}"]`).textContent = name;
    }
    // Update path display
    const ctx = document.getElementById(`sc-ctx-${id}`)?.value || '';
    const df  = document.getElementById(`sc-df-${id}`)?.value || 'Dockerfile';
    const full = ctx ? ctx.replace(/\/$/, '') + '/' + df : '';
    const el = document.getElementById(`df-path-${id}`);
    if (el) el.textContent = full || 'Set build context above';
  });

  // Activate first tab if none active
  if (!tabsEl.querySelector('.df-tab.active')) switchDfTab(buildSvcs[0]?.id.replace('sc-',''));
}

function switchDfTab(id) {
  document.querySelectorAll('.df-tab').forEach(t => t.classList.toggle('active', t.dataset.svcid===String(id)));
  document.querySelectorAll('.df-panel').forEach(p => p.classList.toggle('active', p.dataset.svcid===String(id)));
}

async function loadDockerfile(id) {
  const ctx = document.getElementById(`sc-ctx-${id}`)?.value?.trim();
  const df  = document.getElementById(`sc-df-${id}`)?.value?.trim() || 'Dockerfile';
  if (!ctx) { alert('Set the build context path first'); return; }
  const path = ctx.replace(/\/$/, '') + '/' + df;
  try {
    const r = await fetch('/read-file', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({path})});
    const {content, error} = await r.json();
    if (error) { alert('Could not load: '+error); return; }
    document.getElementById(`df-editor-${id}`).value = content;
    _dfContents[id] = content;
  } catch(e) { alert('Load failed: '+e.message); }
}

async function saveDockerfile(id) {
  const ctx = document.getElementById(`sc-ctx-${id}`)?.value?.trim();
  const df  = document.getElementById(`sc-df-${id}`)?.value?.trim() || 'Dockerfile';
  if (!ctx) { alert('Set the build context path first'); return; }
  const path = ctx.replace(/\/$/, '') + '/' + df;
  const content = document.getElementById(`df-editor-${id}`).value;
  try {
    const r = await fetch('/write-file', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({path, content})});
    const {error} = await r.json();
    if (error) alert('Save error: '+error);
    else alert(`Saved to ${path}`);
  } catch(e) { alert('Save failed: '+e.message); }
}

// ── Directory trees ───────────────────────────────────────────────────────────
function updateTrees() {
  // Source tree
  const importPath = document.getElementById('importPath').value.trim();
  const svcs = collectServices();
  let src = '';
  if (importPath) {
    const dir = importPath.replace(/\/[^/]+$/, '');
    src += `<span class="tree-dir">${dir}/</span>\n`;
    src += `  ├── docker-compose.yml\n`;
    svcs.filter(s=>s.type==='build'&&s.context).forEach(s=>{
      const ctx = s.context.replace(dir+'/', '');
      src += `  ├── <span class="tree-dir">${ctx}/</span>\n`;
      const dfName = s.dockerfile || 'Dockerfile';
      src += `  │   └── ${dfName}\n`;
    });
  } else if (svcs.length) {
    svcs.filter(s=>s.type==='build'&&s.context).forEach(s=>{
      src += `<span class="tree-dir">${s.context}/</span>\n`;
      src += `  └── ${s.dockerfile||'Dockerfile'}\n`;
    });
  } else {
    src = '<span class="tree-note">No compose file loaded</span>';
  }
  document.getElementById('sourceTree').innerHTML = src;

  // Output tree
  const outDir = document.getElementById('outputDir').value.trim();
  const artifact = document.getElementById('artifactName').value.trim();
  if (outDir) {
    let out = `<span class="tree-dir">${outDir}/</span>\n`;
    out += `  ├── <span class="tree-dir">images/</span>\n`;
    svcs.forEach(s => {
      const name = s.name || '…';
      out += `  │   └── <span class="tree-new">${name}.tar</span>\n`;
    });
    out += `  ├── <span class="tree-dir">manifests/</span>\n`;
    out += `  │   └── <span class="tree-new">docker-compose.yml</span>\n`;
    if (artifact) out += `  └── <span class="tree-new">${artifact}.mender</span>\n`;
    document.getElementById('outputTree').innerHTML = out;
  } else {
    document.getElementById('outputTree').innerHTML = '<span class="tree-note">Configure output directory</span>';
  }
}

// ── YAML helpers ──────────────────────────────────────────────────────────────
function buildYamlDoc(svcs, nets) {
  const doc = {services: {}};
  for (const s of svcs) {
    if (!s.name) continue;
    const e = {};
    if (s.type==='build') {
      e.build = {context: s.context||'.'};
      if (s.dockerfile) e.build.dockerfile = s.dockerfile;
      if (s.tag) e.image = s.tag;
    } else if (s.type==='tar') {
      // tar: compose uses image: tag (the tar is loaded on the device from images/)
      if (s.tag) e.image = s.tag;
    } else {
      if (s.image) e.image = s.image;
    }
    if (s.containerName) e.container_name = s.containerName;
    if (s.restart&&s.restart!=='unless-stopped') e.restart = s.restart;
    else if (s.restart==='unless-stopped') e.restart = s.restart;
    const envs = (s.envVars||[]).filter(v=>v.key).map(v=>`${v.key}=${v.value}`);
    if (envs.length) e.environment = envs;
    const vols = (s.volumes||[]).filter(v=>v.host).map(v=>`${v.host}:${v.container}`);
    if (vols.length) e.volumes = vols;
    if (s.networks?.length) e.networks = s.networks;
    doc.services[s.name] = e;
  }
  if (nets.length) {
    doc.networks = {};
    for (const n of nets) {
      if (!n.name) continue;
      doc.networks[n.name] = n.external ? {external: true} : {name:n.name, driver:n.driver||'bridge'};
    }
  }
  return doc;
}

function jsYaml(obj, indent) {
  const sp = '  '.repeat(indent);
  if (obj===null||obj===undefined) return 'null';
  if (typeof obj==='boolean'||typeof obj==='number') return String(obj);
  if (typeof obj==='string') {
    if (obj==='') return "''";
    if (/[:{}\[\],#&*?|!%@`]/.test(obj)||/^\s|\s$/.test(obj)||obj.includes('\n')) return `"${obj.replace(/\\/g,'\\\\').replace(/"/g,'\\"').replace(/\n/g,'\\n')}"`;
    return obj;
  }
  if (Array.isArray(obj)) {
    if (!obj.length) return '[]';
    return obj.map(v=>`\n${sp}- ${jsYaml(v,indent+1)}`).join('');
  }
  if (typeof obj==='object') {
    const ents=Object.entries(obj).filter(([,v])=>v!==undefined&&v!==null&&!(Array.isArray(v)&&!v.length));
    if (!ents.length) return '{}';
    return ents.map(([k,v])=>{
      const r=jsYaml(v,indent+1);
      if (Array.isArray(v)&&v.length) return `\n${sp}${k}:${r}`;
      if (typeof v==='object'&&v!==null&&!Array.isArray(v)) return `\n${sp}${k}:${r}`;
      return `\n${sp}${k}: ${r}`;
    }).join('');
  }
  return String(obj);
}

function yamlTabKey(e) {
  if (e.key!=='Tab') return;
  e.preventDefault();
  const t=e.target, s=t.selectionStart, end=t.selectionEnd;
  t.value=t.value.substring(0,s)+'  '+t.value.substring(end);
  t.selectionStart=t.selectionEnd=s+2;
}
function dfTabKey(e) {
  if (e.key!=='Tab') return;
  e.preventDefault();
  const t=e.target, s=t.selectionStart, end=t.selectionEnd;
  t.value=t.value.substring(0,s)+'    '+t.value.substring(end);
  t.selectionStart=t.selectionEnd=s+4;
}

// ── Build pipeline ────────────────────────────────────────────────────────────
async function startBuild() {
  // Derive compose path for the build job
  const composeSavePath = document.getElementById('importPath').value.trim()
    || document.getElementById('yamlSavePath').value.trim();

  if (!composeSavePath) {
    // Save YAML to a temp path under outputDir first
    const outDir = document.getElementById('outputDir').value.trim();
    if (!outDir) { alert('Set the output directory first'); return; }
    const tmpPath = outDir + '/docker-compose.yml';
    const r = await fetch('/write-file', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({path: tmpPath, content: document.getElementById('yamlEditor').value})});
    const {error} = await r.json();
    if (error) { alert('Could not save compose file: '+error); return; }
    document.getElementById('importPath').value = tmpPath;
  } else {
    // Save current YAML editor content to that path
    const r = await fetch('/write-file', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({path: composeSavePath, content: document.getElementById('yamlEditor').value})});
    const {error} = await r.json();
    if (error) { alert('Could not save compose file: '+error); return; }
  }

  const params = {
    composePath:  document.getElementById('importPath').value.trim(),
    architecture: document.getElementById('architecture').value,
    artifactName: document.getElementById('artifactName').value.trim(),
    projectName:  document.getElementById('projectName').value.trim(),
    deviceType:   document.getElementById('deviceType').value.trim(),
    outputDir:    document.getElementById('outputDir').value.trim(),
    // Pass services explicitly so the backend has tarPath (not present in compose YAML)
    services: collectServices().map(s => ({
      name: s.name, type: s.type,
      image: s.image, tag: s.tag,
      context: s.context, dockerfile: s.dockerfile,
      tarPath: s.tarPath || '',
    })),
  };
  for (const [k,v] of Object.entries(params)) {
    if (!v) { alert('Please fill in all fields ('+k+')'); return; }
  }
  document.getElementById('buildBtn').disabled = true;
  clearLog(); show('logCard'); setStatus('running','Building…');

  const r = await fetch('/start', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(params)});
  const {jobId, error} = await r.json();
  if (error) { appendLog(error,'err'); setStatus('error','Failed to start'); return; }

  const es = new EventSource('/stream/'+jobId);
  es.onmessage = e => { const {line,kind}=JSON.parse(e.data); appendLog(line,kind); };
  es.addEventListener('done', e => {
    es.close();
    const {status,artifact}=JSON.parse(e.data);
    setStatus(status==='success'?'success':'error', status==='success'?'Artifact ready → '+artifact:'Build failed — check log');
    document.getElementById('buildBtn').disabled=false;
    if (status==='success') updateTrees();
  });
  es.onerror=()=>{ es.close(); setStatus('error','Connection lost'); document.getElementById('buildBtn').disabled=false; };
}

// ── Utilities ─────────────────────────────────────────────────────────────────
function appendLog(text,kind='') {
  const log=document.getElementById('log'), span=document.createElement('span');
  if(kind) span.className=kind; span.textContent=text+'\n'; log.appendChild(span); log.scrollTop=log.scrollHeight;
}
function clearLog()  { document.getElementById('log').innerHTML=''; }
function setStatus(state,text) {
  document.getElementById('statusDot').className='dot '+state;
  document.getElementById('statusText').textContent=text;
}
function show(id) { document.getElementById(id).classList.remove('hidden'); }
function hide(id) { document.getElementById(id).classList.add('hidden'); }
</script>
</body>
</html>
"""

# ── Compose parsing ───────────────────────────────────────────────────────────

def parse_compose_file(path: str) -> list:
    with open(path) as f:
        return _parse_compose_data(yaml.safe_load(f), Path(path).parent)

def parse_compose_string(content: str) -> dict:
    data = yaml.safe_load(content)
    services, networks = [], []

    for name, svc in (data.get("services") or {}).items():
        if not svc:
            continue
        build, image = svc.get("build"), svc.get("image")
        entry = {"name": name}
        if build:
            context = build if isinstance(build, str) else build.get("context", ".")
            dockerfile = build.get("dockerfile") if isinstance(build, dict) else ""
            entry.update({"type": "build", "context": context, "dockerfile": dockerfile or "",
                           "tag": image or f"{name}:latest", "image": ""})
        elif image:
            entry.update({"type": "image", "image": image, "context": "", "dockerfile": "", "tag": ""})
        else:
            continue

        entry["containerName"] = svc.get("container_name", "")
        entry["restart"] = svc.get("restart", "unless-stopped")

        env = svc.get("environment", [])
        if isinstance(env, list):
            entry["envVars"] = [{"key": e.split("=", 1)[0], "value": e.split("=", 1)[1] if "=" in e else ""} for e in env]
        elif isinstance(env, dict):
            entry["envVars"] = [{"key": k, "value": str(v)} for k, v in env.items()]
        else:
            entry["envVars"] = []

        vols = svc.get("volumes", [])
        entry["volumes"] = []
        for v in (vols if isinstance(vols, list) else []):
            if isinstance(v, str):
                p = v.split(":", 1)
                entry["volumes"].append({"host": p[0], "container": p[1] if len(p) > 1 else p[0]})
            elif isinstance(v, dict):
                entry["volumes"].append({"host": v.get("source", ""), "container": v.get("target", "")})

        nets = svc.get("networks", [])
        entry["networks"] = list(nets.keys()) if isinstance(nets, dict) else (nets if isinstance(nets, list) else [])
        services.append(entry)

    for net_name, net_def in (data.get("networks") or {}).items():
        nd = net_def or {}
        networks.append({"name": net_name, "driver": nd.get("driver", "bridge"), "external": bool(nd.get("external", False))})

    return {"services": services, "networks": networks}

def _parse_compose_data(data, compose_dir: Path) -> list:
    services = []
    for name, svc in (data.get("services") or {}).items():
        if not svc:
            continue
        build, image = svc.get("build"), svc.get("image")
        if build:
            context = build if isinstance(build, str) else build.get("context", ".")
            context = str((compose_dir / context).resolve())
            dockerfile = build.get("dockerfile") if isinstance(build, dict) else None
            services.append({"name": name, "type": "build", "source": f"Dockerfile @ {context}",
                              "tag": image or f"{name}:latest", "context": context, "dockerfile": dockerfile})
        elif image:
            services.append({"name": name, "type": "image", "source": image, "tag": image})
    return services

# ── Compose generation ────────────────────────────────────────────────────────

def generate_compose_yaml(services: list, networks: list) -> str:
    doc: dict = {"services": {}}
    for svc in services:
        name = svc["name"]
        entry: dict = {}
        if svc["type"] == "build":
            build_def: dict = {"context": svc["context"]}
            if svc.get("dockerfile"):
                build_def["dockerfile"] = svc["dockerfile"]
            entry["build"] = build_def
            if svc.get("tag"):
                entry["image"] = svc["tag"]
        else:
            entry["image"] = svc["image"]
        if svc.get("containerName"):
            entry["container_name"] = svc["containerName"]
        if svc.get("restart"):
            entry["restart"] = svc["restart"]
        envs = [f"{e['key']}={e['value']}" for e in svc.get("envVars", []) if e.get("key")]
        if envs:
            entry["environment"] = envs
        vols = [f"{v['host']}:{v['container']}" for v in svc.get("volumes", []) if v.get("host")]
        if vols:
            entry["volumes"] = vols
        if svc.get("networks"):
            entry["networks"] = svc["networks"]
        doc["services"][name] = entry
    if networks:
        doc["networks"] = {}
        for net in networks:
            net_name = net["name"]
            if net.get("external"):
                doc["networks"][net_name] = {"external": True}
            else:
                doc["networks"][net_name] = {"name": net_name, "driver": net.get("driver", "bridge")}
    return yaml.dump(doc, default_flow_style=False, sort_keys=False, allow_unicode=True)

# ── Build pipeline ────────────────────────────────────────────────────────────

def _run(cmd: list, q: queue.Queue, cwd: str = None) -> int:
    q.put(("info", "$ " + " ".join(cmd)))
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=cwd)
    for line in proc.stdout:
        q.put(("", line.rstrip()))
    proc.wait()
    return proc.returncode

def run_build_job(job_id: str, params: dict):
    job = _jobs[job_id]
    q: queue.Queue = job["queue"]

    def emit(msg, kind=""):
        q.put((kind, msg))

    try:
        compose_path  = params["composePath"]
        architecture  = params["architecture"]
        artifact_name = params["artifactName"]
        project_name  = params["projectName"]
        device_type   = params["deviceType"]
        output_dir    = Path(params["outputDir"])

        if re.search(r"[^a-zA-Z0-9_-]", project_name):
            raise ValueError(f"Project name '{project_name}' must contain only a-z A-Z 0-9 _ -")

        images_dir    = output_dir / "images"
        manifests_dir = output_dir / "manifests"
        images_dir.mkdir(parents=True, exist_ok=True)
        manifests_dir.mkdir(parents=True, exist_ok=True)

        # Use the services array from the frontend if provided — it carries tarPath
        # and the original type, which are not present in the compose YAML.
        if params.get("services"):
            services = params["services"]
            emit(f"Using {len(services)} service(s) from editor", "info")
        else:
            emit(f"Parsing {compose_path}", "info")
            services = _parse_compose_data(
                yaml.safe_load(Path(compose_path).read_text()), Path(compose_path).parent
            )
            emit(f"Found {len(services)} service(s)", "info")

        shutil.copy2(compose_path, manifests_dir / "docker-compose.yml")
        emit(f"Manifest copied → {manifests_dir}/", "info")

        for svc in services:
            name = svc.get("name") or svc.get("name", "unknown")
            svc_type = svc.get("type", "image")
            emit(f"\n── {name} ({svc_type}) {'─'*40}", "info")

            safe = re.sub(r"[^a-zA-Z0-9_-]", "_", name)
            tar  = images_dir / f"{safe}.tar"

            if svc_type == "tar":
                tar_src = svc.get("tarPath", "").strip()
                if not tar_src:
                    raise RuntimeError(f"No tar path set for service '{name}'")
                if not os.path.isfile(tar_src):
                    raise RuntimeError(f"Tar file not found: {tar_src}")
                emit(f"Copying {tar_src} → {tar}", "info")
                shutil.copy2(tar_src, tar)

            elif svc_type == "build":
                tag = svc.get("tag") or name + ":latest"
                cmd = ["docker", "buildx", "build", "--platform", architecture, "--load", "-t", tag]
                if svc.get("dockerfile"):
                    cmd += ["-f", svc["dockerfile"]]
                ctx = svc.get("context", ".")
                cmd.append(ctx)
                if _run(cmd, q, cwd=ctx) != 0:
                    raise RuntimeError(f"Build failed for '{name}'")
                emit(f"Exporting → {tar}", "info")
                if _run(["docker", "save", tag, "-o", str(tar)], q) != 0:
                    raise RuntimeError(f"Export failed for '{name}'")

            else:  # image type — local first, fall back to pull
                tag = svc.get("tag") or svc.get("image") or name + ":latest"
                check = subprocess.run(
                    ["docker", "images", "-q", tag],
                    capture_output=True, text=True, timeout=10,
                )
                if check.stdout.strip():
                    emit(f"Image {tag} found locally — skipping pull", "info")
                else:
                    emit(f"Image not found locally — pulling {tag}", "info")
                    if _run(["docker", "pull", "--platform", architecture, tag], q) != 0:
                        raise RuntimeError(f"Pull failed for '{name}': {tag}")
                emit(f"Exporting → {tar}", "info")
                if _run(["docker", "save", tag, "-o", str(tar)], q) != 0:
                    raise RuntimeError(f"Export failed for '{name}'")

        artifact_path = str(output_dir / f"{artifact_name}.mender")
        emit("\n── Bundling Mender artifact ──────────────────────────────", "info")
        if _run(["gen_docker-compose", "--artifact-name", artifact_name, "--device-type", device_type,
                 "--project-name", project_name, "--manifests-dir", str(manifests_dir),
                 "--images-dir", str(images_dir), "--output-path", artifact_path], q) != 0:
            raise RuntimeError("gen_docker-compose failed")

        emit(f"\nArtifact ready: {artifact_path}", "ok")
        job["status"] = "success"; job["artifact"] = artifact_path

    except Exception as exc:
        emit(f"\n{exc}", "err")
        job["status"] = "error"; job["artifact"] = ""
    finally:
        q.put(None)

# ── HTTP handler ──────────────────────────────────────────────────────────────

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass

    def send_json(self, data, code=200):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length))

    def do_GET(self):
        if self.path == "/":
            body = HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif self.path.startswith("/stream/"):
            job_id = self.path[len("/stream/"):]
            if job_id not in _jobs:
                self.send_json({"error": "Job not found"}, 404); return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            q = _jobs[job_id]["queue"]
            try:
                while True:
                    try:
                        item = q.get(timeout=25)
                    except queue.Empty:
                        self.wfile.write(b": heartbeat\n\n"); self.wfile.flush(); continue
                    if item is None:
                        job = _jobs[job_id]
                        payload = json.dumps({"status": job["status"], "artifact": job["artifact"]})
                        self.wfile.write(f"event: done\ndata: {payload}\n\n".encode())
                        self.wfile.flush(); break
                    kind, line = item
                    data = json.dumps({"line": line, "kind": kind})
                    self.wfile.write(f"data: {data}\n\n".encode()); self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError): pass

        elif self.path == "/images/local":
            try:
                result = subprocess.run(["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"],
                    capture_output=True, text=True, timeout=10)
                images = sorted(set(l.strip() for l in result.stdout.splitlines()
                    if l.strip() and "<none>" not in l))
                self.send_json(images)
            except Exception: self.send_json([])

        elif self.path.startswith("/images/search"):
            q = parse_qs(urlparse(self.path).query).get("q", [""])[0].strip()
            if not q: self.send_json([]); return
            try:
                result = subprocess.run(["docker", "search", "--format", "{{.Name}}", "--limit", "25", q],
                    capture_output=True, text=True, timeout=20)
                self.send_json([l.strip() for l in result.stdout.splitlines() if l.strip()])
            except Exception: self.send_json([])

        else:
            self.send_json({"error": "Not found"}, 404)

    def do_POST(self):
        if self.path == "/browse":
            try:
                body = self.read_json()
                path = browse_dialog(body.get("type","file"), body.get("title","Select"),
                    body.get("initialDir",""), body.get("filetypes",[]))
                if path == "__unavailable__":
                    self.send_json({"path":"","error":"tkinter not available — install python3-tk"})
                else:
                    self.send_json({"path": path})
            except Exception as exc: self.send_json({"path":"","error":str(exc)})

        elif self.path == "/read-file":
            try:
                body = self.read_json()
                content = Path(body["path"]).read_text(encoding="utf-8", errors="replace")
                self.send_json({"content": content})
            except FileNotFoundError:
                self.send_json({"content":"","error":"File not found"})
            except Exception as exc:
                self.send_json({"content":"","error":str(exc)})

        elif self.path == "/write-file":
            try:
                body = self.read_json()
                p = Path(body["path"])
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(body["content"], encoding="utf-8")
                self.send_json({"ok": True})
            except Exception as exc:
                self.send_json({"ok":False,"error":str(exc)})

        elif self.path == "/parse-yaml":
            try:
                body = self.read_json()
                result = parse_compose_string(body["content"])
                self.send_json(result)
            except Exception as exc:
                self.send_json({"services":[],"networks":[],"error":str(exc)})

        elif self.path == "/parse":
            try:
                body = self.read_json()
                self.send_json({"services": parse_compose_file(body["path"])})
            except FileNotFoundError:
                self.send_json({"error":"File not found"})
            except Exception as exc:
                self.send_json({"error":str(exc)})

        elif self.path == "/start":
            try:
                params = self.read_json()
                job_id = uuid.uuid4().hex[:10]
                _jobs[job_id] = {"queue": queue.Queue(), "status": "running", "artifact": ""}
                threading.Thread(target=run_build_job, args=(job_id, params), daemon=True).start()
                self.send_json({"jobId": job_id})
            except Exception as exc:
                self.send_json({"error":str(exc)})

        else:
            self.send_json({"error": "Not found"}, 404)

# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Mender Artifact Bundle GUI")
    ap.add_argument("--port", type=int, default=8888, help="Port (default: 8888)")
    ap.add_argument("--no-browser", action="store_true", help="Do not open browser automatically")
    args = ap.parse_args()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://localhost:{args.port}"
    print(f"Mender Bundle GUI → {url}"); print("Ctrl+C to stop\n")
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try: server.serve_forever()
    except KeyboardInterrupt: print("\nStopped.")

if __name__ == "__main__":
    main()

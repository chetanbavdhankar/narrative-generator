"""Interactive web UI for the KRI/KPI context builder.

Run: python app.py --port 5000
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

from flask import Flask, jsonify, request, Response

from core import (
    resolve_quarter, load_tables, filter_kris, enrich_kpis,
    build_output, extract_combo_from_filename
)

app = Flask(__name__)


# ── Folder picker (Isolated subprocess to avoid Tkinter thread deadlocks) ──

def _pick_folder() -> str:
    """Launch Tkinter folder dialog in a separate subprocess so Flask never hangs."""
    script = (
        "import tkinter as tk, tkinter.filedialog as fd; "
        "root=tk.Tk(); root.withdraw(); root.attributes('-topmost', True); "
        "d=fd.askdirectory(title='Select Folder'); print(d); root.destroy()"
    )
    try:
        res = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return res.stdout.strip()
    except Exception as e:
        print(f"[Browse Error] {e}")
        return ""


# ── API routes ──────────────────────────────────────────────────────────────

@app.get("/api/browse")
def browse():
    """Open native folder picker, return selected path."""
    path = _pick_folder()
    return jsonify({"path": path})


@app.post("/api/scan")
def scan():
    """Fast scan of input directory for country and business line combinations."""
    data = request.json or {}
    raw_dir = data.get("input_dir", "").strip(' "\'')
    if not raw_dir:
        return jsonify({"error": "Please specify an input folder path"}), 400

    root = Path(raw_dir)
    if not root.is_dir():
        return jsonify({"error": f"Folder not found: {raw_dir}"}), 400

    combo_files: dict[tuple[str, str], list[str]] = {}
    unmatched: list[str] = []
    total_excel = 0

    try:
        for entry in os.scandir(root):
            if not entry.is_file() or entry.name.startswith("~$"):
                continue
            name_lower = entry.name.lower()
            if not (name_lower.endswith(".xlsx") or name_lower.endswith(".xls") or name_lower.endswith(".xlsm")):
                continue

            total_excel += 1
            combo = extract_combo_from_filename(entry.name)
            if combo:
                combo_files.setdefault(combo, []).append(entry.name)
            else:
                unmatched.append(entry.name)
    except Exception as e:
        return jsonify({"error": f"Failed reading folder: {e}"}), 500

    result = [
        {"country": c, "business_line": b, "files": sorted(files)}
        for (c, b), files in sorted(combo_files.items())
    ]

    return jsonify({
        "combos": result,
        "total_excel_files": total_excel,
        "unmatched_files": unmatched,
    })


@app.post("/api/run")
def run_pipeline():
    """Run the pipeline for selected combinations and files."""
    data = request.json or {}
    input_dir = str(data.get("input_dir", "")).strip(' "\'')
    output_dir = str(data.get("output_dir", "")).strip(' "\'')
    quarter = str(data.get("ingestion_quarter", "")).strip()
    combos = data.get("combos", [])

    if not input_dir:
        return jsonify({"error": "Input directory is required"}), 400
    if not output_dir:
        return jsonify({"error": "Output directory is required"}), 400
    if not quarter:
        return jsonify({"error": "Ingestion quarter is required"}), 400
    if not combos:
        return jsonify({"error": "Select at least one combination with at least one file"}), 400

    try:
        qi = resolve_quarter(quarter)
    except Exception as e:
        return jsonify({"error": f"Invalid quarter format '{quarter}': {e}"}), 400

    results = []
    for combo in combos:
        country, bl = combo["country"], combo["business_line"]
        chosen_files = combo.get("files", [])
        if not chosen_files:
            continue

        label = f"{country}/{bl}"
        try:
            tables = load_tables(input_dir, country, bl, selected_files=chosen_files)
            kri_results = filter_kris(tables, qi)
            ads = set(kri_results)
            kpi_data, kpi_avail = enrich_kpis(tables, ads, qi)
            build_output(kri_results, kpi_data, kpi_avail, qi, output_dir, country, bl)
            results.append({
                "label": label,
                "status": "ok",
                "triggered": len(ads),
                "files_count": len(chosen_files)
            })
        except Exception as e:
            results.append({"label": label, "status": "error", "message": str(e)})

    return jsonify({
        "quarter": qi.ingestion,
        "test": qi.test,
        "base": qi.base,
        "results": results,
    })


# ── HTML UI ─────────────────────────────────────────────────────────────────

@app.get("/")
def index():
    return Response(HTML, content_type="text/html")


HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>KRI/KPI Context Builder</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --bg:#0b0e14;--surface:#151922;--surface2:#1f2430;--surface3:#272e3d;--border:#2b3245;
  --text:#e6e8f0;--text2:#8f96a8;--accent:#6366f1;--accent2:#818cf8;
  --green:#10b981;--red:#ef4444;--radius:12px;
}
body{font-family:'Inter',sans-serif;background:var(--bg);color:var(--text);
  min-height:100vh;display:flex;justify-content:center;padding:40px 20px}
.app{max-width:820px;width:100%}
h1{font-size:1.7rem;font-weight:700;margin-bottom:6px;
  background:linear-gradient(135deg,#a5b4fc,#34d399);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent}
.subtitle{color:var(--text2);font-size:.86rem;margin-bottom:28px}
.card{background:var(--surface);border:1px solid var(--border);
  border-radius:var(--radius);padding:24px;margin-bottom:20px;
  box-shadow:0 4px 20px rgba(0,0,0,0.2)}
.card h2{font-size:.96rem;font-weight:600;margin-bottom:16px;color:var(--accent2);display:flex;align-items:center;gap:8px}
.field{margin-bottom:14px}
.field label{display:block;font-size:.78rem;color:var(--text2);margin-bottom:6px;
  text-transform:uppercase;letter-spacing:.5px;font-weight:600}
.row{display:flex;gap:10px}
.row input{flex:1}
input{width:100%;padding:11px 14px;background:var(--surface2);
  border:1px solid var(--border);border-radius:8px;color:var(--text);
  font-size:.9rem;font-family:inherit;outline:none;transition:border-color .2s}
input:focus{border-color:var(--accent)}
.btn{padding:11px 20px;border:none;border-radius:8px;font-family:inherit;
  font-size:.88rem;font-weight:600;cursor:pointer;transition:all .2s;display:inline-flex;align-items:center;justify-content:center;gap:6px}
.btn-browse{background:var(--surface2);color:var(--accent2);border:1px solid var(--border)}
.btn-browse:hover{border-color:var(--accent);background:var(--accent);color:#fff}
.btn-scan{background:var(--accent);color:#fff;width:100%;margin-top:6px}
.btn-scan:hover{background:var(--accent2)}
.btn-run{background:linear-gradient(135deg,var(--accent),var(--green));color:#fff;
  width:100%;padding:14px;font-size:.98rem;border-radius:10px;margin-top:10px}
.btn-run:hover{opacity:.95;transform:translateY(-1px);box-shadow:0 6px 20px rgba(99,102,241,.3)}
.btn-run:disabled{opacity:.4;cursor:not-allowed;transform:none;box-shadow:none}
.btn-sm{background:transparent;color:var(--accent2);border:1px solid var(--border);padding:5px 10px;font-size:.76rem;border-radius:6px}
.btn-sm:hover{background:var(--surface2)}

.scan-header{display:flex;justify-content:space-between;align-items:center;margin-top:18px;margin-bottom:12px;padding-bottom:8px;border-bottom:1px solid var(--border)}
.combo-group{background:var(--surface2);border:1px solid var(--border);border-radius:10px;margin-bottom:14px;overflow:hidden;transition:border-color .2s}
.combo-group:hover{border-color:rgba(99,102,241,0.5)}
.combo-group-header{padding:12px 16px;background:var(--surface3);display:flex;justify-content:space-between;align-items:center;cursor:pointer;user-select:none}
.combo-title-area{display:flex;align-items:center;gap:12px}
.combo-badge{background:var(--accent);color:#fff;font-weight:700;font-size:0.86rem;padding:3px 10px;border-radius:6px}
.combo-meta{font-size:0.82rem;color:var(--text2)}
.file-list{padding:10px 16px;display:flex;flex-direction:column;gap:8px}
.file-item{display:flex;align-items:center;gap:10px;padding:8px 12px;background:rgba(0,0,0,0.15);border-radius:6px;border:1px solid transparent;transition:all .15s}
.file-item:hover{background:rgba(99,102,241,0.08);border-color:rgba(99,102,241,0.3)}
.file-item label{display:flex;align-items:center;gap:10px;width:100%;cursor:pointer;font-family:'JetBrains Mono',monospace;font-size:0.84rem;color:var(--text)}
.file-icon{opacity:0.6;font-size:0.9rem}

input[type="checkbox"]{width:16px;height:16px;accent-color:var(--accent);cursor:pointer}

.results{margin-top:16px}
.result{padding:12px 16px;border-radius:8px;margin-bottom:8px;font-size:.88rem;
  display:flex;justify-content:space-between;align-items:center}
.result.ok{background:rgba(16,185,129,.1);border:1px solid rgba(16,185,129,.25)}
.result.error{background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.25)}
.badge{padding:4px 10px;border-radius:6px;font-size:.76rem;font-weight:700}
.badge.ok{background:var(--green);color:#06281e}
.badge.error{background:var(--red);color:#fff}
.empty{color:var(--text2);font-size:.86rem;text-align:center;padding:16px;background:rgba(0,0,0,0.15);border-radius:8px;margin-top:12px}
.spinner{display:inline-block;width:18px;height:18px;border:2px solid var(--border);
  border-top-color:var(--accent);border-radius:50%;animation:spin .6s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
</style>
</head>
<body>
<div class="app">
  <h1>KRI / KPI Context Builder</h1>
  <p class="subtitle">Transaction Monitoring — Automated Quantitative Context Generator</p>

  <!-- Input Folder -->
  <div class="card">
    <h2>📂 Input Folder</h2>
    <div class="field">
      <label>Folder containing country Excel files</label>
      <div class="row">
        <input id="inputDir" placeholder="Select or paste folder path (e.g. C:\data\input or input)" />
        <button class="btn btn-browse" onclick="browse('inputDir')">Browse</button>
      </div>
    </div>
    <button class="btn btn-scan" onclick="scan()">🔍 Scan Folder for Available Countries & Files</button>
    <div id="comboArea"></div>
  </div>

  <!-- Parameters -->
  <div class="card">
    <h2>⚙️ Parameters</h2>
    <div class="field">
      <label>Ingestion Quarter</label>
      <input id="quarter" placeholder="Q1_2026" value="Q1_2026" />
    </div>
    <div class="field">
      <label>Output Directory</label>
      <div class="row">
        <input id="outputDir" placeholder="Select or paste output directory (e.g. output)" value="output" />
        <button class="btn btn-browse" onclick="browse('outputDir')">Browse</button>
      </div>
    </div>
  </div>

  <!-- Run -->
  <div class="card">
    <h2>🚀 Execute Pipeline</h2>
    <button id="runBtn" class="btn btn-run" onclick="run()" disabled>
      Select at least one file above to run
    </button>
    <div id="resultArea"></div>
  </div>
</div>

<script>
let scanData = [];

async function browse(targetId) {
  const btn = event?.target;
  if (btn) btn.textContent = 'Opening...';
  try {
    const r = await fetch('/api/browse');
    const d = await r.json();
    if (d.path) {
      document.getElementById(targetId).value = d.path;
      if (targetId === 'inputDir') {
        scan();
      }
    }
  } finally {
    if (btn) btn.textContent = 'Browse';
  }
}

async function scan() {
  const dir = document.getElementById('inputDir').value.trim();
  const area = document.getElementById('comboArea');
  if (!dir) {
    area.innerHTML = '<div class="empty">Please specify an input folder path first</div>';
    return;
  }
  area.innerHTML = '<div class="empty"><span class="spinner"></span> Scanning folder for Excel files...</div>';

  try {
    const r = await fetch('/api/scan', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({input_dir: dir})
    });
    const d = await r.json();

    if (!r.ok || d.error) {
      area.innerHTML = `<div class="empty" style="color:var(--red)">⚠ ${d.error || 'Failed scanning folder'}</div>`;
      return;
    }

    if (!d.combos.length) {
      let unmsg = '';
      if (d.unmatched_files && d.unmatched_files.length) {
        unmsg = `<br><br><b>Unmatched Excel files:</b><div style="font-family:'JetBrains Mono',monospace;font-size:0.8rem;color:var(--text2);margin-top:6px">` +
                d.unmatched_files.map(f => `<div>📄 ${f}</div>`).join('') + `</div>`;
      }
      area.innerHTML = `<div class="empty">Found ${d.total_excel_files} Excel file(s), but none match <code>&lt;Country&gt;_&lt;BusinessLine&gt;_...xlsx</code>.${unmsg}</div>`;
      return;
    }

    scanData = d.combos;

    let html = `
      <div class="scan-header">
        <span style="font-size:0.85rem;color:var(--text2)">
          Detected <b>${d.combos.length}</b> combination(s) in <b>${d.total_excel_files}</b> file(s)
        </span>
        <div style="display:flex;gap:6px">
          <button class="btn btn-sm" onclick="setAllFiles(true)">Select All Files</button>
          <button class="btn btn-sm" onclick="setAllFiles(false)">Deselect All</button>
        </div>
      </div>
    `;

    html += d.combos.map((c, cIdx) => {
      const comboId = `${c.country}_${c.business_line}`;
      return `
        <div class="combo-group" id="group_${comboId}">
          <div class="combo-group-header" onclick="toggleComboHeader(event, '${comboId}')">
            <div class="combo-title-area">
              <input type="checkbox" id="chk_combo_${comboId}" checked onchange="toggleComboCheckbox('${comboId}', this.checked)" onclick="event.stopPropagation()">
              <span class="combo-badge">${c.country} / ${c.business_line}</span>
              <span class="combo-meta" id="meta_${comboId}">${c.files.length} of ${c.files.length} file(s) selected</span>
            </div>
            <div style="display:flex;gap:6px">
              <button class="btn btn-sm" onclick="event.stopPropagation(); setGroupFiles('${comboId}', true)">All</button>
              <button class="btn btn-sm" onclick="event.stopPropagation(); setGroupFiles('${comboId}', false)">None</button>
            </div>
          </div>
          <div class="file-list">
            ${c.files.map((file, fIdx) => `
              <div class="file-item">
                <label>
                  <input type="checkbox" class="file-chk file-chk-${comboId}" data-combo="${comboId}" data-country="${c.country}" data-bl="${c.business_line}" data-file="${file}" checked onchange="onFileCheckboxChange('${comboId}')">
                  <span class="file-icon">📄</span>
                  <span>${file}</span>
                </label>
              </div>
            `).join('')}
          </div>
        </div>
      `;
    }).join('');

    area.innerHTML = html;
    updateRunBtn();
  } catch (err) {
    area.innerHTML = `<div class="empty" style="color:var(--red)">Network error: ${err.message}</div>`;
  }
}

function toggleComboHeader(event, comboId) {
  const masterChk = document.getElementById(`chk_combo_${comboId}`);
  masterChk.checked = !masterChk.checked;
  toggleComboCheckbox(comboId, masterChk.checked);
}

function toggleComboCheckbox(comboId, isChecked) {
  document.querySelectorAll(`.file-chk-${comboId}`).forEach(el => el.checked = isChecked);
  updateGroupMeta(comboId);
  updateRunBtn();
}

function setGroupFiles(comboId, isChecked) {
  document.querySelectorAll(`.file-chk-${comboId}`).forEach(el => el.checked = isChecked);
  document.getElementById(`chk_combo_${comboId}`).checked = isChecked;
  updateGroupMeta(comboId);
  updateRunBtn();
}

function onFileCheckboxChange(comboId) {
  const chks = document.querySelectorAll(`.file-chk-${comboId}`);
  const checkedCount = Array.from(chks).filter(c => c.checked).length;
  const masterChk = document.getElementById(`chk_combo_${comboId}`);
  masterChk.checked = checkedCount > 0;
  updateGroupMeta(comboId);
  updateRunBtn();
}

function updateGroupMeta(comboId) {
  const chks = document.querySelectorAll(`.file-chk-${comboId}`);
  const checkedCount = Array.from(chks).filter(c => c.checked).length;
  const meta = document.getElementById(`meta_${comboId}`);
  if (meta) {
    meta.textContent = `${checkedCount} of ${chks.length} file(s) selected`;
  }
}

function setAllFiles(isChecked) {
  document.querySelectorAll('.file-chk').forEach(el => el.checked = isChecked);
  document.querySelectorAll('[id^="chk_combo_"]').forEach(el => el.checked = isChecked);
  scanData.forEach(c => updateGroupMeta(`${c.country}_${c.business_line}`));
  updateRunBtn();
}

function getSelectedPayload() {
  const payload = [];
  scanData.forEach(c => {
    const comboId = `${c.country}_${c.business_line}`;
    const selectedFiles = Array.from(document.querySelectorAll(`.file-chk-${comboId}:checked`)).map(el => el.dataset.file);
    if (selectedFiles.length > 0) {
      payload.push({
        country: c.country,
        business_line: c.business_line,
        files: selectedFiles
      });
    }
  });
  return payload;
}

function updateRunBtn() {
  const payload = getSelectedPayload();
  const totalFiles = payload.reduce((acc, cur) => acc + cur.files.length, 0);
  const btn = document.getElementById('runBtn');
  btn.disabled = totalFiles === 0;
  btn.textContent = totalFiles > 0
    ? `▶ Run Pipeline (${payload.length} country/BL, ${totalFiles} file${totalFiles > 1 ? 's' : ''})`
    : 'Select at least one file above to run';
}

async function run() {
  const btn = document.getElementById('runBtn');
  const area = document.getElementById('resultArea');
  const combos = getSelectedPayload();

  if (!combos.length) return;

  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Processing pipeline...';
  area.innerHTML = '<div class="empty"><span class="spinner"></span> Running pipeline for selected files...</div>';

  try {
    const r = await fetch('/api/run', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        input_dir: document.getElementById('inputDir').value,
        output_dir: document.getElementById('outputDir').value,
        ingestion_quarter: document.getElementById('quarter').value,
        combos
      })
    });
    const d = await r.json();

    if (!r.ok || d.error) {
      area.innerHTML = `<div class="empty" style="color:var(--red)">⚠ ${d.error || 'Execution failed'}</div>`;
      updateRunBtn();
      return;
    }

    let outHtml = `
      <div class="results">
        <div style="color:var(--text2);font-size:.82rem;margin-bottom:12px;padding:8px 12px;background:var(--surface2);border-radius:6px">
          <b>Quarters resolved:</b> Ingestion = <code>${d.quarter}</code> · Test = <code>${d.test}</code> · Base = <code>${d.base}</code>
        </div>
    `;

    outHtml += d.results.map(res => `
      <div class="result ${res.status}">
        <div>
          <b>${res.label}</b>
          <span style="color:var(--text2);margin-left:8px;font-size:0.84rem">
            ${res.status === 'ok' ? `(${res.triggered} alert definitions with triggered KRIs from ${res.files_count} file(s))` : `(${res.message})`}
          </span>
        </div>
        <span class="badge ${res.status}">${res.status === 'ok' ? '✓ DONE' : '✗ FAILED'}</span>
      </div>
    `).join('');

    outHtml += '</div>';
    area.innerHTML = outHtml;
  } catch (err) {
    area.innerHTML = `<div class="empty" style="color:var(--red)">Execution error: ${err.message}</div>`;
  } finally {
    updateRunBtn();
  }
}
</script>
</body>
</html>
"""

if __name__ == "__main__":
    import argparse, webbrowser
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5000)
    args = ap.parse_args()
    threading.Timer(1.0, lambda: webbrowser.open(f"http://localhost:{args.port}")).start()
    print(f"[Server] Starting at http://localhost:{args.port}")
    app.run(port=args.port, debug=False)

"""
Embedded local web server that serves the DataSure setup wizard.
Starts on localhost:8765, opens the browser, waits for the user to
complete setup, writes ~/.datasure/config.yaml, then shuts down.
"""
from __future__ import annotations

import json
import os
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any


CONFIG_DIR  = Path.home() / ".datasure"
CONFIG_FILE = CONFIG_DIR / "config.yaml"

_shutdown_event = threading.Event()
_saved_config: dict = {}


# ── request handler ───────────────────────────────────────────────────────────

class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass  # silence access log

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, "text/html", _WIZARD_HTML.encode())
        else:
            self._send(404, "text/plain", b"Not found")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body   = json.loads(self.rfile.read(length) or "{}")

        if self.path == "/api/test":
            result = _test_connection(body)
            self._send(200, "application/json", json.dumps(result).encode())

        elif self.path == "/api/save":
            result = _save_config(body)
            self._send(200, "application/json", json.dumps(result).encode())
            if result.get("ok"):
                _shutdown_event.set()
        else:
            self._send(404, "text/plain", b"Not found")

    def _send(self, code: int, ctype: str, body: bytes):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)


# ── connection tester ─────────────────────────────────────────────────────────

def _test_connection(data: dict) -> dict:
    try:
        from datasure.config.settings import QlikSenseSettings
        from datasure.connectors.qlik_sense import QlikSenseConnector
        settings = QlikSenseSettings(**{k: v for k, v in data.items() if v != ""})
        connector = QlikSenseConnector(settings)
        return connector.test_connection()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ── config writer ─────────────────────────────────────────────────────────────

def _save_config(data: dict) -> dict:
    try:
        import yaml
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)

        qlik_keys = {
            "mode", "host", "port", "virtual_proxy", "verify_ssl",
            "ca_cert", "cert_path", "key_path",
            "user_directory", "user_id",
            "tenant", "api_key",
            "timeout", "retries",
        }
        qlik = {k: v for k, v in data.items() if k in qlik_keys and v not in ("", None)}
        cfg = {
            "qlik": qlik,
            "validation": {
                "enabled_modules": [
                    "syntax", "data_types",
                    "field_integrity", "data_model_health", "duplicates",
                ]
            },
            "report": {
                "output_dir": str(Path.home() / "datasure-reports"),
                "formats": ["html", "json"],
            },
            "log_level": "INFO",
        }
        CONFIG_FILE.write_text(yaml.dump(cfg, default_flow_style=False, allow_unicode=True))
        global _saved_config
        _saved_config = cfg
        return {"ok": True, "path": str(CONFIG_FILE)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ── entrypoint ────────────────────────────────────────────────────────────────

def run(port: int = 8765, no_browser: bool = False) -> Path:
    """Start the wizard server, block until the user completes setup."""
    server = HTTPServer(("127.0.0.1", port), _Handler)
    url    = f"http://localhost:{port}"

    t = threading.Thread(target=_serve_until_done, args=(server,), daemon=True)
    t.start()

    if not no_browser:
        threading.Timer(0.4, webbrowser.open, args=(url,)).start()

    print(f"\n  DataSure Setup Wizard → {url}\n")
    _shutdown_event.wait()
    server.shutdown()
    return CONFIG_FILE


def _serve_until_done(server: HTTPServer):
    while not _shutdown_event.is_set():
        server.handle_request()


# ── HTML wizard (single-file, self-contained) ─────────────────────────────────

_WIZARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DataSure Setup</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0f1923;color:#e0e6ef;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:2rem}
.wizard{width:100%;max-width:560px}
.logo{text-align:center;margin-bottom:2.5rem}
.logo-name{font-size:2rem;font-weight:800;color:#fff;letter-spacing:-1px}
.logo-tag{color:#4a9eff;font-size:0.85rem;margin-top:4px;letter-spacing:1px;text-transform:uppercase}
.card{background:#1a2332;border-radius:16px;padding:2rem 2.2rem;box-shadow:0 8px 40px rgba(0,0,0,.4)}
.step{display:none}.step.active{display:block}
h2{font-size:1.3rem;font-weight:700;color:#fff;margin-bottom:.4rem}
.sub{color:#6b8aad;font-size:0.88rem;margin-bottom:1.6rem;line-height:1.5}

/* type cards */
.type-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:.8rem;margin-bottom:1.6rem}
.type-card{border:2px solid #263548;border-radius:10px;padding:1rem .8rem;text-align:center;cursor:pointer;transition:.15s}
.type-card:hover{border-color:#4a9eff;background:#1f2f42}
.type-card.selected{border-color:#4a9eff;background:#1b3050}
.type-icon{font-size:1.8rem;margin-bottom:.4rem}
.type-label{font-size:.82rem;font-weight:600;color:#cfd8e3}
.type-desc{font-size:.72rem;color:#6b8aad;margin-top:.2rem}

/* form */
.field{margin-bottom:1.1rem}
label{display:block;font-size:.8rem;font-weight:600;color:#8fa8c4;margin-bottom:.35rem;text-transform:uppercase;letter-spacing:.5px}
input[type=text],input[type=number],input[type=password]{width:100%;background:#0f1923;border:1.5px solid #263548;border-radius:8px;padding:.6rem .9rem;color:#e0e6ef;font-size:.9rem;outline:none;transition:.15s}
input:focus{border-color:#4a9eff;box-shadow:0 0 0 3px rgba(74,158,255,.15)}
.hint{font-size:.75rem;color:#4a6a8a;margin-top:.25rem}
.row{display:grid;grid-template-columns:2fr 1fr;gap:.8rem}
.toggle-row{display:flex;align-items:center;gap:.7rem;margin-bottom:1.1rem}
.toggle-row label{margin:0;text-transform:none;font-size:.88rem;font-weight:400;color:#cfd8e3;letter-spacing:0}
input[type=checkbox]{width:16px;height:16px;accent-color:#4a9eff;cursor:pointer}

/* section heading */
.section-label{font-size:.72rem;font-weight:700;color:#4a9eff;text-transform:uppercase;letter-spacing:1px;margin:.3rem 0 .9rem;padding-bottom:.4rem;border-bottom:1px solid #263548}

/* buttons */
.btn-row{display:flex;gap:.8rem;margin-top:1.6rem}
.btn{flex:1;padding:.7rem 1rem;border:none;border-radius:8px;font-size:.92rem;font-weight:600;cursor:pointer;transition:.15s}
.btn-primary{background:#4a9eff;color:#fff}.btn-primary:hover{background:#3a8eef}
.btn-secondary{background:#263548;color:#8fa8c4}.btn-secondary:hover{background:#2e3f56}
.btn:disabled{opacity:.4;cursor:not-allowed}

/* test result */
.result{border-radius:8px;padding:.9rem 1rem;margin-top:1rem;font-size:.88rem;display:none}
.result.ok{background:#0d2b1a;border:1px solid #1e6b3e;color:#4ade80}
.result.err{background:#2b0d0d;border:1px solid #6b1e1e;color:#f87171}
.result ul{margin:.4rem 0 0 1rem}
.result li{margin:.15rem 0;color:#cfd8e3}
.spinner{display:inline-block;width:14px;height:14px;border:2px solid #4a9eff;border-top-color:transparent;border-radius:50%;animation:spin .7s linear infinite;vertical-align:middle;margin-right:.4rem}
@keyframes spin{to{transform:rotate(360deg)}}

/* progress dots */
.progress{display:flex;justify-content:center;gap:.5rem;margin-bottom:1.8rem}
.dot{width:8px;height:8px;border-radius:50%;background:#263548;transition:.2s}
.dot.active{background:#4a9eff}.dot.done{background:#2ecc71}

/* success */
.success-icon{font-size:3.5rem;text-align:center;margin:1rem 0}
.cmd-block{background:#0f1923;border:1px solid #263548;border-radius:8px;padding:.9rem 1rem;font-family:monospace;font-size:.85rem;color:#a8d8ea;margin:.5rem 0}
.next-steps li{margin:.4rem 0;color:#cfd8e3;font-size:.88rem;padding-left:.2rem}
.next-steps li::marker{color:#4a9eff}
</style>
</head>
<body>
<div class="wizard">
  <div class="logo">
    <div class="logo-name">DataSure</div>
    <div class="logo-tag">Analytics QA Platform</div>
  </div>

  <div class="progress">
    <div class="dot active" id="d0"></div>
    <div class="dot" id="d1"></div>
    <div class="dot" id="d2"></div>
    <div class="dot" id="d3"></div>
  </div>

  <div class="card">

    <!-- Step 0: Welcome -->
    <div class="step active" id="step-0">
      <h2>Welcome to DataSure</h2>
      <p class="sub">This wizard will connect DataSure to your Qlik environment in under 2 minutes. You can re-run it any time with <code>datasure setup</code>.</p>
      <p class="sub">You will need:<br>
        &bull; <b>Qlik Sense Enterprise:</b> server hostname + exported certificates (root.pem, client.pem, client_key.pem)<br>
        &bull; <b>Qlik Cloud:</b> your tenant URL + an API key
      </p>
      <div class="btn-row">
        <button class="btn btn-primary" onclick="goTo(1)">Get Started →</button>
      </div>
    </div>

    <!-- Step 1: Deployment type -->
    <div class="step" id="step-1">
      <h2>Deployment Type</h2>
      <p class="sub">Which Qlik environment are you connecting to?</p>
      <div class="type-grid">
        <div class="type-card" onclick="selectType('enterprise',this)">
          <div class="type-icon">🏢</div>
          <div class="type-label">Enterprise</div>
          <div class="type-desc">Qlik Sense on Windows</div>
        </div>
        <div class="type-card" onclick="selectType('cloud',this)">
          <div class="type-icon">☁️</div>
          <div class="type-label">Cloud</div>
          <div class="type-desc">Qlik Cloud SaaS</div>
        </div>
        <div class="type-card" onclick="selectType('desktop',this)">
          <div class="type-icon">💻</div>
          <div class="type-label">Desktop</div>
          <div class="type-desc">Local / developer</div>
        </div>
        <div class="type-card" onclick="selectType('demo',this)" style="border-color:#f39c12">
          <div class="type-icon">🎮</div>
          <div class="type-label" style="color:#f39c12">Demo</div>
          <div class="type-desc">No Qlik needed</div>
        </div>
      </div>
      <div class="btn-row">
        <button class="btn btn-secondary" onclick="goTo(0)">← Back</button>
        <button class="btn btn-primary" id="btn-type-next" onclick="typeNext()" disabled>Next →</button>
      </div>
    </div>

    <!-- Step 2: Connection details -->
    <div class="step" id="step-2">
      <h2>Connection Details</h2>
      <p class="sub" id="conn-sub"></p>
      <div id="conn-form"></div>
      <div id="demo-notice" style="display:none;background:#1a2d14;border:1px solid #2ecc71;border-radius:8px;padding:1rem;color:#4ade80;font-size:.9rem">
        🎮 <b>Demo Mode</b> — no Qlik connection needed.<br>
        <span style="color:#8fa8c4;font-size:.83rem">DataSure will use built-in sample data with intentional issues so you can explore all features immediately.</span>
      </div>
      <div class="btn-row">
        <button class="btn btn-secondary" onclick="goTo(1)">← Back</button>
        <button class="btn btn-primary" id="btn-test-or-skip" onclick="testConn()">Test Connection</button>
      </div>
      <div class="result" id="test-result"></div>
    </div>

    <!-- Step 3: Confirm & save -->
    <div class="step" id="step-3">
      <h2>Save Configuration</h2>
      <p class="sub">Connection verified. DataSure will save your settings to <code id="cfg-path"></code></p>
      <div class="field">
        <label>Report output folder</label>
        <input type="text" id="report-dir" placeholder="~/datasure-reports">
        <div class="hint">HTML and JSON reports will be saved here after each validation run.</div>
      </div>
      <div class="btn-row">
        <button class="btn btn-secondary" onclick="goTo(2)">← Back</button>
        <button class="btn btn-primary" onclick="saveConfig()">Save & Finish</button>
      </div>
      <div class="result" id="save-result"></div>
    </div>

    <!-- Step 4: Done -->
    <div class="step" id="step-4">
      <div class="success-icon">✅</div>
      <h2 style="text-align:center">You're all set!</h2>
      <p class="sub" style="text-align:center;margin-bottom:1.2rem">DataSure is configured and ready to use.</p>
      <div class="section-label">Next steps</div>
      <ul class="next-steps" id="next-steps-list">
        <li>List your apps:<br><div class="cmd-block">datasure list-apps</div></li>
        <li>Validate an app (replace with your app ID):<br><div class="cmd-block">datasure validate &lt;APP_ID&gt;</div></li>
        <li>Re-run setup any time:<br><div class="cmd-block">datasure setup</div></li>
      </ul>
      <div id="demo-next" style="display:none">
        <ul class="next-steps">
          <li>See the 3 built-in demo apps:<br><div class="cmd-block">datasure list-apps</div></li>
          <li>Run a full analysis on the demo app:<br><div class="cmd-block">datasure validate demo-app-001</div></li>
          <li>Or launch the interactive demo:<br><div class="cmd-block">datasure demo</div></li>
          <li>Re-run setup any time:<br><div class="cmd-block">datasure setup</div></li>
        </ul>
      </div>
      <div class="btn-row" style="margin-top:1.4rem">
        <button class="btn btn-primary" onclick="window.close()">Close this window</button>
      </div>
    </div>

  </div>
</div>

<script>
var selectedType = '';
var connData = {};

var FORMS = {
  enterprise: {
    sub: 'Enter your Qlik Sense server details and the paths to your exported certificates (QMC → Nodes → Export Certificates).',
    html: `
      <div class="section-label">Server</div>
      <div class="row">
        <div class="field"><label>Hostname / IP</label><input type="text" id="f-host" placeholder="qlik.yourcompany.com"><div class="hint">Your Qlik Sense server address</div></div>
        <div class="field"><label>Port</label><input type="number" id="f-port" value="443"><div class="hint">443 or 4242</div></div>
      </div>
      <div class="field"><label>Virtual Proxy <span style="font-weight:400;text-transform:none;color:#4a6a8a">(optional)</span></label><input type="text" id="f-vp" placeholder="Leave blank for default"><div class="hint">Only needed if your QRS uses a non-default virtual proxy prefix</div></div>

      <div class="section-label" style="margin-top:1rem">Certificates <span style="font-weight:400;text-transform:none;letter-spacing:0;color:#4a6a8a">— exported from QMC → Nodes → Export Certificates (Linux/Mac format)</span></div>
      <div class="field"><label>CA Certificate (root.pem)</label><input type="text" id="f-ca" placeholder="~/.qlik-certs/root.pem"></div>
      <div class="field"><label>Client Certificate (client.pem)</label><input type="text" id="f-cert" placeholder="~/.qlik-certs/client.pem"></div>
      <div class="field"><label>Client Key (client_key.pem)</label><input type="text" id="f-key" placeholder="~/.qlik-certs/client_key.pem"></div>
      <div class="toggle-row"><input type="checkbox" id="f-ssl" checked><label for="f-ssl">Verify SSL certificate</label></div>

      <div class="section-label" style="margin-top:.5rem">Service Account</div>
      <div class="row">
        <div class="field"><label>User Directory</label><input type="text" id="f-ud" value="INTERNAL"></div>
        <div class="field"><label>User ID</label><input type="text" id="f-uid" value="sa_repository"></div>
      </div>`
  },
  cloud: {
    sub: 'Enter your Qlik Cloud tenant and an API key. Generate the key in Qlik Cloud: Profile menu → API Keys → Generate new key.',
    html: `
      <div class="field"><label>Tenant Hostname</label><input type="text" id="f-tenant" placeholder="yourcompany.us.qlikcloud.com"><div class="hint">Found in your browser URL when logged into Qlik Cloud</div></div>
      <div class="field"><label>API Key</label><input type="password" id="f-apikey" placeholder="eyJhbGciOi..."><div class="hint">Profile menu → API Keys → Generate new key. Give it App read scope.</div></div>`
  },
  desktop: {
    sub: 'Qlik Sense Desktop runs locally. No authentication is needed.',
    html: `
      <div class="row">
        <div class="field"><label>Host</label><input type="text" id="f-host" value="localhost" readonly></div>
        <div class="field"><label>Port</label><input type="number" id="f-port" value="4848" readonly></div>
      </div>
      <p style="color:#6b8aad;font-size:.85rem;margin-top:.5rem">Make sure Qlik Sense Desktop is running before clicking Test Connection.</p>`
  }
};

function selectType(type, el) {
  selectedType = type;
  document.querySelectorAll('.type-card').forEach(c => c.classList.remove('selected'));
  el.classList.add('selected');
  document.getElementById('btn-type-next').disabled = false;
}

function typeNext() {
  if (selectedType === 'demo') {
    // skip connection details, pre-fill connData and jump to save step
    connData = {mode: 'demo'};
    goTo(3);
  } else {
    goTo(2);
  }
}

function goTo(n) {
  document.querySelectorAll('.step').forEach((s,i) => {
    s.classList.toggle('active', i===n);
  });
  document.querySelectorAll('.dot').forEach((d,i) => {
    d.classList.toggle('active', i===n);
    d.classList.toggle('done', i<n);
  });
  if (n===2) renderForm();
  if (n===3) document.getElementById('cfg-path').textContent = (navigator.platform.includes('Win') ? '%USERPROFILE%\\\\.datasure\\\\config.yaml' : '~/.datasure/config.yaml');
  if (n===4) {
    var isDemo = selectedType === 'demo';
    document.getElementById('next-steps-list').style.display = isDemo ? 'none' : 'block';
    document.getElementById('demo-next').style.display = isDemo ? 'block' : 'none';
  }
}

function renderForm() {
  var isDemo = selectedType === 'demo';
  document.getElementById('demo-notice').style.display = isDemo ? 'block' : 'none';
  document.getElementById('conn-sub').textContent = isDemo ? '' : (FORMS[selectedType]||{}).sub||'';
  document.getElementById('conn-form').innerHTML   = isDemo ? '' : (FORMS[selectedType]||{}).html||'';
  document.getElementById('test-result').style.display = 'none';
  var btn = document.getElementById('btn-test-or-skip');
  if (isDemo) { btn.textContent = 'Continue →'; btn.onclick = function(){ connData={mode:'demo'}; goTo(3); }; }
  else        { btn.textContent = 'Test Connection'; btn.onclick = testConn; }
}

function getFormData() {
  var d = { mode: selectedType };
  var get = id => { var el=document.getElementById(id); return el ? el.value.trim() : ''; };
  var getb = id => { var el=document.getElementById(id); return el ? el.checked : true; };
  if (selectedType==='enterprise') {
    d.host = get('f-host'); d.port = parseInt(get('f-port'))||443;
    d.virtual_proxy = get('f-vp');
    d.ca_cert = get('f-ca'); d.cert_path = get('f-cert'); d.key_path = get('f-key');
    d.verify_ssl = getb('f-ssl');
    d.user_directory = get('f-ud')||'INTERNAL';
    d.user_id = get('f-uid')||'sa_repository';
  } else if (selectedType==='cloud') {
    d.tenant = get('f-tenant'); d.api_key = get('f-apikey');
  } else {
    d.host = 'localhost'; d.port = 4848;
  }
  return d;
}

function testConn() {
  var el = document.getElementById('test-result');
  el.className = 'result'; el.style.display = 'block';
  el.innerHTML = '<span class="spinner"></span> Testing connection…';
  connData = getFormData();
  fetch('/api/test', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(connData)})
    .then(r=>r.json()).then(res=>{
      if (res.ok) {
        var items = Object.entries(res).filter(([k])=>k!=='ok').map(([k,v])=>'<li><b>'+k+':</b> '+v+'</li>').join('');
        el.className='result ok';
        el.innerHTML='✓ Connection successful<ul>'+items+'</ul><div style="margin-top:.8rem"><button class="btn btn-primary" style="width:100%" onclick="goTo(3)">Continue →</button></div>';
      } else {
        el.className='result err'; el.innerHTML='✗ '+res.error;
      }
    }).catch(e=>{el.className='result err';el.innerHTML='✗ '+e;});
}

function saveConfig() {
  var el = document.getElementById('save-result');
  el.className='result'; el.style.display='block';
  el.innerHTML='<span class="spinner"></span> Saving…';
  var dir = document.getElementById('report-dir').value.trim() || '~/datasure-reports';
  var payload = Object.assign({}, connData, {report_dir: dir});
  fetch('/api/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)})
    .then(r=>r.json()).then(res=>{
      if(res.ok){goTo(4);}
      else{el.className='result err';el.innerHTML='✗ '+res.error;}
    }).catch(e=>{el.className='result err';el.innerHTML='✗ '+e;});
}
</script>
</body>
</html>"""

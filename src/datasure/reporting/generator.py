from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from typing import Any

from datasure.validators.base import ValidationResult


# ── helpers ──────────────────────────────────────────────────────────────────

def _results_to_dict(results: list[ValidationResult]) -> list[dict]:
    out = []
    for r in results:
        out.append({
            "validator": r.validator_name,
            "object_type": r.object_type,
            "object_id": r.object_id,
            "passed": r.passed,
            "error_count": r.error_count,
            "warning_count": r.warning_count,
            "issues": [
                {
                    "rule_id": i.rule_id,
                    "severity": i.severity.value,
                    "message": i.message,
                    "object_name": i.object_name,
                    "detail": i.detail,
                }
                for i in r.issues
            ],
        })
    return out


def _build_report_payload(
    results: list[ValidationResult],
    summary: dict[str, Any],
    objects: list[dict[str, Any]] | None,
) -> dict:
    """Build the structured JSON payload embedded into the HTML report."""
    all_issues: list[dict] = []
    for r in results:
        for i in r.issues:
            all_issues.append({
                "rule_id": i.rule_id,
                "severity": i.severity.value,
                "validator": r.validator_name,
                "object_type": r.object_type,
                "object_id": r.object_id,
                "object_name": i.object_name or r.object_id,
                "message": i.message,
                "detail": i.detail,
            })

    # issues by validator category
    by_category: dict[str, list] = defaultdict(list)
    for iss in all_issues:
        by_category[iss["validator"]].append(iss)

    # object inventory
    apps, sheets, measures, dimensions, visualizations, variables = [], [], [], [], [], []
    data_model: dict = {}
    if objects:
        for obj in objects:
            t = obj.get("type", "")
            if t == "app":
                apps.append(obj)
            elif t == "sheet":
                sheets.append(obj)
            elif t == "measure":
                measures.append(obj)
            elif t == "dimension":
                dimensions.append(obj)
            elif t == "visualization":
                visualizations.append(obj)
            elif t == "variable":
                variables.append(obj)
            elif t == "data_model":
                data_model = obj

    # per-object issue index
    obj_issues: dict[str, list] = defaultdict(list)
    for iss in all_issues:
        obj_issues[iss["object_id"]].append(iss)

    # field usage map
    used_fields: set[str] = set(str(f) for f in data_model.get("used_fields", set()))
    field_usage_rows: list[dict] = []
    for table in data_model.get("tables", []):
        for field in table.get("fields", []):
            fname = field.get("name", "")
            field_usage_rows.append({
                "field": fname,
                "table": table.get("name", ""),
                "is_key": field.get("is_key", False),
                "tags": field.get("tags", []),
                "used": fname.lower() in used_fields,
            })

    # duplicate groups
    dup_groups = [i for i in all_issues if i["rule_id"] == "DUP001"]

    # performance / load_script / resource_optimization issues
    _PERF_VALIDATORS = {"performance", "load_script", "resource_optimization"}
    perf_issues = [i for i in all_issues if i["validator"] in _PERF_VALIDATORS]

    # health score (0-100)
    total = summary.get("total_objects", 1) or 1
    errors = summary.get("total_errors", 0)
    warnings = summary.get("total_warnings", 0)
    score = max(0, round(100 - (errors / total * 60) - (warnings / total * 20)))

    return {
        "summary": summary,
        "score": score,
        "all_issues": all_issues,
        "by_category": dict(by_category),
        "obj_issues": dict(obj_issues),
        "apps": apps,
        "sheets": sheets,
        "measures": measures,
        "dimensions": dimensions,
        "visualizations": visualizations,
        "variables": variables,
        "data_model": data_model,
        "field_usage": field_usage_rows,
        "dup_groups": dup_groups,
        "perf_issues": perf_issues,
    }


# ── report generator ─────────────────────────────────────────────────────────

class ReportGenerator:
    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate(
        self,
        results: list[ValidationResult],
        summary: dict[str, Any],
        formats: list[str],
        run_name: str = "datasure-run",
        objects: list[dict[str, Any]] | None = None,
    ) -> dict[str, Path]:
        paths: dict[str, Path] = {}
        data = _results_to_dict(results)

        if "json" in formats:
            paths["json"] = self._write_json(data, summary, run_name)
        if "junit" in formats:
            paths["junit"] = self._write_junit(data, summary, run_name)
        if "html" in formats:
            payload = _build_report_payload(results, summary, objects)
            paths["html"] = self._write_html(payload, run_name)

        return paths

    def _write_json(self, data: list, summary: dict, name: str) -> Path:
        path = self.output_dir / f"{name}.json"
        path.write_text(json.dumps({"summary": summary, "results": data}, indent=2))
        return path

    def _write_junit(self, data: list, summary: dict, name: str) -> Path:
        path = self.output_dir / f"{name}.xml"
        suite = ET.Element(
            "testsuite", name="DataSure",
            tests=str(summary.get("total_objects", 0)),
            failures=str(summary.get("total_errors", 0)),
            errors="0",
        )
        for r in data:
            case = ET.SubElement(suite, "testcase", classname=r["object_type"], name=r["object_id"])
            for issue in r["issues"]:
                if issue["severity"] == "error":
                    fail = ET.SubElement(case, "failure", message=issue["message"])
                    fail.text = json.dumps(issue["detail"])
        tree = ET.ElementTree(suite)
        ET.indent(tree)
        tree.write(str(path), encoding="unicode", xml_declaration=True)
        return path

    def _write_html(self, payload: dict, name: str) -> Path:
        path = self.output_dir / f"{name}.html"
        path.write_text(_render_app(payload, name))
        return path


# ── HTML renderer ─────────────────────────────────────────────────────────────

_SEV_COLOR = {"error": "#e74c3c", "warning": "#f39c12", "info": "#3498db"}
_SEV_BG    = {"error": "#fdecea", "warning": "#fef9e7", "info": "#eaf4fb"}

def _badge(text: str, color: str, bg: str) -> str:
    return (f'<span style="background:{bg};color:{color};border:1px solid {color};'
            f'border-radius:4px;padding:2px 7px;font-size:0.78rem;font-weight:600">{text}</span>')

def _sev_badge(sev: str) -> str:
    return _badge(sev.upper(), _SEV_COLOR.get(sev, "#999"), _SEV_BG.get(sev, "#f5f5f5"))

def _score_color(score: int) -> str:
    if score >= 80: return "#2ecc71"
    if score >= 60: return "#f39c12"
    return "#e74c3c"


def _page_overview(p: dict) -> str:
    s = p["summary"]
    score = p["score"]
    sc = _score_color(score)
    by_cat = p["by_category"]

    cat_rows = ""
    for cat, issues in sorted(by_cat.items(), key=lambda x: -len(x[1])):
        errs  = sum(1 for i in issues if i["severity"] == "error")
        warns = sum(1 for i in issues if i["severity"] == "warning")
        infos = sum(1 for i in issues if i["severity"] == "info")
        bar_w = min(100, len(issues) * 6)
        cat_rows += f"""
        <tr>
          <td><b>{cat}</b></td>
          <td>{_badge(str(errs),'#e74c3c','#fdecea') if errs else ''}</td>
          <td>{_badge(str(warns),'#f39c12','#fef9e7') if warns else ''}</td>
          <td>{_badge(str(infos),'#3498db','#eaf4fb') if infos else ''}</td>
          <td><div style="background:#e0e0e0;border-radius:4px;height:8px;width:160px">
            <div style="background:{sc};border-radius:4px;height:8px;width:{bar_w}px"></div></div></td>
          <td style="color:#666">{len(issues)} issues</td>
        </tr>"""

    top5 = [i for i in p["all_issues"] if i["severity"] == "error"][:5]
    top5_rows = "".join(
        f'<tr><td>{_sev_badge(i["severity"])}</td>'
        f'<td><code>{i["rule_id"]}</code></td>'
        f'<td>{i["object_type"]}</td>'
        f'<td><code style="font-size:0.82rem">{i["object_id"]}</code></td>'
        f'<td>{i["message"]}</td></tr>'
        for i in top5
    )

    return f"""
    <div class="page-header"><h2>Overview</h2><p>App health summary and top issues</p></div>

    <div class="stat-grid">
      <div class="stat-card"><div class="stat-val">{s['total_objects']}</div><div class="stat-lbl">Objects Checked</div></div>
      <div class="stat-card pass"><div class="stat-val">{s['passed']}</div><div class="stat-lbl">Passed</div></div>
      <div class="stat-card fail"><div class="stat-val">{s['failed']}</div><div class="stat-lbl">Failed</div></div>
      <div class="stat-card err"><div class="stat-val">{s['total_errors']}</div><div class="stat-lbl">Errors</div></div>
      <div class="stat-card warn"><div class="stat-val">{s['total_warnings']}</div><div class="stat-lbl">Warnings</div></div>
      <div class="stat-card score" style="--sc:{sc}">
        <div class="stat-val" style="color:{sc}">{score}</div>
        <div class="stat-lbl">Health Score</div>
        <div style="margin-top:6px;background:#e0e0e0;border-radius:4px;height:6px">
          <div style="background:{sc};border-radius:4px;height:6px;width:{score}%"></div>
        </div>
      </div>
    </div>

    <div class="two-col" style="margin-top:2rem">
      <div class="card">
        <div class="card-title">Issues by Validator</div>
        <table class="data-table"><thead><tr><th>Validator</th><th>Errors</th><th>Warnings</th><th>Info</th><th>Breakdown</th><th></th></tr></thead>
        <tbody>{cat_rows}</tbody></table>
      </div>
      <div class="card">
        <div class="card-title">Top Errors</div>
        {'<p style="color:#aaa;padding:1rem">No errors found</p>' if not top5 else
         f'<table class="data-table"><thead><tr><th>Sev</th><th>Rule</th><th>Type</th><th>ID</th><th>Message</th></tr></thead><tbody>{top5_rows}</tbody></table>'}
      </div>
    </div>"""


def _page_flags(p: dict) -> str:
    all_issues = p["all_issues"]
    if not all_issues:
        return '<div class="page-header"><h2>Flags</h2></div><p class="empty">No issues found.</p>'

    # group by validator
    by_cat: dict[str, list] = defaultdict(list)
    for iss in all_issues:
        by_cat[iss["validator"]].append(iss)

    _CAT_LABEL = {
        "syntax": "Syntax & Structure",
        "data_types": "Data Type Consistency",
        "field_integrity": "Field Integrity",
        "data_model_health": "Data Model Health",
        "duplicates": "Duplicate Expressions",
        "performance": "Performance Analysis",
        "load_script": "Load Script Analysis",
        "resource_optimization": "Resource Optimization",
    }

    sections = ""
    for cat, issues in sorted(by_cat.items(), key=lambda x: -len(x[1])):
        errs = sum(1 for i in issues if i["severity"] == "error")
        rows = ""
        for idx, iss in enumerate(issues):
            det = json.dumps(iss["detail"], indent=2) if iss["detail"] else ""
            det_block = (f'<pre class="detail-pre">{det}</pre>' if det else "")
            rows += f"""
            <tr class="flag-row" data-sev="{iss['severity']}" data-cat="{cat}">
              <td>{_sev_badge(iss['severity'])}</td>
              <td><code>{iss['rule_id']}</code></td>
              <td><span class="obj-chip">{iss['object_type']}</span></td>
              <td><code style="font-size:0.8rem">{iss['object_id']}</code></td>
              <td>{iss['message']}</td>
              <td>
                {'<button class="btn-res" onclick="markResolved(this)">Resolve</button>'
                 '<button class="btn-ign" onclick="markIgnored(this)">Ignore</button>'}
                {f'<button class="btn-det" onclick="toggleDetail(this)">Detail</button>' if det else ''}
              </td>
            </tr>
            {'<tr class="detail-row" style="display:none"><td colspan="6">' + det_block + '</td></tr>' if det else ''}"""

        label = _CAT_LABEL.get(cat, cat)
        badge_str = f'{_badge(str(errs),"#e74c3c","#fdecea")} ' if errs else ''
        sections += f"""
        <div class="flag-section" id="cat-{cat}">
          <div class="section-header" onclick="toggleSection(this)">
            <span class="chevron">▼</span>
            <b>{label}</b> {badge_str}
            <span style="color:#aaa;font-size:0.85rem">{len(issues)} flag{'s' if len(issues)!=1 else ''}</span>
          </div>
          <div class="section-body">
            <table class="data-table flag-table">
              <thead><tr><th>Severity</th><th>Rule</th><th>Object Type</th><th>Object ID</th><th>Message</th><th>Actions</th></tr></thead>
              <tbody>{rows}</tbody>
            </table>
          </div>
        </div>"""

    total_e = sum(1 for i in all_issues if i["severity"]=="error")
    total_w = sum(1 for i in all_issues if i["severity"]=="warning")
    total_i = sum(1 for i in all_issues if i["severity"]=="info")

    return f"""
    <div class="page-header">
      <h2>Flags</h2>
      <p>All validation findings &mdash; {len(all_issues)} total &nbsp;
         {_badge(str(total_e),'#e74c3c','#fdecea')} &nbsp;
         {_badge(str(total_w),'#f39c12','#fef9e7')} &nbsp;
         {_badge(str(total_i),'#3498db','#eaf4fb')}
      </p>
    </div>
    <div class="toolbar">
      <input id="flag-search" class="search-box" placeholder="Search flags…" oninput="filterFlags()">
      <label><input type="checkbox" id="filt-error" checked onchange="filterFlags()"> Errors</label>
      <label><input type="checkbox" id="filt-warning" checked onchange="filterFlags()"> Warnings</label>
      <label><input type="checkbox" id="filt-info" checked onchange="filterFlags()"> Info</label>
      <label><input type="checkbox" id="filt-resolved" onchange="filterFlags()"> Show Resolved</label>
    </div>
    {sections}"""


def _page_data_model(p: dict) -> str:
    dm = p["data_model"]
    tables = dm.get("tables", [])
    used_fields: set[str] = set(str(f) for f in dm.get("used_fields", set()))

    if not tables:
        return '<div class="page-header"><h2>Data Model</h2></div><p class="empty">No data model available.</p>'

    dm_issues = p["by_category"].get("data_model_health", [])
    dm_dt_issues = p["by_category"].get("data_types", [])
    all_dm = dm_issues + dm_dt_issues

    alerts = ""
    for iss in [i for i in all_dm if i["severity"] in ("error","warning")]:
        col = _SEV_COLOR.get(iss["severity"], "#999")
        alerts += f'<div class="alert" style="border-left:4px solid {col}">{_sev_badge(iss["severity"])} <b>{iss["rule_id"]}</b> — {iss["message"]}</div>'

    table_blocks = ""
    for tbl in tables:
        fname_list = tbl.get("fields", [])
        total_f = len(fname_list)
        used_f  = sum(1 for f in fname_list if f.get("name","").lower() in used_fields)
        key_f   = sum(1 for f in fname_list if f.get("is_key"))

        rows = ""
        for f in fname_list:
            fn = f.get("name", "")
            is_used = fn.lower() in used_fields
            is_key  = f.get("is_key", False)
            tags    = ", ".join(f.get("tags", []))
            status_badge = (
                _badge("KEY","#8e44ad","#f5eef8") if is_key else
                (_badge("USED","#27ae60","#eafaf1") if is_used else
                 _badge("UNUSED","#e74c3c","#fdecea"))
            )
            rows += f"<tr><td>{fn}</td><td>{status_badge}</td><td><code style='font-size:0.78rem'>{tags}</code></td></tr>"

        usage_pct = round(used_f / total_f * 100) if total_f else 0
        table_blocks += f"""
        <div class="card" style="margin-bottom:1rem">
          <div class="card-title" style="cursor:pointer" onclick="this.nextElementSibling.style.display=this.nextElementSibling.style.display==='none'?'block':'none'">
            <span>&#9660;</span> <b>{tbl['name']}</b>
            <span style="color:#aaa;font-weight:normal;font-size:0.85rem">
              &nbsp; {total_f} fields &nbsp; {key_f} keys &nbsp;
              <span style="color:{'#27ae60' if usage_pct==100 else '#f39c12' if usage_pct>50 else '#e74c3c'}">{usage_pct}% used</span>
            </span>
          </div>
          <div>
            <table class="data-table"><thead><tr><th>Field</th><th>Status</th><th>Tags</th></tr></thead>
            <tbody>{rows}</tbody></table>
          </div>
        </div>"""

    return f"""
    <div class="page-header"><h2>Data Model</h2><p>{len(tables)} tables</p></div>
    {'<div class="alerts-box">' + alerts + '</div>' if alerts else ''}
    {table_blocks}"""


def _page_objects(p: dict) -> str:
    obj_issues = p["obj_issues"]

    def _obj_table(objs: list, cols: list[tuple[str, str]]) -> str:
        if not objs:
            return '<p class="empty">None found.</p>'
        rows = ""
        for obj in objs:
            oid = obj.get("id","")
            issues = obj_issues.get(oid, [])
            errs  = sum(1 for i in issues if i["severity"]=="error")
            warns = sum(1 for i in issues if i["severity"]=="warning")
            status = (_badge("FAIL","#e74c3c","#fdecea") if errs else
                      (_badge("WARN","#f39c12","#fef9e7") if warns else
                       _badge("PASS","#27ae60","#eafaf1")))
            issue_chips = " ".join(
                f'<span title="{i["message"]}" style="cursor:help">{_sev_badge(i["severity"])} {i["rule_id"]}</span>'
                for i in issues
            )
            row = "<tr>"
            for key, _ in cols:
                val = obj.get(key, "")
                if key == "_status": val = status
                elif key == "_issues": val = issue_chips or '<span style="color:#aaa">—</span>'
                row += f"<td>{val}</td>"
            row += "</tr>"
            rows += row
        headers = "".join(f"<th>{label}</th>" for _, label in cols)
        return f'<table class="data-table"><thead><tr>{headers}</tr></thead><tbody>{rows}</tbody></table>'

    measure_cols   = [("name","Name"),("id","ID"),("label","Label"),("expression","Expression"),("_status","Status"),("_issues","Issues")]
    dim_cols       = [("name","Name"),("id","ID"),("field_def","Field Def"),("_status","Status"),("_issues","Issues")]
    viz_cols       = [("name","Name"),("id","ID"),("visualization_type","Type"),("_status","Status"),("_issues","Issues")]
    sheet_cols     = [("title","Title"),("id","ID"),("_status","Status"),("_issues","Issues")]
    app_cols       = [("name","Name"),("id","ID"),("description","Description"),("_status","Status"),("_issues","Issues")]
    var_cols       = [("name","Name"),("id","ID"),("definition","Definition"),("_issues","Issues")]

    tabs = [
        ("measures",      "Measures",      _obj_table(p["measures"],      measure_cols)),
        ("dimensions",    "Dimensions",    _obj_table(p["dimensions"],     dim_cols)),
        ("visualizations","Visualizations",_obj_table(p["visualizations"], viz_cols)),
        ("sheets",        "Sheets",        _obj_table(p["sheets"],         sheet_cols)),
        ("apps",          "Apps",          _obj_table(p["apps"],           app_cols)),
        ("variables",     "Variables",     _obj_table(p["variables"],      var_cols)),
    ]

    tab_btns  = "".join(f'<button class="tab-btn" onclick="showTab(\'obj-{k}\')" id="tbtn-obj-{k}">{label} <span class="tab-count">{len(p[k])}</span></button>' for k, label, _ in tabs)
    tab_panes = "".join(f'<div class="tab-pane" id="obj-{k}" style="display:none">{html}</div>' for k, _, html in tabs)

    return f"""
    <div class="page-header"><h2>Objects</h2><p>Browse all app objects and their validation status</p></div>
    <div class="tab-bar">{tab_btns}</div>
    {tab_panes}
    <script>
      (function(){{
        var first = document.querySelector('#objects-page .tab-btn');
        if(first) first.click();
      }})();
    </script>"""


def _page_field_usage(p: dict) -> str:
    rows = p["field_usage"]
    if not rows:
        return '<div class="page-header"><h2>Field Usage</h2></div><p class="empty">No data model available.</p>'

    used   = [r for r in rows if r["used"]]
    unused = [r for r in rows if not r["used"] and not r["is_key"]]
    keys   = [r for r in rows if r["is_key"]]

    def _tbl(items: list) -> str:
        if not items: return '<p class="empty">None.</p>'
        trs = ""
        for r in items:
            tags = ", ".join(r.get("tags",[]))
            status = (_badge("KEY","#8e44ad","#f5eef8") if r["is_key"] else
                      (_badge("USED","#27ae60","#eafaf1") if r["used"] else
                       _badge("UNUSED","#e74c3c","#fdecea")))
            trs += f"<tr><td>{r['field']}</td><td>{r['table']}</td><td>{status}</td><td><code style='font-size:0.78rem'>{tags}</code></td></tr>"
        return f'<table class="data-table"><thead><tr><th>Field</th><th>Table</th><th>Status</th><th>Tags</th></tr></thead><tbody>{trs}</tbody></table>'

    return f"""
    <div class="page-header"><h2>Field Usage</h2>
      <p>{len(rows)} total fields &mdash;
         {_badge(str(len(used)),'#27ae60','#eafaf1')} used &nbsp;
         {_badge(str(len(unused)),'#e74c3c','#fdecea')} unused &nbsp;
         {_badge(str(len(keys)),'#8e44ad','#f5eef8')} keys
      </p>
    </div>
    <div class="card" style="margin-bottom:1.5rem">
      <div class="card-title">Unused Fields</div>
      {_tbl(unused)}
    </div>
    <div class="card" style="margin-bottom:1.5rem">
      <div class="card-title">Key Fields</div>
      {_tbl(keys)}
    </div>
    <div class="card">
      <div class="card-title">Used Fields</div>
      {_tbl(used)}
    </div>"""


def _page_duplicates(p: dict) -> str:
    groups = p["dup_groups"]
    if not groups:
        return '<div class="page-header"><h2>Duplicate Expressions</h2></div><p class="empty">No duplicate expressions found.</p>'

    cards = ""
    for g in groups:
        det = g.get("detail", {})
        expr    = det.get("expression", "")
        normed  = det.get("normalised", "")
        count   = det.get("occurrences", 0)
        ids     = det.get("source_ids", [])
        names   = det.get("source_names", [])
        chips   = "".join(f'<span class="obj-chip">{n or i}</span> ' for n, i in zip(names, ids))
        cards += f"""
        <div class="card dup-card">
          <div style="display:flex;justify-content:space-between;align-items:center">
            <div><b>Expression duplicated {count}×</b></div>
            {_badge('Master Item Candidate','#8e44ad','#f5eef8')}
          </div>
          <pre class="expr-pre">{expr}</pre>
          <div style="margin-top:0.5rem;color:#666;font-size:0.85rem">Found in: {chips}</div>
          {'<details style="margin-top:0.5rem"><summary style="cursor:pointer;color:#aaa;font-size:0.8rem">Normalised form</summary><pre class="detail-pre">' + normed + '</pre></details>' if normed != expr else ''}
        </div>"""

    return f"""
    <div class="page-header"><h2>Duplicate Expressions</h2>
      <p>{len(groups)} duplicate group{'s' if len(groups)!=1 else ''} found — consolidation recommended</p>
    </div>
    {cards}"""


def _page_performance(p: dict) -> str:
    """Phase 3: Performance, Load Script, and Resource Optimization findings."""
    issues = p.get("perf_issues", [])

    _RULE_HELP = {
        "PERF001": ("Sheet Density", "Too many visualizations on one sheet slows rendering."),
        "PERF002": ("Nested Aggr()", "Nested Aggr() calls multiply query evaluation cost."),
        "PERF003": ("Multiple Set Modifiers", "Multiple {<...>} modifiers in one expression are expensive."),
        "PERF004": ("P()/E() Functions", "Possible/excluded set functions scan the full data model."),
        "PERF005": ("App Scale", "Too many sheets impacts app open time."),
        "LS001":   ("Orphaned Script Table", "Table defined in load script but absent from data model."),
        "LS002":   ("Direct SQL Load", "SQL SELECT without a QVD layer reloads from source every time."),
        "LS003":   ("INLINE Data", "Large INLINE blocks are not scalable."),
        "LS004":   ("Star LOAD", "LOAD * FROM is fragile — explicit field lists are safer."),
        "LS005":   ("Undocumented Script", "Script sections lack comments."),
        "RO001":   ("No Master Measures", "App has many inline measures but no Master Measures."),
        "RO002":   ("No Master Dimensions", "App has inline dimensions but no Master Dimensions."),
        "RO003":   ("Unused Variable", "Variable defined but never referenced in expressions."),
        "RO004":   ("Low Master Item Adoption", "Most measures are still inline despite some master items."),
    }

    _SECTION_GROUPS = {
        "Performance Analysis": ["PERF001","PERF002","PERF003","PERF004","PERF005"],
        "Load Script Analysis": ["LS001","LS002","LS003","LS004","LS005"],
        "Resource Optimization": ["RO001","RO002","RO003","RO004"],
    }

    if not issues:
        return """
        <div class="page-header"><h2>Performance &amp; Optimization</h2></div>
        <p class="empty">No performance or optimization issues found. Great work!</p>"""

    sections_html = ""
    for section_title, rule_ids in _SECTION_GROUPS.items():
        grp = [i for i in issues if i["rule_id"] in rule_ids]
        if not grp:
            continue
        rows = ""
        for iss in grp:
            det = iss.get("detail", {})
            rule_name, rule_help = _RULE_HELP.get(iss["rule_id"], (iss["rule_id"], ""))
            det_summary = ""
            if "expression" in det:
                det_summary = f'<code style="font-size:0.78rem;color:#666">{str(det["expression"])[:80]}{"…" if len(str(det.get("expression","")))>80 else ""}</code>'
            elif det:
                det_summary = " &nbsp; ".join(
                    f'<span style="color:#888;font-size:0.8rem">{k}: <b>{v}</b></span>'
                    for k, v in list(det.items())[:3]
                )
            rows += f"""
            <tr>
              <td>{_sev_badge(iss['severity'])}</td>
              <td><code>{iss['rule_id']}</code></td>
              <td><b>{rule_name}</b><br><span style="color:#888;font-size:0.8rem">{rule_help}</span></td>
              <td><span class="obj-chip">{iss['object_type']}</span></td>
              <td>{iss['message']}</td>
              <td>{det_summary}</td>
            </tr>"""

        e = sum(1 for i in grp if i["severity"]=="error")
        sections_html += f"""
        <div class="flag-section" style="margin-bottom:1rem">
          <div class="section-header" onclick="toggleSection(this)">
            <span class="chevron">▼</span>
            <b>{section_title}</b>
            {_badge(str(e),"#e74c3c","#fdecea") + "&nbsp;" if e else ""}
            <span style="color:#aaa;font-size:0.85rem">{len(grp)} finding{'s' if len(grp)!=1 else ''}</span>
          </div>
          <div class="section-body">
            <table class="data-table">
              <thead><tr><th>Sev</th><th>Rule</th><th>Category</th><th>Object</th><th>Message</th><th>Detail</th></tr></thead>
              <tbody>{rows}</tbody>
            </table>
          </div>
        </div>"""

    total_e = sum(1 for i in issues if i["severity"]=="error")
    total_w = sum(1 for i in issues if i["severity"]=="warning")
    total_i = sum(1 for i in issues if i["severity"]=="info")

    return f"""
    <div class="page-header">
      <h2>Performance &amp; Optimization</h2>
      <p>{len(issues)} findings &mdash;
         {_badge(str(total_e),'#e74c3c','#fdecea')} &nbsp;
         {_badge(str(total_w),'#f39c12','#fef9e7')} &nbsp;
         {_badge(str(total_i),'#3498db','#eaf4fb')}
      </p>
    </div>
    {sections_html}"""


# ── full app render ───────────────────────────────────────────────────────────

def _render_app(payload: dict, title: str) -> str:
    pages = [
        ("overview",    "📊", "Overview",             _page_overview(payload)),
        ("flags",       "🚩", "Flags",                _page_flags(payload)),
        ("data-model",  "🗄", "Data Model",           _page_data_model(payload)),
        ("objects",     "📦", "Objects",              _page_objects(payload)),
        ("field-usage", "🔗", "Field Usage",          _page_field_usage(payload)),
        ("duplicates",  "♻",  "Duplicates",           _page_duplicates(payload)),
        ("performance", "⚡", "Performance",          _page_performance(payload)),
    ]

    nav_items = "".join(
        f'<li><a href="#" class="nav-link" id="nav-{pid}" onclick="showPage(\'{pid}\');return false">'
        f'<span class="nav-icon">{icon}</span><span class="nav-label">{label}</span></a></li>'
        for pid, icon, label, _ in pages
    )

    page_divs = "".join(
        f'<div class="page" id="page-{pid}" style="display:none">{html}</div>'
        for pid, _, _, html in pages
    )

    score = payload["score"]
    sc = _score_color(score)
    s  = payload["summary"]

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>DataSure — {title}</title>
  <style>
    *,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f0f2f5;color:#2c3e50;min-height:100vh;display:flex}}

    /* Sidebar */
    #sidebar{{width:220px;min-width:220px;background:#1a2332;color:#cfd8e3;display:flex;flex-direction:column;padding:0}}
    .sidebar-brand{{padding:1.4rem 1.2rem 1rem;border-bottom:1px solid #263548}}
    .sidebar-brand .brand-name{{font-size:1.3rem;font-weight:700;color:#fff;letter-spacing:-0.5px}}
    .sidebar-brand .brand-sub{{font-size:0.72rem;color:#6b8aad;margin-top:2px}}
    .sidebar-score{{padding:1rem 1.2rem;border-bottom:1px solid #263548;text-align:center}}
    .sidebar-score .score-val{{font-size:2.5rem;font-weight:800;color:{sc}}}
    .sidebar-score .score-lbl{{font-size:0.7rem;color:#6b8aad;text-transform:uppercase;letter-spacing:1px}}
    .score-bar{{background:#263548;border-radius:4px;height:5px;margin-top:6px}}
    .score-fill{{background:{sc};border-radius:4px;height:5px;width:{score}%}}
    nav ul{{list-style:none;padding:0.5rem 0}}
    .nav-link{{display:flex;align-items:center;gap:10px;padding:0.65rem 1.2rem;color:#8fa8c4;text-decoration:none;font-size:0.9rem;transition:background 0.15s,color 0.15s;border-left:3px solid transparent}}
    .nav-link:hover{{background:#263548;color:#fff}}
    .nav-link.active{{background:#263548;color:#fff;border-left-color:#4a9eff}}
    .nav-icon{{font-size:1.1rem;width:20px;text-align:center}}
    .sidebar-stats{{padding:1rem 1.2rem;border-top:1px solid #263548;margin-top:auto}}
    .mini-stat{{display:flex;justify-content:space-between;font-size:0.78rem;padding:3px 0;color:#6b8aad}}
    .mini-stat span:last-child{{font-weight:600;color:#cfd8e3}}

    /* Main content */
    #main{{flex:1;overflow-y:auto;padding:2rem}}
    .page-header{{margin-bottom:1.5rem}}
    .page-header h2{{font-size:1.6rem;font-weight:700;color:#1a2332}}
    .page-header p{{color:#6b8aad;margin-top:4px;font-size:0.9rem}}

    /* Stat cards */
    .stat-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:1rem}}
    .stat-card{{background:#fff;border-radius:10px;padding:1.2rem;box-shadow:0 1px 4px rgba(0,0,0,.07);border-top:3px solid #e0e6ef}}
    .stat-card.pass{{border-top-color:#2ecc71}}.stat-card.fail{{border-top-color:#e74c3c}}
    .stat-card.err{{border-top-color:#e74c3c}}.stat-card.warn{{border-top-color:#f39c12}}
    .stat-card.score{{border-top-color:{sc}}}
    .stat-val{{font-size:2rem;font-weight:800;color:#1a2332;line-height:1}}
    .stat-lbl{{font-size:0.75rem;color:#6b8aad;margin-top:4px;text-transform:uppercase;letter-spacing:0.5px}}

    /* Cards */
    .card{{background:#fff;border-radius:10px;padding:1.2rem 1.4rem;box-shadow:0 1px 4px rgba(0,0,0,.07);margin-bottom:1rem}}
    .card-title{{font-weight:600;font-size:0.95rem;margin-bottom:1rem;color:#1a2332;border-bottom:1px solid #f0f2f5;padding-bottom:0.6rem}}
    .two-col{{display:grid;grid-template-columns:1fr 1fr;gap:1rem}}

    /* Tables */
    .data-table{{width:100%;border-collapse:collapse;font-size:0.85rem}}
    .data-table th{{background:#f7f9fc;color:#6b8aad;font-weight:600;padding:8px 10px;text-align:left;border-bottom:2px solid #e0e6ef;font-size:0.78rem;text-transform:uppercase;letter-spacing:0.5px}}
    .data-table td{{padding:8px 10px;border-bottom:1px solid #f0f2f5;vertical-align:top;max-width:320px;word-break:break-word}}
    .data-table tr:hover td{{background:#f7faff}}
    .data-table code{{background:#f0f2f5;padding:1px 5px;border-radius:3px;font-size:0.82rem}}

    /* Flags */
    .flag-section{{background:#fff;border-radius:10px;margin-bottom:0.8rem;box-shadow:0 1px 4px rgba(0,0,0,.07);overflow:hidden}}
    .section-header{{display:flex;align-items:center;gap:10px;padding:0.9rem 1.2rem;cursor:pointer;border-bottom:1px solid #f0f2f5;font-size:0.92rem}}
    .section-header:hover{{background:#f7faff}}
    .section-body{{padding:0 0 0.5rem}}
    .section-body .data-table{{margin:0}}
    .chevron{{font-size:0.7rem;color:#aaa;transition:transform 0.2s;display:inline-block}}
    .flag-row.resolved td{{opacity:0.4;text-decoration:line-through}}
    .flag-row.ignored td{{opacity:0.3}}
    .detail-pre{{background:#f7f9fc;padding:0.8rem 1rem;font-size:0.8rem;border-radius:4px;overflow-x:auto;margin:4px 10px 8px}}
    .btn-res,.btn-ign,.btn-det{{border:none;border-radius:4px;padding:2px 8px;font-size:0.75rem;cursor:pointer;margin-right:3px}}
    .btn-res{{background:#eafaf1;color:#27ae60}}.btn-ign{{background:#fef9e7;color:#f39c12}}.btn-det{{background:#f0f2f5;color:#6b8aad}}

    /* Toolbar */
    .toolbar{{display:flex;align-items:center;gap:1rem;margin-bottom:1.2rem;flex-wrap:wrap}}
    .search-box{{border:1px solid #dde3ec;border-radius:6px;padding:6px 12px;font-size:0.88rem;width:240px;outline:none}}
    .search-box:focus{{border-color:#4a9eff;box-shadow:0 0 0 3px #eaf4ff}}
    .toolbar label{{font-size:0.85rem;color:#6b8aad;display:flex;align-items:center;gap:4px;cursor:pointer}}

    /* Tabs */
    .tab-bar{{display:flex;gap:4px;margin-bottom:1rem;flex-wrap:wrap}}
    .tab-btn{{border:none;background:#fff;border-radius:8px;padding:7px 14px;font-size:0.85rem;cursor:pointer;color:#6b8aad;box-shadow:0 1px 3px rgba(0,0,0,.08)}}
    .tab-btn.active{{background:#4a9eff;color:#fff;box-shadow:0 2px 6px rgba(74,158,255,.35)}}
    .tab-count{{background:rgba(0,0,0,.08);border-radius:10px;padding:1px 6px;font-size:0.72rem;margin-left:4px}}
    .tab-pane{{display:none}}

    /* Misc */
    .obj-chip{{background:#eef2f8;color:#4a6fa5;border-radius:4px;padding:2px 7px;font-size:0.78rem;font-weight:500}}
    .alerts-box{{margin-bottom:1rem}}
    .alert{{background:#fff;border-radius:6px;padding:0.7rem 1rem;margin-bottom:0.5rem;font-size:0.88rem;box-shadow:0 1px 3px rgba(0,0,0,.06)}}
    .empty{{color:#aaa;padding:1.5rem;text-align:center;font-style:italic}}
    .dup-card{{margin-bottom:1rem}}
    .expr-pre{{background:#1a2332;color:#a8d8ea;padding:0.8rem 1rem;border-radius:6px;font-size:0.88rem;margin-top:0.7rem;overflow-x:auto}}

    @media(max-width:768px){{
      #sidebar{{display:none}}
      .two-col{{grid-template-columns:1fr}}
    }}
  </style>
</head>
<body>
<div id="sidebar">
  <div class="sidebar-brand">
    <div class="brand-name">DataSure</div>
    <div class="brand-sub">Analytics QA Platform</div>
  </div>
  <div class="sidebar-score">
    <div class="score-val">{score}</div>
    <div class="score-lbl">Health Score</div>
    <div class="score-bar"><div class="score-fill"></div></div>
  </div>
  <nav><ul>{nav_items}</ul></nav>
  <div class="sidebar-stats">
    <div class="mini-stat"><span>Objects</span><span>{s['total_objects']}</span></div>
    <div class="mini-stat"><span>Errors</span><span style="color:#e74c3c">{s['total_errors']}</span></div>
    <div class="mini-stat"><span>Warnings</span><span style="color:#f39c12">{s['total_warnings']}</span></div>
    <div class="mini-stat"><span>Pass rate</span><span>{round(s['passed']/max(s['total_objects'],1)*100)}%</span></div>
  </div>
</div>

<div id="main">
  {page_divs}
</div>

<script>
function showPage(id) {{
  document.querySelectorAll('.page').forEach(p => p.style.display='none');
  document.querySelectorAll('.nav-link').forEach(a => a.classList.remove('active'));
  var pg = document.getElementById('page-'+id);
  if(pg) pg.style.display='block';
  var lnk = document.getElementById('nav-'+id);
  if(lnk) lnk.classList.add('active');
  // activate first tab on objects page
  if(id==='objects') {{
    var first = document.querySelector('#page-objects .tab-btn');
    if(first) first.click();
  }}
}}

function showTab(id) {{
  var pane = document.getElementById(id);
  if(!pane) return;
  var container = pane.closest('.page');
  container.querySelectorAll('.tab-pane').forEach(p=>p.style.display='none');
  container.querySelectorAll('.tab-btn').forEach(b=>b.classList.remove('active'));
  pane.style.display='block';
  var prefix = id.split('-').slice(0,2).join('-');
  container.querySelectorAll('.tab-btn').forEach(b=>{{
    if(b.getAttribute('onclick')&&b.getAttribute('onclick').includes("'"+id+"'")) b.classList.add('active');
  }});
}}

function toggleSection(hdr) {{
  var body = hdr.nextElementSibling;
  var chevron = hdr.querySelector('.chevron');
  if(body.style.display==='none'){{body.style.display='block';chevron.style.transform='';}}
  else{{body.style.display='none';chevron.style.transform='rotate(-90deg)';}}
}}

function markResolved(btn) {{
  var row = btn.closest('tr');
  row.classList.toggle('resolved');
}}
function markIgnored(btn) {{
  var row = btn.closest('tr');
  row.classList.toggle('ignored');
}}
function toggleDetail(btn) {{
  var row = btn.closest('tr');
  var det = row.nextElementSibling;
  if(det && det.classList.contains('detail-row'))
    det.style.display = det.style.display==='none'?'table-row':'none';
}}

function filterFlags() {{
  var q      = (document.getElementById('flag-search')||{{}}).value||'';
  var showE  = document.getElementById('filt-error')&&document.getElementById('filt-error').checked;
  var showW  = document.getElementById('filt-warning')&&document.getElementById('filt-warning').checked;
  var showI  = document.getElementById('filt-info')&&document.getElementById('filt-info').checked;
  var showR  = document.getElementById('filt-resolved')&&document.getElementById('filt-resolved').checked;
  q = q.toLowerCase();
  document.querySelectorAll('.flag-row').forEach(row => {{
    var sev = row.dataset.sev||'';
    var txt = row.innerText.toLowerCase();
    var sevOk = (sev==='error'&&showE)||(sev==='warning'&&showW)||(sev==='info'&&showI);
    var resOk = showR || !row.classList.contains('resolved');
    var qOk   = !q || txt.includes(q);
    row.style.display = (sevOk&&resOk&&qOk)?'':'none';
    var det = row.nextElementSibling;
    if(det&&det.classList.contains('detail-row')) det.style.display='none';
  }});
}}

// Boot — honour URL hash for direct linking and headless screenshots
(function() {{
  var hash = window.location.hash.replace('#','');
  var valid = ['overview','flags','data-model','objects','field-usage','duplicates','performance'];
  showPage(valid.indexOf(hash) >= 0 ? hash : 'overview');
  window.addEventListener('hashchange', function() {{
    var h = window.location.hash.replace('#','');
    if (valid.indexOf(h) >= 0) showPage(h);
  }});
}})();
</script>
</body>
</html>"""

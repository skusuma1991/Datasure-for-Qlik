from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from datasure.config.settings import QlikSenseSettings

log = logging.getLogger(__name__)

_XRF = "abcdefghijklmnop"

# ── demo data ─────────────────────────────────────────────────────────────────

DEMO_APPS = [
    {"type": "app", "id": "demo-app-001", "name": "Sales Dashboard",      "description": "Monthly sales KPIs by region and product", "published": True,  "stream": "Finance",    "owner": "INTERNAL\\john.smith",   "last_reload": "2026-06-01T08:00:00Z"},
    {"type": "app", "id": "demo-app-002", "name": "HR Overview",          "description": "",                                          "published": True,  "stream": "HR",         "owner": "INTERNAL\\jane.doe",     "last_reload": "2026-05-28T14:30:00Z"},
    {"type": "app", "id": "demo-app-003", "name": "Supply Chain Monitor", "description": "Inventory and logistics tracking",          "published": False, "stream": "",           "owner": "INTERNAL\\bob.jones",    "last_reload": "2026-06-03T06:15:00Z"},
]

_DEMO_LOAD_SCRIPT = """\
// $tab Main
// Config variables
SET vDataPath = 'lib://DataFiles/';

// $tab FactSales
FactSales:
LOAD
    OrderID,
    CustomerID,
    ProductID,
    Revenue,
    OrderDate,
    OrderValue
FROM [lib://DataFiles/sales.csv] (txt, utf8, embedded labels, delimiter is ',');

// $tab DimCustomer
DimCustomer:
LOAD
    CustomerID,
    Region,
    CustomerName
FROM [lib://DataFiles/customers.qvd] (qvd);

// $tab DimProduct  -- no QVD layer, loading directly from DB
DimProduct:
SQL SELECT ProductID, CustomerID, ProductName FROM products_table;

// $tab StagingTemp
StagingTemp:
LOAD * INLINE [
    TempID, TempVal
    1, Alpha
    2, Beta
    3, Gamma
];

// Orphaned table — loaded but never used in the data model
OrphanedAuditLog:
LOAD * FROM [lib://DataFiles/audit_old.qvd] (qvd);

// LOAD * (star load) — fragile
DimCategory:
LOAD * FROM [lib://DataFiles/categories.qvd] (qvd);
"""


def _demo_objects(app_id: str) -> list[dict[str, Any]]:
    # 17 cells on the crowded sheet to trigger PERF001 warning
    crowded_cells = [{"type": "barchart"}] * 17
    return [
        {"type": "app", "id": app_id, "name": "Sales Dashboard",
         "description": "Monthly sales KPIs", "sheet_count": 4,
         "load_script": _DEMO_LOAD_SCRIPT},
        # variables — vCurrYear is never used in any expression (triggers RO003)
        {"type": "variable",  "id": "var-001", "name": "vSalesExpr", "definition": "Sum(Revenue)"},
        {"type": "variable",  "id": "var-002", "name": "vCurrYear",  "definition": "Year(Today())"},
        # sheets
        {"type": "sheet", "id": "sheet-001", "name": "Overview",
         "title": "Executive Overview", "cells": [{"type": "barchart"}, {"type": "kpi"}]},
        {"type": "sheet", "id": "sheet-002", "name": "Empty Sheet",
         "title": "Work In Progress", "cells": []},
        {"type": "sheet", "id": "sheet-003", "name": "Crowded Detail",
         "title": "Detail View", "cells": crowded_cells},
        # master measures (only 1 out of many → RO004 low adoption)
        {"type": "measure", "id": "master-001", "name": "Total Revenue (Master)",
         "expression": "Sum(Revenue)", "label": "Total Revenue", "is_master": True,
         "number_format": {"fmt": "#,##0.00"}, "expected_type": "numeric"},
        # inline measures
        {"type": "measure", "id": "meas-001",  "name": "Total Revenue",
         "expression": "Sum(Revenue)", "label": "Total Revenue",
         "number_format": {"fmt": "#,##0.00"}, "expected_type": "numeric"},
        {"type": "measure", "id": "meas-001b", "name": "Revenue Copy",
         "expression": "Sum(Revenue)", "label": "Revenue Copy",
         "number_format": {"fmt": "#,##0.00"}, "expected_type": "numeric"},
        {"type": "measure", "id": "meas-001c", "name": "Revenue via Var",
         "expression": "$(vSalesExpr)", "label": "Revenue (var)",
         "number_format": {"fmt": "#,##0.00"}, "expected_type": "numeric"},
        {"type": "measure", "id": "meas-002",  "name": "Avg Order Value",
         "expression": "Avg(OrderValue)", "label": "",
         "number_format": {}, "expected_type": "numeric"},
        {"type": "measure", "id": "meas-003",  "name": "Broken Measure",
         "expression": "   ", "label": "Broken",
         "number_format": {}, "expected_type": "numeric"},
        {"type": "measure", "id": "meas-005",  "name": "Ghost Metric",
         "expression": "Sum(GhostField)", "label": "Ghost",
         "number_format": {}, "expected_type": "numeric"},
        {"type": "measure", "id": "meas-006",  "name": "Set Analysis Bad",
         "expression": "Sum({<DeletedStatus={'Active'}>} Revenue)", "label": "Bad Set",
         "number_format": {}, "expected_type": "numeric"},
        {"type": "measure", "id": "meas-007",  "name": "Count by Key",
         "expression": "Count(CustomerID)", "label": "Cust Count",
         "number_format": {}, "expected_type": "numeric"},
        {"type": "measure", "id": "meas-008",  "name": "Ref Deleted Master",
         "expression": "Sum(Revenue)", "label": "Old Master Ref",
         "master_item_id": "master-deleted-999",
         "number_format": {}, "expected_type": "numeric"},
        # two Aggr() calls in one expression — triggers PERF002
        {"type": "measure", "id": "meas-009",  "name": "Double Aggr",
         "expression": "Aggr(Sum(Revenue), Region) + Aggr(Sum(OrderValue), ProductID)",
         "label": "Double Aggr", "number_format": {}, "expected_type": "numeric"},
        # P() set function — triggers PERF004
        {"type": "measure", "id": "meas-010",  "name": "Expensive P()",
         "expression": "Sum({<CustomerID=P({<Region={'North'}>}CustomerID)>}Revenue)",
         "label": "P() Measure", "number_format": {}, "expected_type": "numeric"},
        # dimensions
        {"type": "dimension", "id": "dim-001", "name": "Region",    "field_def": "Region",   "tags": ["$ascii"]},
        {"type": "dimension", "id": "dim-002", "name": "Empty Dim", "field_def": "",          "tags": []},
        # visualizations
        {"type": "visualization", "id": "viz-001", "name": "Revenue Bar",
         "visualization_type": "barchart", "properties": {"title": "Revenue by Region"}},
        {"type": "visualization", "id": "viz-002", "name": "Mystery Chart",
         "visualization_type": "", "properties": {"title": ""}},
        # data model
        {"type": "data_model", "id": app_id,
         "used_fields": {"revenue", "ordervalue", "orderdate", "region", "customerid"},
         "tables": [
            {"name": "FactSales",   "fields": [
                {"name": "Revenue",    "tags": ["$numeric"],          "is_key": False},
                {"name": "OrderValue", "tags": ["$numeric"],          "is_key": False},
                {"name": "OrderDate",  "tags": ["$date", "$numeric"], "is_key": False},
                {"name": "CustomerID", "tags": ["$numeric"],          "is_key": True},
                {"name": "ProductID",  "tags": ["$numeric"],          "is_key": True},
                {"name": "Category",   "tags": [],                    "is_key": False},
                {"name": "LoadBatch",  "tags": ["$numeric"],          "is_key": False},
            ]},
            {"name": "DimCustomer", "fields": [
                {"name": "CustomerID",  "tags": ["$numeric"], "is_key": True},
                {"name": "Region",      "tags": ["$ascii"],   "is_key": False},
            ]},
            {"name": "DimProduct",  "fields": [
                {"name": "ProductID",   "tags": ["$numeric"], "is_key": True},
                {"name": "CustomerID",  "tags": ["$numeric"], "is_key": True},
                {"name": "ProductName", "tags": ["$ascii"],   "is_key": False},
            ]},
            {"name": "StagingTemp", "fields": [
                {"name": "TempID",  "tags": ["$numeric"], "is_key": False},
                {"name": "TempVal", "tags": ["$ascii"],   "is_key": False},
            ]},
        ]},
    ]


# ── session factory ───────────────────────────────────────────────────────────

def _make_session(s: QlikSenseSettings) -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=s.retries,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    if s.mode == "enterprise":
        if s.cert_path and s.key_path:
            session.cert = (str(s.cert_path), str(s.key_path))
        if s.ca_cert:
            session.verify = str(s.ca_cert)
        else:
            session.verify = s.verify_ssl

    elif s.mode == "cloud":
        session.headers.update({
            "Authorization": f"Bearer {s.api_key}",
            "Content-Type": "application/json",
        })
        session.verify = True

    elif s.mode == "desktop":
        session.verify = False

    return session


# ── connector ─────────────────────────────────────────────────────────────────

class QlikSenseConnector:
    """
    Unified connector for:
      - Qlik Sense Enterprise on Windows  (mode: enterprise)  — QRS REST API + certs
      - Qlik Cloud / SaaS                 (mode: cloud)       — REST API v1 + API key
      - Qlik Sense Desktop                (mode: desktop)     — local QRS, no auth
      - Demo / offline                    (mode: demo)        — built-in dummy data, no network
    """

    def __init__(self, settings: QlikSenseSettings) -> None:
        self.settings = settings
        self._session = _make_session(settings) if settings.mode != "demo" else None
        self._mode = settings.mode

        if self._mode == "cloud":
            self._base = f"https://{settings.tenant}/api/v1"
        elif self._mode == "desktop":
            self._base = f"http://{settings.host}:4848/qrs"
        else:
            vp = f"/{settings.virtual_proxy}" if settings.virtual_proxy else ""
            self._base = f"https://{settings.host}:{settings.port}{vp}/qrs"

    # ── low-level request helpers ─────────────────────────────────────────────

    def _qrs_get(self, path: str, params: dict | None = None) -> Any:
        """QRS API call (Enterprise / Desktop) — needs XRF key."""
        url = f"{self._base}/{path.lstrip('/')}"
        log.debug("QRS GET %s", url)
        resp = self._session.get(
            url,
            params={"xrfkey": _XRF, **(params or {})},
            headers={
                "X-Qlik-Xrfkey": _XRF,
                "X-Qlik-User": f"UserDirectory={self.settings.user_directory};UserId={self.settings.user_id}",
            },
            timeout=self.settings.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def _cloud_get(self, path: str, params: dict | None = None) -> Any:
        """Qlik Cloud REST v1 call — auth via Bearer token in session headers."""
        url = f"{self._base}/{path.lstrip('/')}"
        log.debug("Cloud GET %s", url)
        resp = self._session.get(url, params=params or {}, timeout=self.settings.timeout)
        resp.raise_for_status()
        return resp.json()

    def _get(self, path: str, params: dict | None = None) -> Any:
        if self._mode == "cloud":
            return self._cloud_get(path, params)
        return self._qrs_get(path, params)

    # ── connectivity check ────────────────────────────────────────────────────

    def test_connection(self) -> dict[str, Any]:
        """
        Verify connectivity and auth. Returns a dict with success/error info.
        Use this before running a full analysis.
        """
        if self._mode == "demo":
            return {
                "ok": True,
                "mode": "demo",
                "note": "Running in demo mode — no real Qlik connection required",
                "apps_available": len(DEMO_APPS),
            }
        try:
            if self._mode == "cloud":
                data = self._cloud_get("users/me")
                return {
                    "ok": True,
                    "mode": "cloud",
                    "tenant": self.settings.tenant,
                    "user": data.get("name") or data.get("subject", "unknown"),
                }
            else:
                data = self._qrs_get("about")
                return {
                    "ok": True,
                    "mode": self._mode,
                    "host": self.settings.host,
                    "version": data.get("buildVersion", "unknown"),
                    "product": data.get("productName", "Qlik Sense"),
                }
        except requests.exceptions.SSLError as exc:
            return {"ok": False, "error": f"SSL error — check cert_path / ca_cert: {exc}"}
        except requests.exceptions.ConnectionError as exc:
            return {"ok": False, "error": f"Cannot reach host: {exc}"}
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "?"
            hints = {
                401: "Unauthorized — check api_key (cloud) or certificates (enterprise)",
                403: "Forbidden — user lacks QRS access (enterprise: use sa_repository)",
                404: "Not found — wrong host/port/virtual_proxy?",
            }
            return {"ok": False, "error": f"HTTP {status} — {hints.get(status, str(exc))}"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ── app listing ───────────────────────────────────────────────────────────

    def list_apps(self) -> list[dict[str, Any]]:
        if self._mode == "demo":
            return DEMO_APPS
        if self._mode == "cloud":
            return self._list_apps_cloud()
        return self._list_apps_qrs()

    def _list_apps_qrs(self) -> list[dict[str, Any]]:
        raw = self._qrs_get("app/full")
        return [
            {
                "type": "app",
                "id": item.get("id"),
                "name": item.get("name", ""),
                "description": item.get("description", ""),
                "last_reload": item.get("lastReloadTime"),
                "published": item.get("published", False),
                "stream": (item.get("stream") or {}).get("name", ""),
                "owner": (item.get("owner") or {}).get("userDirectory", ""),
            }
            for item in raw
        ]

    def _list_apps_cloud(self) -> list[dict[str, Any]]:
        raw = self._cloud_get("items", {"resourceType": "app", "limit": 200})
        apps = []
        for item in raw.get("data", []):
            attr = item.get("resourceAttributes", {})
            apps.append({
                "type": "app",
                "id": item.get("resourceId", ""),
                "name": attr.get("name", ""),
                "description": attr.get("description", ""),
                "last_reload": attr.get("lastReloadTime"),
                "published": item.get("resourceCustomAttributes", {}).get("published", False),
                "stream": item.get("spaceId", ""),
                "owner": item.get("ownerId", ""),
            })
        return apps

    # ── app object extraction ─────────────────────────────────────────────────

    def get_app_objects(self, app_id: str) -> list[dict[str, Any]]:
        if self._mode == "demo":
            return [o for o in _demo_objects(app_id) if o.get("type") != "data_model"]
        if self._mode == "cloud":
            return self._get_app_objects_cloud(app_id)
        return self._get_app_objects_qrs(app_id)

    def _get_app_objects_qrs(self, app_id: str) -> list[dict[str, Any]]:
        raw = self._qrs_get("app/object/full", params={"filter": f"app.id eq {app_id}"})
        objects = []
        for item in raw:
            obj_type = item.get("objectType", "").lower()
            mapped: dict[str, Any] = {
                "type": obj_type,
                "id": item.get("id"),
                "name": item.get("name", ""),
                "app_id": app_id,
                "published": item.get("published", False),
            }
            props = item.get("properties", {})
            if obj_type == "sheet":
                mapped["title"] = props.get("title", mapped["name"])
                mapped["cells"] = props.get("cells", [])
            elif obj_type in ("measure", "masterobject"):
                mapped["expression"] = (
                    props.get("measureExpression")
                    or props.get("qMetaDef", {}).get("expr", "")
                )
                mapped["label"] = props.get("label", "")
                mapped["number_format"] = props.get("numberFormat", {})
                mapped["is_master"] = obj_type == "masterobject"
            elif obj_type == "dimension":
                mapped["field_def"] = (
                    props.get("fieldDef")
                    or props.get("qMetaDef", {}).get("fieldDef", "")
                )
                mapped["tags"] = props.get("tags", [])
            elif obj_type == "variable":
                mapped["definition"] = props.get("qDefinition", "")
            objects.append(mapped)
        return objects

    def _get_app_objects_cloud(self, app_id: str) -> list[dict[str, Any]]:
        raw = self._cloud_get(f"apps/{app_id}/objects")
        objects = []
        for item in raw.get("data", []):
            obj_type = (item.get("objectType") or item.get("type") or "").lower()
            mapped: dict[str, Any] = {
                "type": obj_type,
                "id": item.get("id"),
                "name": item.get("name", ""),
                "app_id": app_id,
            }
            props = item.get("properties", {})
            if obj_type == "sheet":
                mapped["title"] = (props.get("qMetaDef") or {}).get("title", mapped["name"])
                mapped["cells"] = props.get("cells", [])
            elif obj_type in ("measure", "masterobject"):
                mapped["expression"] = (props.get("qMeasure") or {}).get("qDef", "")
                mapped["label"] = (props.get("qMeasure") or {}).get("qLabel", "")
                mapped["number_format"] = (props.get("qMeasure") or {}).get("qNumFormat", {})
                mapped["is_master"] = obj_type == "masterobject"
            elif obj_type == "dimension":
                dim = props.get("qDim") or {}
                mapped["field_def"] = " ".join(dim.get("qFieldDefs", []))
                mapped["tags"] = dim.get("qTags", [])
            elif obj_type == "variable":
                mapped["definition"] = (props.get("qVar") or {}).get("qDefinition", "")
            objects.append(mapped)
        return objects

    # ── data model ────────────────────────────────────────────────────────────

    def get_data_model(self, app_id: str) -> dict[str, Any]:
        if self._mode == "demo":
            return next(o for o in _demo_objects(app_id) if o.get("type") == "data_model")
        if self._mode == "cloud":
            return self._get_data_model_cloud(app_id)
        return self._get_data_model_qrs(app_id)

    def _get_data_model_qrs(self, app_id: str) -> dict[str, Any]:
        try:
            raw = self._qrs_get(f"datamodel/app/{app_id}/tables")
        except Exception:
            log.warning("Data model endpoint unavailable for app %s", app_id)
            return {"type": "data_model", "id": app_id, "tables": []}
        tables = [
            {
                "name": t.get("name"),
                "fields": [
                    {"name": f.get("name"), "tags": f.get("tags", []), "is_key": f.get("isKey", False)}
                    for f in t.get("fields", [])
                ],
            }
            for t in raw.get("tables", [])
        ]
        return {"type": "data_model", "id": app_id, "tables": tables}

    def _get_data_model_cloud(self, app_id: str) -> dict[str, Any]:
        try:
            raw = self._cloud_get(f"apps/{app_id}/datamodel/outline")
        except Exception:
            log.warning("Data model endpoint unavailable for app %s (cloud)", app_id)
            return {"type": "data_model", "id": app_id, "tables": []}
        tables = []
        for t in raw.get("qtr", []):
            fields = [
                {"name": f.get("qName"), "tags": f.get("qTags", []), "is_key": f.get("qKeyType") != "NOT_KEY"}
                for f in t.get("qFields", [])
            ]
            tables.append({"name": t.get("qName"), "fields": fields})
        return {"type": "data_model", "id": app_id, "tables": tables}

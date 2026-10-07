#!/usr/bin/env python3
"""
LocalBase — Your self-hosted backend. Simple, local, and yours.

A lightweight, single-file Supabase alternative written in pure Python.
Run: python localbase.py
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import secrets
import shutil
import sqlite3
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

try:
    from fastapi import (
        FastAPI, Request, HTTPException, Depends, WebSocket, WebSocketDisconnect,
        UploadFile, File, Header, Query
    )
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import (
        HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse, FileResponse
    )
    from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
    from pydantic import BaseModel
    import uvicorn
except ImportError as e:
    print("Missing dependencies. Install with:")
    print("  pip install -r requirements.txt")
    print(f"Error: {e}")
    sys.exit(1)


# ============================================================
# CONFIG / PATHS
# ============================================================

VERSION = "1.0.0"
APP_NAME = "LocalBase"


def get_data_dir(cli_data: Optional[str] = None) -> Path:
    """Resolve data directory. Handles PyInstaller frozen mode."""
    if cli_data:
        p = Path(cli_data).expanduser().resolve()
    elif os.environ.get("LOCALBASE_DATA"):
        p = Path(os.environ["LOCALBASE_DATA"]).expanduser().resolve()
    else:
        # When frozen (PyInstaller), use directory next to executable
        if getattr(sys, "frozen", False):
            base = Path(sys.executable).parent
        else:
            base = Path.cwd()
        p = base / "localbase-data"
    p.mkdir(parents=True, exist_ok=True)
    (p / "projects").mkdir(exist_ok=True)
    (p / "backups").mkdir(exist_ok=True)
    return p


# Global config (set in main)
CONFIG = {
    "data_dir": Path("."),
    "secret": "",
}


def projects_dir() -> Path:
    return CONFIG["data_dir"] / "projects"


def backups_dir() -> Path:
    return CONFIG["data_dir"] / "backups"


def meta_db_path() -> Path:
    return CONFIG["data_dir"] / "localbase-meta.db"


def project_db_path(project_id: str) -> Path:
    return projects_dir() / f"{project_id}.db"


# ============================================================
# META DATABASE (projects, api keys, logs, saved queries)
# ============================================================

def init_meta_db() -> None:
    with sqlite3.connect(meta_db_path()) as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            cors_origins TEXT DEFAULT '*'
        );
        CREATE TABLE IF NOT EXISTS api_keys (
            id TEXT PRIMARY KEY,
            project_id TEXT,
            name TEXT NOT NULL,
            key TEXT NOT NULL UNIQUE,
            role TEXT NOT NULL DEFAULT 'public',
            created_at TEXT NOT NULL,
            revoked INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            method TEXT,
            endpoint TEXT,
            status INTEGER,
            duration_ms REAL,
            project TEXT,
            error TEXT
        );
        CREATE TABLE IF NOT EXISTS saved_queries (
            id TEXT PRIMARY KEY,
            project_id TEXT,
            name TEXT NOT NULL,
            sql TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """)


@contextmanager
def meta_conn():
    conn = sqlite3.connect(meta_db_path())
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


@contextmanager
def project_conn(project_id: str):
    path = project_db_path(project_id)
    if not path.exists():
        raise HTTPException(404, detail=f"Project '{project_id}' not found")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        yield conn
        conn.commit()
    finally:
        conn.close()


def log_request(method: str, endpoint: str, status: int,
                duration_ms: float, project: Optional[str], error: Optional[str]) -> None:
    try:
        with meta_conn() as conn:
            conn.execute(
                "INSERT INTO logs (timestamp, method, endpoint, status, duration_ms, project, error) "
                "VALUES (?,?,?,?,?,?,?)",
                (datetime.now(timezone.utc).isoformat(), method, endpoint,
                 status, duration_ms, project, error)
            )
            # cap log size
            conn.execute(
                "DELETE FROM logs WHERE id NOT IN "
                "(SELECT id FROM logs ORDER BY id DESC LIMIT 5000)"
            )
    except Exception:
        pass


# ============================================================
# VALIDATION
# ============================================================

import re
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


def validate_identifier(name: str, what: str = "identifier") -> str:
    if not name or not _IDENT_RE.match(name):
        raise HTTPException(400, detail=f"Invalid {what}: {name!r}")
    return name


def validate_project_id(pid: str) -> str:
    if not pid or not re.match(r"^[a-z0-9][a-z0-9_-]{0,62}$", pid):
        raise HTTPException(400, detail="Invalid project id (use lowercase letters, digits, - and _)")
    return pid


def quote_ident(name: str) -> str:
    """Safe SQLite identifier quoting."""
    return '"' + name.replace('"', '""') + '"'


# ============================================================
# PROJECT MANAGEMENT
# ============================================================

def project_exists(pid: str) -> bool:
    with meta_conn() as conn:
        row = conn.execute("SELECT 1 FROM projects WHERE id=?", (pid,)).fetchone()
        return row is not None


def create_project(pid: str, name: Optional[str] = None) -> dict:
    validate_project_id(pid)
    if project_exists(pid):
        raise HTTPException(409, detail=f"Project '{pid}' already exists")
    # create actual sqlite file
    db_path = project_db_path(pid)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.close()
    now = datetime.now(timezone.utc).isoformat()
    with meta_conn() as conn:
        conn.execute(
            "INSERT INTO projects (id, name, created_at, cors_origins) VALUES (?,?,?,?)",
            (pid, name or pid, now, "*")
        )
    return {"id": pid, "name": name or pid, "created_at": now, "cors_origins": "*"}


def list_projects() -> list[dict]:
    with meta_conn() as conn:
        rows = conn.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]


def delete_project(pid: str) -> None:
    validate_project_id(pid)
    if not project_exists(pid):
        raise HTTPException(404, detail="Project not found")
    with meta_conn() as conn:
        conn.execute("DELETE FROM projects WHERE id=?", (pid,))
        conn.execute("DELETE FROM api_keys WHERE project_id=?", (pid,))
        conn.execute("DELETE FROM saved_queries WHERE project_id=?", (pid,))
    p = project_db_path(pid)
    if p.exists():
        p.unlink()
    # also wal/shm
    for ext in ("-wal", "-shm"):
        pp = Path(str(p) + ext)
        if pp.exists():
            pp.unlink()


def rename_project(pid: str, new_name: str) -> dict:
    if not project_exists(pid):
        raise HTTPException(404, detail="Project not found")
    with meta_conn() as conn:
        conn.execute("UPDATE projects SET name=? WHERE id=?", (new_name, pid))
    return {"id": pid, "name": new_name}


# ============================================================
# INTROSPECTION
# ============================================================

def list_tables(pid: str) -> list[dict]:
    with project_conn(pid) as conn:
        rows = conn.execute(
            "SELECT name, sql FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        result = []
        for r in rows:
            try:
                count = conn.execute(f"SELECT COUNT(*) FROM {quote_ident(r['name'])}").fetchone()[0]
            except Exception:
                count = 0
            result.append({"name": r["name"], "row_count": count, "sql": r["sql"]})
        return result


def get_table_schema(pid: str, table: str) -> dict:
    validate_identifier(table, "table name")
    with project_conn(pid) as conn:
        info = conn.execute(f"PRAGMA table_info({quote_ident(table)})").fetchall()
        if not info:
            raise HTTPException(404, detail=f"Table '{table}' does not exist")
        columns = [{
            "cid": r["cid"],
            "name": r["name"],
            "type": r["type"],
            "notnull": bool(r["notnull"]),
            "default": r["dflt_value"],
            "pk": bool(r["pk"]),
        } for r in info]

        fks = conn.execute(f"PRAGMA foreign_key_list({quote_ident(table)})").fetchall()
        foreign_keys = [{
            "id": r["id"],
            "from": r["from"],
            "to_table": r["table"],
            "to_column": r["to"],
        } for r in fks]

        idx = conn.execute(f"PRAGMA index_list({quote_ident(table)})").fetchall()
        indexes = []
        for r in idx:
            cols = conn.execute(f"PRAGMA index_info({quote_ident(r['name'])})").fetchall()
            indexes.append({
                "name": r["name"],
                "unique": bool(r["unique"]),
                "columns": [c["name"] for c in cols],
            })

        return {"table": table, "columns": columns,
                "foreign_keys": foreign_keys, "indexes": indexes}


# ============================================================
# ROW OPERATIONS
# ============================================================

def _build_where(filters: dict, columns: list[str]) -> tuple[str, list]:
    """filters: {col: {'op': value}} or {col: value} for eq."""
    ops = {"eq": "=", "neq": "!=", "gt": ">", "gte": ">=",
           "lt": "<", "lte": "<=", "like": "LIKE"}
    clauses = []
    params = []
    for col, spec in filters.items():
        if col not in columns:
            continue
        if isinstance(spec, dict):
            for op, val in spec.items():
                if op == "in":
                    if not isinstance(val, list):
                        continue
                    placeholders = ",".join("?" * len(val))
                    clauses.append(f"{quote_ident(col)} IN ({placeholders})")
                    params.extend(val)
                elif op in ops:
                    clauses.append(f"{quote_ident(col)} {ops[op]} ?")
                    params.append(val)
        else:
            clauses.append(f"{quote_ident(col)} = ?")
            params.append(spec)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def select_rows(pid: str, table: str, filters: dict, sort: Optional[str],
                order: str, limit: int, offset: int) -> dict:
    validate_identifier(table, "table name")
    with project_conn(pid) as conn:
        info = conn.execute(f"PRAGMA table_info({quote_ident(table)})").fetchall()
        if not info:
            raise HTTPException(404, detail=f"Table '{table}' does not exist")
        columns = [r["name"] for r in info]
        where, params = _build_where(filters, columns)
        order_sql = ""
        if sort:
            if sort not in columns:
                raise HTTPException(400, detail=f"Unknown sort column: {sort}")
            direction = "DESC" if (order or "").lower() == "desc" else "ASC"
            order_sql = f" ORDER BY {quote_ident(sort)} {direction}"
        # count
        count = conn.execute(
            f"SELECT COUNT(*) FROM {quote_ident(table)}{where}", params
        ).fetchone()[0]
        # page
        sql = f"SELECT * FROM {quote_ident(table)}{where}{order_sql} LIMIT ? OFFSET ?"
        rows = conn.execute(sql, params + [limit, offset]).fetchall()
        return {"data": [dict(r) for r in rows], "count": count,
                "limit": limit, "offset": offset}


def insert_row(pid: str, table: str, data: dict) -> dict:
    validate_identifier(table, "table name")
    if not isinstance(data, dict) or not data:
        raise HTTPException(400, detail="Request body must be a non-empty JSON object")
    with project_conn(pid) as conn:
        info = conn.execute(f"PRAGMA table_info({quote_ident(table)})").fetchall()
        if not info:
            raise HTTPException(404, detail=f"Table '{table}' does not exist")
        cols = [r["name"] for r in info]
        valid = {k: v for k, v in data.items() if k in cols}
        if not valid:
            raise HTTPException(400, detail="No valid columns provided")
        keys = list(valid.keys())
        placeholders = ",".join("?" * len(keys))
        col_sql = ",".join(quote_ident(k) for k in keys)
        cur = conn.execute(
            f"INSERT INTO {quote_ident(table)} ({col_sql}) VALUES ({placeholders})",
            [valid[k] for k in keys]
        )
        rowid = cur.lastrowid
        # try to fetch by rowid
        row = conn.execute(
            f"SELECT * FROM {quote_ident(table)} WHERE rowid=?", (rowid,)
        ).fetchone()
        return dict(row) if row else {"rowid": rowid}


def update_row(pid: str, table: str, rowid: int, data: dict) -> dict:
    validate_identifier(table, "table name")
    with project_conn(pid) as conn:
        info = conn.execute(f"PRAGMA table_info({quote_ident(table)})").fetchall()
        if not info:
            raise HTTPException(404, detail=f"Table '{table}' does not exist")
        cols = [r["name"] for r in info]
        valid = {k: v for k, v in data.items() if k in cols}
        if not valid:
            raise HTTPException(400, detail="No valid columns provided")
        set_sql = ",".join(f"{quote_ident(k)}=?" for k in valid.keys())
        cur = conn.execute(
            f"UPDATE {quote_ident(table)} SET {set_sql} WHERE rowid=?",
            list(valid.values()) + [rowid]
        )
        if cur.rowcount == 0:
            raise HTTPException(404, detail="Row not found")
        row = conn.execute(
            f"SELECT * FROM {quote_ident(table)} WHERE rowid=?", (rowid,)
        ).fetchone()
        return dict(row) if row else {}


def delete_row(pid: str, table: str, rowid: int) -> None:
    validate_identifier(table, "table name")
    with project_conn(pid) as conn:
        cur = conn.execute(
            f"DELETE FROM {quote_ident(table)} WHERE rowid=?", (rowid,)
        )
        if cur.rowcount == 0:
            raise HTTPException(404, detail="Row not found")


# ============================================================
# SQL EXECUTION
# ============================================================

def execute_sql(pid: str, sql: str) -> dict:
    if not sql or not sql.strip():
        raise HTTPException(400, detail="Empty SQL")
    started = time.time()
    with project_conn(pid) as conn:
        try:
            cur = conn.cursor()
            cur.execute(sql)
            if cur.description:
                cols = [d[0] for d in cur.description]
                rows = [dict(zip(cols, r)) for r in cur.fetchall()]
                return {
                    "type": "select",
                    "columns": cols,
                    "rows": rows,
                    "row_count": len(rows),
                    "duration_ms": (time.time() - started) * 1000,
                }
            else:
                return {
                    "type": "mutation",
                    "row_count": cur.rowcount,
                    "last_row_id": cur.lastrowid,
                    "duration_ms": (time.time() - started) * 1000,
                }
        except sqlite3.Error as e:
            raise HTTPException(400, detail=f"SQL error: {e}")


# ============================================================
# API KEYS
# ============================================================

def create_api_key(project_id: Optional[str], name: str, role: str = "public") -> dict:
    key = f"lb_{role}_{secrets.token_urlsafe(32)}"
    kid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    with meta_conn() as conn:
        conn.execute(
            "INSERT INTO api_keys (id, project_id, name, key, role, created_at, revoked) "
            "VALUES (?,?,?,?,?,?,0)",
            (kid, project_id, name, key, role, now)
        )
    return {"id": kid, "name": name, "key": key, "role": role,
            "project_id": project_id, "created_at": now}


def list_api_keys() -> list[dict]:
    with meta_conn() as conn:
        rows = conn.execute("SELECT * FROM api_keys ORDER BY created_at DESC").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["revoked"] = bool(d["revoked"])
            # mask key
            d["key_masked"] = d["key"][:12] + "..." + d["key"][-4:]
            out.append(d)
        return out


def revoke_api_key(kid: str) -> None:
    with meta_conn() as conn:
        conn.execute("UPDATE api_keys SET revoked=1 WHERE id=?", (kid,))


def delete_api_key(kid: str) -> None:
    with meta_conn() as conn:
        conn.execute("DELETE FROM api_keys WHERE id=?", (kid,))


def verify_api_key(key: str, project_id: Optional[str] = None) -> Optional[dict]:
    if not key:
        return None
    with meta_conn() as conn:
        row = conn.execute(
            "SELECT * FROM api_keys WHERE key=? AND revoked=0", (key,)
        ).fetchone()
        if not row:
            return None
        if row["project_id"] and project_id and row["project_id"] != project_id:
            return None
        return dict(row)


# ============================================================
# BACKUPS
# ============================================================

def create_backup(pid: str) -> dict:
    if not project_exists(pid):
        raise HTTPException(404, detail="Project not found")
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    bname = f"{pid}-{ts}.db"
    src = project_db_path(pid)
    dst = backups_dir() / bname
    # Use SQLite backup API for safety
    src_conn = sqlite3.connect(src)
    dst_conn = sqlite3.connect(dst)
    try:
        src_conn.backup(dst_conn)
    finally:
        src_conn.close()
        dst_conn.close()
    return {"name": bname, "size": dst.stat().st_size}


def list_backups() -> list[dict]:
    out = []
    for p in sorted(backups_dir().glob("*.db"), reverse=True):
        out.append({
            "name": p.name,
            "size": p.stat().st_size,
            "created_at": datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat(),
        })
    return out


def restore_backup(pid: str, name: str) -> None:
    validate_project_id(pid)
    # prevent traversal
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(400, detail="Invalid backup name")
    bpath = backups_dir() / name
    if not bpath.exists():
        raise HTTPException(404, detail="Backup not found")
    target = project_db_path(pid)
    # snapshot current
    if target.exists():
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        shutil.copy2(target, backups_dir() / f"{pid}-pre-restore-{ts}.db")
    shutil.copy2(bpath, target)


def delete_backup(name: str) -> None:
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(400, detail="Invalid backup name")
    bpath = backups_dir() / name
    if bpath.exists():
        bpath.unlink()


# ============================================================
# CSV IMPORT/EXPORT
# ============================================================

def export_table_csv(pid: str, table: str) -> str:
    validate_identifier(table, "table name")
    with project_conn(pid) as conn:
        info = conn.execute(f"PRAGMA table_info({quote_ident(table)})").fetchall()
        if not info:
            raise HTTPException(404, detail="Table not found")
        cols = [r["name"] for r in info]
        rows = conn.execute(f"SELECT * FROM {quote_ident(table)}").fetchall()
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(cols)
        for r in rows:
            writer.writerow([r[c] for c in cols])
        return buf.getvalue()


def import_csv(pid: str, table: str, csv_text: str) -> int:
    validate_identifier(table, "table name")
    reader = csv.reader(io.StringIO(csv_text))
    try:
        header = next(reader)
    except StopIteration:
        raise HTTPException(400, detail="Empty CSV")
    with project_conn(pid) as conn:
        info = conn.execute(f"PRAGMA table_info({quote_ident(table)})").fetchall()
        if not info:
            raise HTTPException(404, detail="Table not found")
        cols = [r["name"] for r in info]
        insert_cols = [c for c in header if c in cols]
        if not insert_cols:
            raise HTTPException(400, detail="No matching columns")
        placeholders = ",".join("?" * len(insert_cols))
        col_sql = ",".join(quote_ident(c) for c in insert_cols)
        count = 0
        for row in reader:
            if len(row) != len(header):
                continue
            data = dict(zip(header, row))
            vals = [data[c] if data[c] != "" else None for c in insert_cols]
            conn.execute(
                f"INSERT INTO {quote_ident(table)} ({col_sql}) VALUES ({placeholders})",
                vals
            )
            count += 1
        return count


# ============================================================
# WEBSOCKET HUB
# ============================================================

class WSHub:
    def __init__(self):
        self.clients: list[WebSocket] = []

    async def connect(self, ws: WebSocket, project_id: Optional[str]):
        await ws.accept()
        ws.state_project = project_id
        self.clients.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.clients:
            self.clients.remove(ws)

    async def broadcast(self, event: dict):
        dead = []
        for ws in self.clients:
            try:
                proj = getattr(ws, "state_project", None)
                if proj and proj != event.get("project"):
                    continue
                await ws.send_json(event)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


HUB = WSHub()


# ============================================================
# FASTAPI APP
# ============================================================

app = FastAPI(title=f"{APP_NAME} API", version=VERSION,
              description="Self-hosted backend API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_middleware(request: Request, call_next):
    started = time.time()
    project = None
    m = re.match(r"^/api/project/([^/]+)", request.url.path)
    if m:
        project = m.group(1)
    try:
        response = await call_next(request)
        status = response.status_code
        err = None
    except Exception as e:
        status = 500
        err = str(e)
        raise
    finally:
        duration = (time.time() - started) * 1000
        if not request.url.path.startswith(("/_static", "/favicon")):
            log_request(request.method, str(request.url.path),
                        status, duration, project, err)
    return response


# ---------- Auth dependency ----------

bearer = HTTPBearer(auto_error=False)


async def optional_auth(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
    x_api_key: Optional[str] = Header(None, alias="x-api-key"),
) -> Optional[dict]:
    key = None
    if creds and creds.credentials:
        key = creds.credentials
    elif x_api_key:
        key = x_api_key
    if not key:
        return None
    return verify_api_key(key)


# ============================================================
# REST API — PROJECT / TABLE
# ============================================================

@app.get("/api/projects")
async def api_list_projects():
    return {"success": True, "data": list_projects()}


@app.post("/api/projects")
async def api_create_project(body: dict):
    pid = body.get("id") or body.get("name")
    if not pid:
        raise HTTPException(400, detail="Missing project id")
    proj = create_project(pid, body.get("name"))
    return {"success": True, "data": proj}


@app.delete("/api/projects/{pid}")
async def api_delete_project(pid: str):
    delete_project(pid)
    return {"success": True}


@app.patch("/api/projects/{pid}")
async def api_rename_project(pid: str, body: dict):
    name = body.get("name")
    if not name:
        raise HTTPException(400, detail="Missing name")
    return {"success": True, "data": rename_project(pid, name)}


@app.get("/api/project/{pid}/tables")
async def api_list_tables(pid: str):
    if not project_exists(pid):
        raise HTTPException(404, detail="Project not found")
    return {"success": True, "data": list_tables(pid)}


@app.get("/api/project/{pid}/table/{table}/schema")
async def api_table_schema(pid: str, table: str):
    if not project_exists(pid):
        raise HTTPException(404, detail="Project not found")
    return {"success": True, "data": get_table_schema(pid, table)}


def _parse_filters(query_params) -> dict:
    filters: dict = {}
    for k, v in query_params.items():
        m = re.match(r"^filter\[([^\]]+)\]\[([^\]]+)\]$", k)
        if m:
            col, op = m.group(1), m.group(2)
            if op == "in":
                filters.setdefault(col, {})[op] = v.split(",")
            else:
                filters.setdefault(col, {})[op] = v
        elif k not in ("limit", "offset", "sort", "order") and not k.startswith("filter"):
            # simple col=value shorthand
            filters.setdefault(k, v)
    return filters


@app.get("/api/project/{pid}/table/{table}")
async def api_select(pid: str, table: str, request: Request,
                     limit: int = 50, offset: int = 0,
                     sort: Optional[str] = None, order: str = "asc",
                     auth: Optional[dict] = Depends(optional_auth)):
    if not project_exists(pid):
        raise HTTPException(404, detail="Project not found")
    limit = max(1, min(limit, 1000))
    filters = _parse_filters(request.query_params)
    try:
        result = select_rows(pid, table, filters, sort, order, limit, offset)
    except HTTPException as e:
        return JSONResponse(
            status_code=e.status_code,
            content={"success": False, "error": {
                "code": "TABLE_NOT_FOUND" if e.status_code == 404 else "BAD_REQUEST",
                "message": e.detail,
            }}
        )
    return {"success": True, **result}


@app.post("/api/project/{pid}/table/{table}")
async def api_insert(pid: str, table: str, request: Request,
                     auth: Optional[dict] = Depends(optional_auth)):
    if not project_exists(pid):
        raise HTTPException(404, detail="Project not found")
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, detail="Invalid JSON body")
    # accept array or single
    if isinstance(data, list):
        rows = [insert_row(pid, table, d) for d in data]
        for r in rows:
            await HUB.broadcast({"type": "insert", "project": pid,
                                 "table": table, "record": r})
        return {"success": True, "data": rows, "count": len(rows)}
    row = insert_row(pid, table, data)
    await HUB.broadcast({"type": "insert", "project": pid,
                         "table": table, "record": row})
    return {"success": True, "data": row}


@app.patch("/api/project/{pid}/table/{table}/{rowid}")
async def api_update(pid: str, table: str, rowid: int, request: Request,
                     auth: Optional[dict] = Depends(optional_auth)):
    if not project_exists(pid):
        raise HTTPException(404, detail="Project not found")
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, detail="Invalid JSON body")
    row = update_row(pid, table, rowid, data)
    await HUB.broadcast({"type": "update", "project": pid,
                         "table": table, "record": row})
    return {"success": True, "data": row}


@app.delete("/api/project/{pid}/table/{table}/{rowid}")
async def api_delete(pid: str, table: str, rowid: int,
                     auth: Optional[dict] = Depends(optional_auth)):
    if not project_exists(pid):
        raise HTTPException(404, detail="Project not found")
    delete_row(pid, table, rowid)
    await HUB.broadcast({"type": "delete", "project": pid,
                         "table": table, "rowid": rowid})
    return {"success": True}


# ---------- SQL ----------

@app.post("/api/project/{pid}/sql")
async def api_sql(pid: str, body: dict):
    if not project_exists(pid):
        raise HTTPException(404, detail="Project not found")
    sql = body.get("sql", "")
    result = execute_sql(pid, sql)
    return {"success": True, "data": result}


# ---------- Table management (DDL) ----------

@app.post("/api/project/{pid}/table/{table}/create")
async def api_create_table(pid: str, table: str, body: dict):
    validate_identifier(table, "table name")
    columns = body.get("columns")
    if not columns:
        raise HTTPException(400, detail="No columns provided")
    parts = []
    for c in columns:
        name = validate_identifier(c["name"], "column name")
        ctype = c.get("type", "TEXT").upper()
        if ctype not in ("TEXT", "INTEGER", "REAL", "BLOB", "NUMERIC", "BOOLEAN",
                         "DATE", "DATETIME", "JSON"):
            raise HTTPException(400, detail=f"Invalid type: {ctype}")
        p = f"{quote_ident(name)} {ctype}"
        if c.get("primary_key"):
            p += " PRIMARY KEY"
            if c.get("auto_increment") and ctype == "INTEGER":
                p += " AUTOINCREMENT"
        if not c.get("nullable", True) and not c.get("primary_key"):
            p += " NOT NULL"
        if c.get("unique"):
            p += " UNIQUE"
        if c.get("default") is not None:
            p += f" DEFAULT {c['default']}"
        parts.append(p)
    sql = f"CREATE TABLE {quote_ident(table)} ({', '.join(parts)})"
    with project_conn(pid) as conn:
        try:
            conn.execute(sql)
        except sqlite3.Error as e:
            raise HTTPException(400, detail=f"SQL error: {e}")
    return {"success": True, "sql": sql}


@app.post("/api/project/{pid}/table/{table}/drop")
async def api_drop_table(pid: str, table: str):
    validate_identifier(table, "table name")
    with project_conn(pid) as conn:
        conn.execute(f"DROP TABLE {quote_ident(table)}")
    return {"success": True}


@app.post("/api/project/{pid}/table/{table}/rename")
async def api_rename_table(pid: str, table: str, body: dict):
    new_name = validate_identifier(body.get("new_name", ""), "new table name")
    validate_identifier(table, "table name")
    with project_conn(pid) as conn:
        conn.execute(f"ALTER TABLE {quote_ident(table)} RENAME TO {quote_ident(new_name)}")
    return {"success": True}


@app.post("/api/project/{pid}/table/{table}/add_column")
async def api_add_column(pid: str, table: str, body: dict):
    validate_identifier(table, "table name")
    name = validate_identifier(body.get("name", ""), "column name")
    ctype = body.get("type", "TEXT").upper()
    parts = [f"ALTER TABLE {quote_ident(table)} ADD COLUMN {quote_ident(name)} {ctype}"]
    if not body.get("nullable", True):
        # SQLite requires default for NOT NULL on ADD COLUMN
        if body.get("default") is None:
            raise HTTPException(400, detail="NOT NULL column needs a default value")
        parts.append("NOT NULL")
    if body.get("default") is not None:
        parts.append(f"DEFAULT {body['default']}")
    with project_conn(pid) as conn:
        conn.execute(" ".join(parts))
    return {"success": True}


@app.post("/api/project/{pid}/table/{table}/drop_column")
async def api_drop_column(pid: str, table: str, body: dict):
    validate_identifier(table, "table name")
    name = validate_identifier(body.get("name", ""), "column name")
    with project_conn(pid) as conn:
        # SQLite 3.35+ supports DROP COLUMN
        try:
            conn.execute(f"ALTER TABLE {quote_ident(table)} DROP COLUMN {quote_ident(name)}")
        except sqlite3.Error as e:
            raise HTTPException(400, detail=f"Cannot drop column: {e}")
    return {"success": True}


# ---------- API keys ----------

@app.get("/api/api-keys")
async def api_list_keys():
    return {"success": True, "data": list_api_keys()}


@app.post("/api/api-keys")
async def api_create_key(body: dict):
    name = body.get("name", "Untitled")
    role = body.get("role", "public")
    project_id = body.get("project_id")
    if role not in ("public", "server"):
        raise HTTPException(400, detail="role must be 'public' or 'server'")
    return {"success": True, "data": create_api_key(project_id, name, role)}


@app.post("/api/api-keys/{kid}/revoke")
async def api_revoke_key(kid: str):
    revoke_api_key(kid)
    return {"success": True}


@app.delete("/api/api-keys/{kid}")
async def api_delete_key(kid: str):
    delete_api_key(kid)
    return {"success": True}


# ---------- Logs ----------

@app.get("/api/logs")
async def api_logs(limit: int = 200, project: Optional[str] = None):
    with meta_conn() as conn:
        if project:
            rows = conn.execute(
                "SELECT * FROM logs WHERE project=? ORDER BY id DESC LIMIT ?",
                (project, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM logs ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return {"success": True, "data": [dict(r) for r in rows]}


@app.delete("/api/logs")
async def api_clear_logs():
    with meta_conn() as conn:
        conn.execute("DELETE FROM logs")
    return {"success": True}


# ---------- Backups ----------

@app.get("/api/backups")
async def api_list_backups():
    return {"success": True, "data": list_backups()}


@app.post("/api/project/{pid}/backup")
async def api_create_backup(pid: str):
    return {"success": True, "data": create_backup(pid)}


@app.post("/api/project/{pid}/restore")
async def api_restore(pid: str, body: dict):
    restore_backup(pid, body.get("name", ""))
    return {"success": True}


@app.delete("/api/backups/{name}")
async def api_delete_backup(name: str):
    delete_backup(name)
    return {"success": True}


@app.get("/api/backups/{name}/download")
async def api_download_backup(name: str):
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(400, detail="Invalid name")
    p = backups_dir() / name
    if not p.exists():
        raise HTTPException(404, detail="Not found")
    return FileResponse(p, filename=name)


# ---------- Export / Import ----------

@app.get("/api/project/{pid}/table/{table}/export.csv")
async def api_export_csv(pid: str, table: str):
    text = export_table_csv(pid, table)
    return PlainTextResponse(
        text, media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{table}.csv"'}
    )


@app.get("/api/project/{pid}/table/{table}/export.json")
async def api_export_json(pid: str, table: str, limit: int = 100000, offset: int = 0):
    result = select_rows(pid, table, {}, None, "asc", limit, offset)
    return JSONResponse(
        result["data"],
        headers={"Content-Disposition": f'attachment; filename="{table}.json"'}
    )


@app.post("/api/project/{pid}/table/{table}/import.csv")
async def api_import_csv(pid: str, table: str, file: UploadFile = File(...)):
    content = (await file.read()).decode("utf-8")
    n = import_csv(pid, table, content)
    return {"success": True, "imported": n}


# ---------- System ----------

@app.get("/api/health")
async def api_health():
    return {"success": True, "status": "ok", "version": VERSION}


@app.get("/api/info")
async def api_info(request: Request):
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("host", f"localhost:8000")
    return {
        "success": True,
        "data": {
            "version": VERSION,
            "base_url": f"{scheme}://{host}",
            "api_url": f"{scheme}://{host}/api",
            "data_dir": str(CONFIG["data_dir"]),
        }
    }


# ---------- Saved Queries ----------

@app.get("/api/project/{pid}/saved-queries")
async def api_list_saved(pid: str):
    with meta_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM saved_queries WHERE project_id=? ORDER BY created_at DESC",
            (pid,)
        ).fetchall()
    return {"success": True, "data": [dict(r) for r in rows]}


@app.post("/api/project/{pid}/saved-queries")
async def api_save_query(pid: str, body: dict):
    qid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    with meta_conn() as conn:
        conn.execute(
            "INSERT INTO saved_queries (id, project_id, name, sql, created_at) VALUES (?,?,?,?,?)",
            (qid, pid, body.get("name", "Query"), body.get("sql", ""), now)
        )
    return {"success": True, "data": {"id": qid}}


@app.delete("/api/saved-queries/{qid}")
async def api_delete_saved(qid: str):
    with meta_conn() as conn:
        conn.execute("DELETE FROM saved_queries WHERE id=?", (qid,))
    return {"success": True}


# ============================================================
# WEBSOCKET
# ============================================================

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket, project: Optional[str] = Query(None)):
    await HUB.connect(ws, project)
    try:
        while True:
            # keepalive
            await ws.receive_text()
    except WebSocketDisconnect:
        HUB.disconnect(ws)
    except Exception:
        HUB.disconnect(ws)


# ============================================================
# DASHBOARD (embedded HTML)
# ============================================================

INDEX_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LocalBase</title>
<style>
:root {
  --bg: #0d1117; --bg2: #161b22; --bg3: #21262d;
  --fg: #e6edf3; --fg2: #8b949e; --border: #30363d;
  --accent: #3fb950; --accent2: #58a6ff; --danger: #f85149; --warn: #d29922;
  --radius: 8px;
}
[data-theme="light"] {
  --bg: #ffffff; --bg2: #f6f8fa; --bg3: #eaeef2;
  --fg: #1f2328; --fg2: #656d76; --border: #d0d7de;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
  background: var(--bg); color: var(--fg); font-size: 14px; line-height: 1.5;
  overflow: hidden; height: 100vh;
}
button { cursor: pointer; font-family: inherit; }
input, textarea, select {
  font-family: inherit; font-size: 13px;
  background: var(--bg); color: var(--fg);
  border: 1px solid var(--border); border-radius: 6px;
  padding: 6px 10px; outline: none;
}
input:focus, textarea:focus, select:focus { border-color: var(--accent2); }
.btn {
  background: var(--bg3); color: var(--fg); border: 1px solid var(--border);
  border-radius: 6px; padding: 6px 12px; font-size: 13px; font-weight: 500;
  transition: all .12s;
}
.btn:hover { background: var(--bg2); border-color: var(--fg2); }
.btn.primary { background: var(--accent); color: #fff; border-color: var(--accent); }
.btn.primary:hover { filter: brightness(1.1); }
.btn.danger { background: var(--danger); color: #fff; border-color: var(--danger); }
.btn.ghost { background: transparent; border-color: transparent; }
.btn.ghost:hover { background: var(--bg3); }
.btn.sm { padding: 3px 8px; font-size: 12px; }
.layout { display: flex; height: 100vh; }
.sidebar {
  width: 240px; background: var(--bg2); border-right: 1px solid var(--border);
  display: flex; flex-direction: column; overflow-y: auto; flex-shrink: 0;
}
.brand {
  padding: 16px; font-weight: 700; font-size: 16px; border-bottom: 1px solid var(--border);
  display: flex; align-items: center; gap: 8px;
}
.brand-logo {
  width: 24px; height: 24px; border-radius: 6px;
  background: linear-gradient(135deg, var(--accent), var(--accent2));
  display: flex; align-items: center; justify-content: center;
  color: #fff; font-size: 12px; font-weight: 800;
}
.nav { padding: 8px; flex: 1; }
.nav-item {
  display: flex; align-items: center; gap: 10px;
  padding: 8px 12px; border-radius: 6px; color: var(--fg2);
  cursor: pointer; font-size: 13px; user-select: none;
}
.nav-item:hover { background: var(--bg3); color: var(--fg); }
.nav-item.active { background: var(--bg3); color: var(--fg); font-weight: 600; }
.nav-item .icon { width: 16px; text-align: center; }
.nav-section {
  padding: 12px 12px 4px; font-size: 11px; text-transform: uppercase;
  color: var(--fg2); letter-spacing: .5px; font-weight: 600;
}
.project-list { padding: 0 8px 8px; }
.project-item {
  padding: 6px 12px; border-radius: 6px; cursor: pointer; font-size: 13px;
  color: var(--fg2); display: flex; align-items: center; justify-content: space-between;
}
.project-item:hover { background: var(--bg3); color: var(--fg); }
.project-item.active { background: var(--bg3); color: var(--fg); }
.main { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
.header {
  padding: 12px 24px; border-bottom: 1px solid var(--border);
  display: flex; align-items: center; justify-content: space-between;
  background: var(--bg2); flex-shrink: 0;
}
.header h1 { font-size: 16px; font-weight: 600; }
.header-actions { display: flex; gap: 8px; align-items: center; }
.content { flex: 1; overflow-y: auto; padding: 24px; }
.card {
  background: var(--bg2); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 20px; margin-bottom: 16px;
}
.card h3 { font-size: 14px; font-weight: 600; margin-bottom: 12px; }
.grid { display: grid; gap: 16px; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); }
.stat { padding: 16px; }
.stat .label { color: var(--fg2); font-size: 12px; text-transform: uppercase; letter-spacing: .5px; }
.stat .value { font-size: 28px; font-weight: 700; margin-top: 4px; }
table {
  width: 100%; border-collapse: collapse; font-size: 13px;
}
th, td {
  text-align: left; padding: 8px 12px; border-bottom: 1px solid var(--border);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 320px;
}
th { background: var(--bg3); font-weight: 600; font-size: 12px; position: sticky; top: 0; }
tr:hover td { background: var(--bg3); }
.tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--border); margin-bottom: 16px; }
.tab {
  padding: 8px 16px; cursor: pointer; font-size: 13px; color: var(--fg2);
  border-bottom: 2px solid transparent; margin-bottom: -1px;
}
.tab:hover { color: var(--fg); }
.tab.active { color: var(--fg); border-bottom-color: var(--accent2); font-weight: 600; }
.modal-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,.5);
  display: flex; align-items: center; justify-content: center; z-index: 100;
}
.modal {
  background: var(--bg2); border: 1px solid var(--border); border-radius: var(--radius);
  padding: 24px; min-width: 400px; max-width: 90vw; max-height: 90vh; overflow-y: auto;
}
.modal h2 { font-size: 16px; margin-bottom: 16px; }
.form-group { margin-bottom: 12px; }
.form-group label { display: block; font-size: 12px; color: var(--fg2); margin-bottom: 4px; }
.form-group input, .form-group select, .form-group textarea { width: 100%; }
.modal-actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 20px; }
.toast-container {
  position: fixed; bottom: 24px; right: 24px; z-index: 200;
  display: flex; flex-direction: column; gap: 8px;
}
.toast {
  padding: 12px 16px; border-radius: 6px; background: var(--bg3);
  border-left: 3px solid var(--accent2); min-width: 240px; font-size: 13px;
  animation: slideIn .2s ease;
  box-shadow: 0 4px 12px rgba(0,0,0,.3);
}
.toast.error { border-left-color: var(--danger); }
.toast.success { border-left-color: var(--accent); }
@keyframes slideIn { from { transform: translateX(100%); opacity: 0; } to { transform: translateX(0); opacity: 1; } }
.sql-editor {
  width: 100%; min-height: 180px; font-family: "SF Mono", Monaco, Menlo, Consolas, monospace;
  font-size: 13px; background: var(--bg); color: var(--fg);
  border: 1px solid var(--border); border-radius: 6px; padding: 12px;
  resize: vertical; line-height: 1.5;
}
.code-block {
  background: var(--bg); border: 1px solid var(--border); border-radius: 6px;
  padding: 12px; font-family: "SF Mono", Monaco, Menlo, Consolas, monospace;
  font-size: 12px; overflow-x: auto; white-space: pre; position: relative;
  margin-bottom: 12px;
}
.copy-btn {
  position: absolute; top: 8px; right: 8px;
  background: var(--bg3); border: 1px solid var(--border);
  border-radius: 4px; padding: 2px 8px; font-size: 11px; color: var(--fg2);
}
.copy-btn:hover { color: var(--fg); }
.empty { text-align: center; padding: 48px 24px; color: var(--fg2); }
.empty h2 { color: var(--fg); margin-bottom: 8px; font-size: 18px; }
.spinner {
  display: inline-block; width: 14px; height: 14px;
  border: 2px solid var(--border); border-top-color: var(--accent2);
  border-radius: 50%; animation: spin .6s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
.pill {
  display: inline-block; padding: 2px 8px; border-radius: 10px;
  font-size: 11px; background: var(--bg3); color: var(--fg2);
}
.pill.green { background: rgba(63,185,80,.2); color: var(--accent); }
.pill.blue { background: rgba(88,166,255,.2); color: var(--accent2); }
.pill.red { background: rgba(248,81,73,.2); color: var(--danger); }
.toolbar { display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; align-items: center; }
.row-actions { opacity: 0; transition: opacity .1s; }
tr:hover .row-actions { opacity: 1; }
.column-row { display: flex; gap: 8px; margin-bottom: 8px; align-items: center; }
.column-row input, .column-row select { padding: 4px 8px; font-size: 12px; }
.checkbox-wrap { display: flex; align-items: center; gap: 4px; font-size: 12px; white-space: nowrap; }
@media (max-width: 768px) {
  .sidebar { position: absolute; z-index: 50; height: 100vh; transform: translateX(-100%); transition: transform .2s; }
  .sidebar.open { transform: translateX(0); }
  .content { padding: 16px; }
  .grid { grid-template-columns: 1fr; }
}
</style>
</head>
<body data-theme="dark">
<div class="layout">
  <aside class="sidebar" id="sidebar">
    <div class="brand">
      <div class="brand-logo">LB</div>
      <div>LocalBase</div>
    </div>
    <nav class="nav" id="nav">
      <div class="nav-item" data-page="overview"><span class="icon">◉</span> Overview</div>
      <div class="nav-item" data-page="database"><span class="icon">▤</span> Database</div>
      <div class="nav-item" data-page="sql"><span class="icon">⌨</span> SQL Editor</div>
      <div class="nav-item" data-page="api"><span class="icon">⇄</span> API</div>
      <div class="nav-item" data-page="keys"><span class="icon">🔑</span> API Keys</div>
      <div class="nav-item" data-page="logs"><span class="icon">≡</span> Logs</div>
      <div class="nav-item" data-page="backups"><span class="icon">⛁</span> Backups</div>
      <div class="nav-item" data-page="settings"><span class="icon">⚙</span> Settings</div>
    </nav>
    <div class="nav-section">Projects</div>
    <div class="project-list" id="projectList"></div>
    <div style="padding:8px">
      <button class="btn sm" style="width:100%" onclick="newProjectModal()">+ New Project</button>
    </div>
  </aside>
  <div class="main">
    <header class="header">
      <div style="display:flex;align-items:center;gap:12px">
        <button class="btn ghost" id="menuBtn" style="display:none" onclick="toggleSidebar()">☰</button>
        <h1 id="pageTitle">Overview</h1>
      </div>
      <div class="header-actions">
        <span class="pill" id="currentProjectPill">no project</span>
        <button class="btn sm" onclick="toggleTheme()">◐</button>
      </div>
    </header>
    <main class="content" id="content"></main>
  </div>
</div>
<div class="toast-container" id="toasts"></div>
<div id="modalRoot"></div>

<script>
// ============================================================
// STATE
// ============================================================
const state = {
  project: null,
  page: 'overview',
  table: null,
  tableTab: 'data',
  projects: [],
  theme: 'dark',
  ws: null,
};

const API = '/api';

// ============================================================
// UTILS
// ============================================================
function $(sel, root=document) { return root.querySelector(sel); }
function $$(sel, root=document) { return Array.from(root.querySelectorAll(sel)); }
function esc(s) {
  if (s === null || s === undefined) return '';
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function toast(msg, kind='info') {
  const el = document.createElement('div');
  el.className = 'toast ' + kind;
  el.textContent = msg;
  $('#toasts').appendChild(el);
  setTimeout(() => el.remove(), 4000);
}
async function api(path, opts={}) {
  const res = await fetch(API + path, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  });
  const ct = res.headers.get('content-type') || '';
  let data;
  if (ct.includes('json')) data = await res.json();
  else data = await res.text();
  if (!res.ok) {
    const msg = (data && data.detail) || (data && data.error && data.error.message) || 'Request failed';
    throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
  }
  return data;
}
function toggleTheme() {
  state.theme = state.theme === 'dark' ? 'light' : 'dark';
  document.body.dataset.theme = state.theme;
  localStorage.setItem('lb-theme', state.theme);
}
function toggleSidebar() { $('#sidebar').classList.toggle('open'); }
function copyText(text, label='Copied') {
  navigator.clipboard.writeText(text).then(() => toast(label, 'success'));
}
function confirmModal(title, msg, onOk) {
  showModal(`<h2>${esc(title)}</h2><p style="color:var(--fg2);margin-bottom:16px">${esc(msg)}</p>
    <div class="modal-actions">
      <button class="btn" onclick="closeModal()">Cancel</button>
      <button class="btn danger" id="confirmOk">Confirm</button>
    </div>`);
  $('#confirmOk').onclick = () => { closeModal(); onOk(); };
}
function showModal(html) {
  $('#modalRoot').innerHTML = `<div class="modal-overlay" onclick="if(event.target===this)closeModal()">
    <div class="modal">${html}</div></div>`;
}
function closeModal() { $('#modalRoot').innerHTML = ''; }

// ============================================================
// NAVIGATION
// ============================================================
$$('#nav .nav-item').forEach(el => {
  el.onclick = () => { state.page = el.dataset.page; state.table = null; render(); };
});
function setActiveNav() {
  $$('#nav .nav-item').forEach(el => {
    el.classList.toggle('active', el.dataset.page === state.page);
  });
}

async function loadProjects() {
  try {
    const res = await api('/projects');
    state.projects = res.data || [];
    renderProjectList();
  } catch (e) { console.error(e); }
}
function renderProjectList() {
  const el = $('#projectList');
  el.innerHTML = state.projects.map(p =>
    `<div class="project-item ${state.project===p.id?'active':''}" onclick="selectProject('${p.id}')">
      <span>◈ ${esc(p.name)}</span>
      <span class="row-actions" onclick="event.stopPropagation();deleteProjectConfirm('${p.id}','${esc(p.name)}')" style="color:var(--fg2)">×</span>
    </div>`
  ).join('') || '<div style="padding:8px 12px;color:var(--fg2);font-size:12px">No projects yet</div>';
  $('#currentProjectPill').textContent = state.project || 'no project';
}
function selectProject(pid) {
  state.project = pid;
  state.page = 'database';
  state.table = null;
  renderProjectList();
  render();
}

// ============================================================
// RENDER
// ============================================================
async function render() {
  setActiveNav();
  const content = $('#content');
  $('#pageTitle').textContent = {
    overview: 'Overview', database: 'Database', sql: 'SQL Editor',
    api: 'API', keys: 'API Keys', logs: 'Logs', backups: 'Backups', settings: 'Settings'
  }[state.page] || 'LocalBase';

  if (state.page === 'overview') return renderOverview(content);
  if (state.page === 'database') return renderDatabase(content);
  if (state.page === 'sql') return renderSQL(content);
  if (state.page === 'api') return renderAPI(content);
  if (state.page === 'keys') return renderKeys(content);
  if (state.page === 'logs') return renderLogs(content);
  if (state.page === 'backups') return renderBackups(content);
  if (state.page === 'settings') return renderSettings(content);
}

async function renderOverview(content) {
  if (!state.project) {
    content.innerHTML = `<div class="empty"><h2>Welcome to LocalBase</h2>
      <p>Your self-hosted backend. Create a project to get started.</p>
      <button class="btn primary" style="margin-top:16px" onclick="newProjectModal()">Create Project</button></div>`;
    return;
  }
  content.innerHTML = '<div class="spinner"></div>';
  try {
    const [tables, info] = await Promise.all([
      api(`/project/${state.project}/tables`),
      api('/info'),
    ]);
    const totalRows = (tables.data||[]).reduce((a,t)=>a+t.row_count,0);
    content.innerHTML = `
      <div class="grid">
        <div class="card stat"><div class="label">Tables</div><div class="value">${(tables.data||[]).length}</div></div>
        <div class="card stat"><div class="label">Total Rows</div><div class="value">${totalRows}</div></div>
        <div class="card stat"><div class="label">Project</div><div class="value" style="font-size:18px">${esc(state.project)}</div></div>
        <div class="card stat"><div class="label">Version</div><div class="value" style="font-size:18px">${esc(info.data.version)}</div></div>
      </div>
      <div class="card">
        <h3>API URL</h3>
        <div class="code-block">${esc(info.data.api_url)}<button class="copy-btn" onclick="copyText('${esc(info.data.api_url)}','API URL copied')">Copy</button></div>
      </div>
      <div class="card">
        <h3>Tables</h3>
        ${(tables.data||[]).length === 0 ? '<p style="color:var(--fg2)">No tables yet. Go to Database to create one.</p>' :
        '<table><thead><tr><th>Name</th><th>Rows</th><th></th></tr></thead><tbody>' +
        tables.data.map(t => `<tr><td>${esc(t.name)}</td><td>${t.row_count}</td>
          <td><button class="btn sm" onclick="state.page='database';state.table='${esc(t.name)}';render()">Open</button></td></tr>`).join('') +
        '</tbody></table>'}
      </div>`;
  } catch (e) {
    content.innerHTML = `<div class="empty"><p style="color:var(--danger)">${esc(e.message)}</p></div>`;
  }
}

async function renderDatabase(content) {
  if (!state.project) {
    content.innerHTML = `<div class="empty"><h2>No project selected</h2>
      <p>Select or create a project from the sidebar.</p></div>`;
    return;
  }
  if (state.table) return renderTable(content);
  content.innerHTML = '<div class="spinner"></div>';
  try {
    const res = await api(`/project/${state.project}/tables`);
    const tables = res.data || [];
    content.innerHTML = `
      <div class="toolbar">
        <button class="btn primary" onclick="createTableModal()">+ New Table</button>
        <button class="btn" onclick="render()">↻ Refresh</button>
        <input id="tableSearch" placeholder="Search tables..." style="margin-left:auto;width:220px" oninput="filterTableList()">
      </div>
      <div class="card">
        ${tables.length === 0 ?
          '<div class="empty"><p>No tables yet.</p><button class="btn primary" onclick="createTableModal()">Create your first table</button></div>' :
          `<table id="tableListTable"><thead><tr><th>Name</th><th>Rows</th><th>Actions</th></tr></thead><tbody>
          ${tables.map(t => `<tr data-name="${esc(t.name)}">
            <td><a href="#" onclick="event.preventDefault();openTable('${esc(t.name)}')" style="color:var(--accent2);text-decoration:none">${esc(t.name)}</a></td>
            <td>${t.row_count}</td>
            <td>
              <button class="btn sm" onclick="openTable('${esc(t.name)}')">Open</button>
              <button class="btn sm" onclick="renameTableModal('${esc(t.name)}')">Rename</button>
              <button class="btn sm danger" onclick="dropTableConfirm('${esc(t.name)}')">Drop</button>
            </td></tr>`).join('')}
          </tbody></table>`}
      </div>`;
  } catch (e) {
    content.innerHTML = `<div class="empty"><p style="color:var(--danger)">${esc(e.message)}</p></div>`;
  }
}
function filterTableList() {
  const q = $('#tableSearch').value.toLowerCase();
  $$('#tableListTable tbody tr').forEach(tr => {
    tr.style.display = tr.dataset.name.toLowerCase().includes(q) ? '' : 'none';
  });
}
function openTable(name) { state.table = name; state.tableTab = 'data'; render(); }

// ============================================================
// TABLE VIEW
// ============================================================
async function renderTable(content) {
  content.innerHTML = `
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:16px">
      <button class="btn sm" onclick="state.table=null;render()">← Back</button>
      <h2 style="font-size:16px">${esc(state.table)}</h2>
    </div>
    <div class="tabs">
      <div class="tab ${state.tableTab==='data'?'active':''}" onclick="state.tableTab='data';render()">Data</div>
      <div class="tab ${state.tableTab==='structure'?'active':''}" onclick="state.tableTab='structure';render()">Structure</div>
      <div class="tab ${state.tableTab==='indexes'?'active':''}" onclick="state.tableTab='indexes';render()">Indexes</div>
      <div class="tab ${state.tableTab==='api'?'active':''}" onclick="state.tableTab='api';render()">API</div>
    </div>
    <div id="tablePanel"><div class="spinner"></div></div>`;
  if (state.tableTab === 'data') await renderTableData();
  else if (state.tableTab === 'structure') await renderTableStructure();
  else if (state.tableTab === 'indexes') await renderTableIndexes();
  else if (state.tableTab === 'api') await renderTableAPI();
}

async function renderTableData() {
  const panel = $('#tablePanel');
  try {
    const [schema, dataRes] = await Promise.all([
      api(`/project/${state.project}/table/${state.table}/schema`),
      api(`/project/${state.project}/table/${state.table}?limit=50`),
    ]);
    const cols = schema.data.columns;
    const rows = dataRes.data || [];
    panel.innerHTML = `
      <div class="toolbar">
        <button class="btn primary sm" onclick="insertRowModal()">+ Add Row</button>
        <button class="btn sm" onclick="renderTableData()">↻ Refresh</button>
        <a class="btn sm" href="${API}/project/${state.project}/table/${state.table}/export.csv" download>Export CSV</a>
        <a class="btn sm" href="${API}/project/${state.project}/table/${state.table}/export.json" download>Export JSON</a>
        <span style="margin-left:auto;color:var(--fg2);font-size:12px">${dataRes.count} rows (showing ${rows.length})</span>
      </div>
      <div class="card" style="padding:0;overflow:auto;max-height:70vh">
        <table><thead><tr>
          ${cols.map(c => `<th>${esc(c.name)} <span class="pill">${esc(c.type||'ANY')}</span></th>`).join('')}
          <th></th>
        </tr></thead><tbody>
          ${rows.map(r => `<tr>
            ${cols.map(c => `<td contenteditable="true"
              data-rowid="${r.rowid ?? r[c.name]}"
              data-col="${esc(c.name)}"
              onblur="cellEdit(this)">${r[c.name] === null ? '<span style="color:var(--fg2)">NULL</span>' : esc(r[c.name])}</td>`).join('')}
            <td><button class="btn sm danger" onclick="deleteRow('${r.rowid ?? r[cols[0].name]}')">×</button></td>
          </tr>`).join('') || `<tr><td colspan="${cols.length+1}" class="empty">No rows</td></tr>`}
        </tbody></table>
      </div>`;
  } catch (e) {
    panel.innerHTML = `<div class="empty"><p style="color:var(--danger)">${esc(e.message)}</p></div>`;
  }
}

async function cellEdit(td) {
  const rowid = td.dataset.rowid;
  const col = td.dataset.col;
  const val = td.textContent.trim();
  const old = td.dataset.old !== undefined ? td.dataset.old : null;
  try {
    await api(`/project/${state.project}/table/${state.table}/${rowid}`, {
      method: 'PATCH', body: JSON.stringify({ [col]: val === 'NULL' ? null : val })
    });
    toast('Cell updated', 'success');
  } catch (e) { toast(e.message, 'error'); }
}

function insertRowModal() {
  api(`/project/${state.project}/table/${state.table}/schema`).then(schema => {
    const cols = schema.data.columns.filter(c => !c.pk);
    showModal(`<h2>Insert Row into ${esc(state.table)}</h2>
      <div id="insertForm">${cols.map(c => `
        <div class="form-group"><label>${esc(c.name)} <span style="color:var(--fg2)">${esc(c.type)}</span></label>
        <input data-col="${esc(c.name)}" placeholder="${c.notnull?'required':'optional'}"></div>`).join('')}</div>
      <div class="modal-actions">
        <button class="btn" onclick="closeModal()">Cancel</button>
        <button class="btn primary" onclick="doInsert()">Insert</button>
      </div>`);
  });
}
async function doInsert() {
  const data = {};
  $$('#insertForm input').forEach(inp => {
    const v = inp.value;
    if (v !== '') data[inp.dataset.col] = v;
  });
  try {
    await api(`/project/${state.project}/table/${state.table}`, {
      method: 'POST', body: JSON.stringify(data)
    });
    closeModal(); toast('Row inserted', 'success'); renderTableData();
  } catch (e) { toast(e.message, 'error'); }
}
function deleteRow(rowid) {
  confirmModal('Delete row?', 'This cannot be undone.', async () => {
    try {
      await api(`/project/${state.project}/table/${state.table}/${rowid}`, { method: 'DELETE' });
      toast('Row deleted', 'success'); renderTableData();
    } catch (e) { toast(e.message, 'error'); }
  });
}

// ============================================================
// STRUCTURE
// ============================================================
async function renderTableStructure() {
  const panel = $('#tablePanel');
  try {
    const schema = await api(`/project/${state.project}/table/${state.table}/schema`);
    const cols = schema.data.columns;
    panel.innerHTML = `
      <div class="card">
        <div style="display:flex;justify-content:space-between;margin-bottom:12px">
          <h3>Columns</h3>
          <button class="btn sm primary" onclick="addColumnModal()">+ Add Column</button>
        </div>
        <table><thead><tr><th>Name</th><th>Type</th><th>PK</th><th>Nullable</th><th>Default</th><th></th></tr></thead>
        <tbody>${cols.map(c => `<tr>
          <td>${esc(c.name)}</td><td>${esc(c.type||'ANY')}</td>
          <td>${c.pk?'✓':''}</td>
          <td>${c.notnull?'NO':'YES'}</td>
          <td>${esc(c.default||'')}</td>
          <td><button class="btn sm danger" onclick="dropColumnConfirm('${esc(c.name)}')">Drop</button></td>
        </tr>`).join('')}</tbody></table>
      </div>
      ${schema.data.foreign_keys.length ? `
      <div class="card"><h3>Foreign Keys</h3>
        <table><thead><tr><th>Column</th><th>References</th></tr></thead><tbody>
        ${schema.data.foreign_keys.map(fk => `<tr><td>${esc(fk.from)}</td><td>${esc(fk.to_table)}.${esc(fk.to_column)}</td></tr>`).join('')}
        </tbody></table></div>` : ''}`;
  } catch (e) { panel.innerHTML = `<div class="empty"><p style="color:var(--danger)">${esc(e.message)}</p></div>`; }
}
function addColumnModal() {
  showModal(`<h2>Add Column</h2>
    <div class="form-group"><label>Name</label><input id="acName" placeholder="column_name"></div>
    <div class="form-group"><label>Type</label>
      <select id="acType"><option>TEXT</option><option>INTEGER</option><option>REAL</option>
      <option>BLOB</option><option>BOOLEAN</option><option>DATE</option><option>DATETIME</option><option>JSON</option></select></div>
    <div class="form-group"><label>Default (optional)</label><input id="acDefault" placeholder="e.g. 0 or 'abc'"></div>
    <div class="checkbox-wrap"><input type="checkbox" id="acNullable" checked><label for="acNullable">Nullable</label></div>
    <div class="modal-actions">
      <button class="btn" onclick="closeModal()">Cancel</button>
      <button class="btn primary" onclick="doAddColumn()">Add</button>
    </div>`);
}
async function doAddColumn() {
  const body = {
    name: $('#acName').value.trim(),
    type: $('#acType').value,
    nullable: $('#acNullable').checked,
    default: $('#acDefault').value.trim() || null,
  };
  try {
    await api(`/project/${state.project}/table/${state.table}/add_column`, {
      method: 'POST', body: JSON.stringify(body)
    });
    closeModal(); toast('Column added', 'success'); renderTableStructure();
  } catch (e) { toast(e.message, 'error'); }
}
function dropColumnConfirm(name) {
  confirmModal(`Drop column "${name}"?`, 'Data in this column will be lost.', async () => {
    try {
      await api(`/project/${state.project}/table/${state.table}/drop_column`, {
        method: 'POST', body: JSON.stringify({ name })
      });
      toast('Column dropped', 'success'); renderTableStructure();
    } catch (e) { toast(e.message, 'error'); }
  });
}

async function renderTableIndexes() {
  const panel = $('#tablePanel');
  try {
    const schema = await api(`/project/${state.project}/table/${state.table}/schema`);
    const idx = schema.data.indexes;
    panel.innerHTML = `<div class="card"><h3>Indexes</h3>
      ${idx.length ? `<table><thead><tr><th>Name</th><th>Unique</th><th>Columns</th></tr></thead><tbody>
      ${idx.map(i => `<tr><td>${esc(i.name)}</td><td>${i.unique?'✓':''}</td><td>${i.columns.map(esc).join(', ')}</td></tr>`).join('')}
      </tbody></table>` : '<p style="color:var(--fg2)">No indexes. Run SQL to create one:</p><div class="code-block">CREATE INDEX idx_name ON '+esc(state.table)+'(column);</div>'}
    </div>`;
  } catch (e) { panel.innerHTML = `<div class="empty"><p style="color:var(--danger)">${esc(e.message)}</p></div>`; }
}

// ============================================================
// TABLE API DOCS
// ============================================================
async function renderTableAPI() {
  const base = window.location.origin;
  const url = `${base}/api/project/${state.project}/table/${state.table}`;
  const panel = $('#tablePanel');
  panel.innerHTML = `
    <div class="card">
      <h3>Endpoints for <code>${esc(state.table)}</code></h3>
      <div class="code-block">GET    ${url}<button class="copy-btn" onclick="copyText('${url}')">Copy</button></div>
      <div class="code-block">POST   ${url}<button class="copy-btn" onclick="copyText('${url}')">Copy</button></div>
      <div class="code-block">PATCH  ${url}/{rowid}<button class="copy-btn" onclick="copyText('${url}/{rowid}')">Copy</button></div>
      <div class="code-block">DELETE ${url}/{rowid}<button class="copy-btn" onclick="copyText('${url}/{rowid}')">Copy</button></div>
    </div>
    <div class="card"><h3>JavaScript</h3>
      <div class="code-block">const res = await fetch("${url}");<button class="copy-btn" onclick="copyText('const res = await fetch(&quot;${url}&quot;);')">Copy</button></div>
    </div>
    <div class="card"><h3>Python</h3>
      <div class="code-block">import requests
r = requests.get("${url}")
print(r.json())<button class="copy-btn" onclick="copyText('import requests\\nr = requests.get(&quot;${url}&quot;)\\nprint(r.json())')">Copy</button></div>
    </div>
    <div class="card"><h3>cURL</h3>
      <div class="code-block">curl "${url}"<button class="copy-btn" onclick="copyText('curl &quot;${url}&quot;')">Copy</button></div>
    </div>
    <div class="card"><h3>Query Parameters</h3>
      <table><thead><tr><th>Param</th><th>Example</th></tr></thead><tbody>
      <tr><td>limit</td><td>?limit=50</td></tr>
      <tr><td>offset</td><td>?offset=100</td></tr>
      <tr><td>sort</td><td>?sort=created_at&order=desc</td></tr>
      <tr><td>filter eq</td><td>?filter[name][eq]=Alice</td></tr>
      <tr><td>filter gt</td><td>?filter[age][gt]=18</td></tr>
      <tr><td>filter in</td><td>?filter[id][in]=1,2,3</td></tr>
      </tbody></table>
    </div>`;
}

// ============================================================
// SQL EDITOR
// ============================================================
async function renderSQL(content) {
  if (!state.project) { content.innerHTML = '<div class="empty"><p>Select a project first.</p></div>'; return; }
  content.innerHTML = `
    <div class="toolbar">
      <button class="btn primary" onclick="runSQL()">▶ Run (Ctrl+Enter)</button>
      <button class="btn" onclick="$('#sqlEditor').value=''">Clear</button>
      <button class="btn" onclick="saveQueryModal()">💾 Save Query</button>
      <button class="btn" onclick="loadSavedQueries()">📂 Load Saved</button>
      <span id="sqlStatus" style="margin-left:auto;color:var(--fg2);font-size:12px"></span>
    </div>
    <textarea class="sql-editor" id="sqlEditor" placeholder="SELECT * FROM users;" onkeydown="if(event.ctrlKey&&event.key==='Enter'){event.preventDefault();runSQL()}"></textarea>
    <div id="sqlResult" style="margin-top:16px"></div>`;
}
async function runSQL() {
  const sql = $('#sqlEditor').value;
  if (!sql.trim()) return;
  $('#sqlStatus').textContent = 'Running...';
  const t0 = performance.now();
  try {
    const res = await api(`/project/${state.project}/sql`, {
      method: 'POST', body: JSON.stringify({ sql })
    });
    const d = res.data;
    $('#sqlStatus').textContent = `Done in ${(performance.now()-t0).toFixed(1)}ms`;
    const panel = $('#sqlResult');
    if (d.type === 'select') {
      panel.innerHTML = `<div class="card" style="padding:0;overflow:auto;max-height:60vh">
        <div style="padding:12px;border-bottom:1px solid var(--border);color:var(--fg2);font-size:12px">${d.row_count} rows · ${d.duration_ms.toFixed(1)}ms</div>
        <table><thead><tr>${d.columns.map(c=>`<th>${esc(c)}</th>`).join('')}</tr></thead>
        <tbody>${d.rows.map(r=>`<tr>${d.columns.map(c=>`<td>${r[c]===null?'<span style="color:var(--fg2)">NULL</span>':esc(r[c])}</td>`).join('')}</tr>`).join('')}</tbody></table>
      </div>`;
    } else {
      panel.innerHTML = `<div class="card"><span class="pill green">${d.row_count} rows affected</span>
        <span class="pill blue" style="margin-left:8px">${d.duration_ms.toFixed(1)}ms</span>
        ${d.last_row_id ? `<span class="pill" style="margin-left:8px">last id: ${d.last_row_id}</span>`:''}</div>`;
    }
    toast('SQL executed', 'success');
  } catch (e) {
    $('#sqlStatus').textContent = 'Error';
    $('#sqlResult').innerHTML = `<div class="card" style="border-left:3px solid var(--danger)"><b style="color:var(--danger)">Error</b><pre style="margin-top:8px;white-space:pre-wrap">${esc(e.message)}</pre></div>`;
    toast('SQL error', 'error');
  }
}
function saveQueryModal() {
  showModal(`<h2>Save Query</h2>
    <div class="form-group"><label>Name</label><input id="sqName" placeholder="My query"></div>
    <div class="modal-actions"><button class="btn" onclick="closeModal()">Cancel</button>
    <button class="btn primary" onclick="doSaveQuery()">Save</button></div>`);
}
async function doSaveQuery() {
  const name = $('#sqName').value.trim() || 'Query';
  const sql = $('#sqlEditor').value;
  try {
    await api(`/project/${state.project}/saved-queries`, {
      method: 'POST', body: JSON.stringify({ name, sql })
    });
    closeModal(); toast('Query saved', 'success');
  } catch (e) { toast(e.message, 'error'); }
}
async function loadSavedQueries() {
  try {
    const res = await api(`/project/${state.project}/saved-queries`);
    const list = res.data || [];
    if (!list.length) { toast('No saved queries'); return; }
    showModal(`<h2>Saved Queries</h2>${list.map(q =>
      `<div style="display:flex;justify-content:space-between;padding:8px;border-bottom:1px solid var(--border)">
        <a href="#" style="color:var(--accent2)" onclick="event.preventDefault();loadQuery('${q.id}');closeModal();">${esc(q.name)}</a>
        <button class="btn sm danger" onclick="delSavedQuery('${q.id}')">×</button>
      </div>`).join('')}
      <div class="modal-actions"><button class="btn" onclick="closeModal()">Close</button></div>`);
    window._savedQueries = list;
  } catch (e) { toast(e.message, 'error'); }
}
function loadQuery(id) {
  const q = (window._savedQueries||[]).find(x => x.id === id);
  if (q) $('#sqlEditor').value = q.sql;
}
async function delSavedQuery(id) {
  await api(`/saved-queries/${id}`, { method: 'DELETE' });
  closeModal(); toast('Query deleted', 'success');
}

// ============================================================
// API PAGE
// ============================================================
async function renderAPI(content) {
  if (!state.project) { content.innerHTML = '<div class="empty"><p>Select a project first.</p></div>'; return; }
  const base = window.location.origin;
  const projUrl = `${base}/api/project/${state.project}/table/{table}`;
  content.innerHTML = `
    <div class="card">
      <h3>Base URL</h3>
      <div class="code-block">${esc(base)}/api<button class="copy-btn" onclick="copyText('${base}/api')">Copy</button></div>
      <h3 style="margin-top:16px">Project Endpoint Pattern</h3>
      <div class="code-block">${esc(projUrl)}<button class="copy-btn" onclick="copyText('${projUrl}')">Copy</button></div>
    </div>
    <div class="card">
      <h3>Authentication</h3>
      <p style="color:var(--fg2);margin-bottom:8px">Optional. Send your API key:</p>
      <div class="code-block">Authorization: Bearer YOUR_KEY<button class="copy-btn" onclick="copyText('Authorization: Bearer YOUR_KEY')">Copy</button></div>
      <div class="code-block">X-API-Key: YOUR_KEY<button class="copy-btn" onclick="copyText('X-API-Key: YOUR_KEY')">Copy</button></div>
    </div>
    <div class="card">
      <h3>OpenAPI Docs</h3>
      <p><a href="/docs" target="_blank" style="color:var(--accent2)">/docs</a> · <a href="/redoc" target="_blank" style="color:var(--accent2)">/redoc</a></p>
    </div>`;
}

// ============================================================
// API KEYS
// ============================================================
async function renderKeys(content) {
  try {
    const res = await api('/api-keys');
    const keys = res.data || [];
    content.innerHTML = `
      <div class="toolbar">
        <button class="btn primary" onclick="newKeyModal()">+ Create Key</button>
        <button class="btn" onclick="render()">↻ Refresh</button>
      </div>
      <div class="card">
        ${keys.length === 0 ? '<div class="empty"><p>No API keys yet.</p></div>' :
        `<table><thead><tr><th>Name</th><th>Role</th><th>Project</th><th>Key</th><th>Status</th><th></th></tr></thead>
        <tbody>${keys.map(k => `<tr>
          <td>${esc(k.name)}</td>
          <td><span class="pill ${k.role==='server'?'red':'blue'}">${esc(k.role)}</span></td>
          <td>${esc(k.project_id||'global')}</td>
          <td><code style="font-size:11px">${esc(k.key_masked)}</code></td>
          <td>${k.revoked?'<span class="pill red">revoked</span>':'<span class="pill green">active</span>'}</td>
          <td>
            ${k.revoked?'':`<button class="btn sm" onclick="revokeKey('${k.id}')">Revoke</button>`}
            <button class="btn sm danger" onclick="deleteKey('${k.id}')">Delete</button>
          </td></tr>`).join('')}</tbody></table>`}
      </div>`;
  } catch (e) { content.innerHTML = `<div class="empty"><p style="color:var(--danger)">${esc(e.message)}</p></div>`; }
}
function newKeyModal() {
  showModal(`<h2>Create API Key</h2>
    <div class="form-group"><label>Name</label><input id="nkName" placeholder="My key"></div>
    <div class="form-group"><label>Role</label>
      <select id="nkRole"><option value="public">public (read-only intent)</option>
      <option value="server">server (full access)</option></select></div>
    <div class="form-group"><label>Scope</label>
      <select id="nkProject"><option value="">Global (all projects)</option>
      ${state.projects.map(p=>`<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('')}</select></div>
    <div class="modal-actions"><button class="btn" onclick="closeModal()">Cancel</button>
    <button class="btn primary" onclick="doCreateKey()">Create</button></div>`);
}
async function doCreateKey() {
  try {
    const res = await api('/api-keys', { method: 'POST', body: JSON.stringify({
      name: $('#nkName').value.trim() || 'Untitled',
      role: $('#nkRole').value,
      project_id: $('#nkProject').value || null,
    })});
    const key = res.data.key;
    showModal(`<h2>API Key Created</h2>
      <p style="color:var(--fg2);margin-bottom:8px">Copy it now — you won't see it again in this form.</p>
      <div class="code-block">${esc(key)}<button class="copy-btn" onclick="copyText('${esc(key)}')">Copy</button></div>
      <div class="modal-actions"><button class="btn primary" onclick="closeModal();render()">Done</button></div>`);
  } catch (e) { toast(e.message, 'error'); }
}
async function revokeKey(id) { await api(`/api-keys/${id}/revoke`, {method:'POST'}); render(); }
async function deleteKey(id) {
  confirmModal('Delete key?', 'This cannot be undone.', async () => {
    await api(`/api-keys/${id}`, {method:'DELETE'}); render();
  });
}

// ============================================================
// LOGS
// ============================================================
async function renderLogs(content) {
  try {
    const res = await api('/logs?limit=200');
    const logs = res.data || [];
    content.innerHTML = `
      <div class="toolbar">
        <button class="btn" onclick="render()">↻ Refresh</button>
        <button class="btn danger" onclick="clearLogs()">Clear Logs</button>
      </div>
      <div class="card" style="padding:0;max-height:75vh;overflow:auto">
        ${logs.length === 0 ? '<div class="empty"><p>No logs yet.</p></div>' :
        `<table><thead><tr><th>Time</th><th>Method</th><th>Endpoint</th><th>Status</th><th>ms</th><th>Project</th></tr></thead>
        <tbody>${logs.map(l => `<tr>
          <td style="font-size:11px">${esc((l.timestamp||'').replace('T',' ').slice(0,19))}</td>
          <td><span class="pill">${esc(l.method)}</span></td>
          <td style="font-size:11px;max-width:400px">${esc(l.endpoint)}</td>
          <td><span class="pill ${l.status<400?'green':'red'}">${l.status}</span></td>
          <td>${(l.duration_ms||0).toFixed(1)}</td>
          <td>${esc(l.project||'')}</td>
        </tr>`).join('')}</tbody></table>`}
      </div>`;
  } catch (e) { content.innerHTML = `<div class="empty"><p style="color:var(--danger)">${esc(e.message)}</p></div>`; }
}
async function clearLogs() {
  confirmModal('Clear all logs?', '', async () => {
    await api('/logs', {method:'DELETE'}); render();
  });
}

// ============================================================
// BACKUPS
// ============================================================
async function renderBackups(content) {
  try {
    const res = await api('/backups');
    const backups = res.data || [];
    content.innerHTML = `
      <div class="toolbar">
        ${state.project ? `<button class="btn primary" onclick="createBackup()">+ Backup ${esc(state.project)}</button>`:''}
        <button class="btn" onclick="render()">↻ Refresh</button>
      </div>
      <div class="card">
        ${backups.length === 0 ? '<div class="empty"><p>No backups yet.</p></div>' :
        `<table><thead><tr><th>Name</th><th>Size</th><th>Created</th><th></th></tr></thead>
        <tbody>${backups.map(b => `<tr>
          <td>${esc(b.name)}</td>
          <td>${(b.size/1024).toFixed(1)} KB</td>
          <td style="font-size:11px">${esc(b.created_at.slice(0,19))}</td>
          <td>
            <a class="btn sm" href="${API}/backups/${esc(b.name)}/download" download>Download</a>
            <button class="btn sm danger" onclick="delBackup('${esc(b.name)}')">Delete</button>
          </td></tr>`).join('')}</tbody></table>`}
      </div>`;
  } catch (e) { content.innerHTML = `<div class="empty"><p style="color:var(--danger)">${esc(e.message)}</p></div>`; }
}
async function createBackup() {
  try { await api(`/project/${state.project}/backup`, {method:'POST'}); toast('Backup created', 'success'); render(); }
  catch (e) { toast(e.message, 'error'); }
}
async function delBackup(name) {
  confirmModal('Delete backup?', name, async () => {
    await api(`/backups/${name}`, {method:'DELETE'}); render();
  });
}

// ============================================================
// SETTINGS
// ============================================================
async function renderSettings(content) {
  if (!state.project) { content.innerHTML = '<div class="empty"><p>Select a project first.</p></div>'; return; }
  const info = await api('/info');
  content.innerHTML = `
    <div class="card">
      <h3>Project Settings</h3>
      <div class="form-group"><label>Project ID</label><input value="${esc(state.project)}" disabled></div>
      <div class="form-group"><label>API Base URL</label><input value="${esc(info.data.api_url)}/project/${esc(state.project)}" readonly></div>
      <div class="form-group"><label>Data directory</label><input value="${esc(info.data.data_dir)}" readonly></div>
    </div>
    <div class="card" style="border-left:3px solid var(--danger)">
      <h3 style="color:var(--danger)">Danger Zone</h3>
      <p style="color:var(--fg2);margin:8px 0">Permanently delete this project and all its data.</p>
      <button class="btn danger" onclick="deleteProjectConfirm('${esc(state.project)}','${esc(state.project)}')">Delete Project</button>
    </div>`;
}

// ============================================================
// PROJECTS
// ============================================================
function newProjectModal() {
  showModal(`<h2>Create Project</h2>
    <div class="form-group"><label>Project ID (lowercase letters, digits, -, _)</label>
      <input id="npId" placeholder="my-app" pattern="[a-z0-9_-]+"></div>
    <div class="form-group"><label>Display Name</label><input id="npName" placeholder="My App"></div>
    <div class="modal-actions"><button class="btn" onclick="closeModal()">Cancel</button>
    <button class="btn primary" onclick="doCreateProject()">Create</button></div>`);
}
async function doCreateProject() {
  const id = $('#npId').value.trim();
  const name = $('#npName').value.trim() || id;
  if (!id) { toast('Project ID required', 'error'); return; }
  try {
    await api('/projects', { method: 'POST', body: JSON.stringify({ id, name })});
    closeModal(); toast('Project created', 'success');
    await loadProjects();
    selectProject(id);
  } catch (e) { toast(e.message, 'error'); }
}
function deleteProjectConfirm(id, name) {
  showModal(`<h2>Delete Project</h2>
    <p style="color:var(--fg2);margin-bottom:12px">Type the project ID <b>${esc(id)}</b> to confirm.</p>
    <div class="form-group"><input id="delConfirm" placeholder="${esc(id)}"></div>
    <div class="modal-actions"><button class="btn" onclick="closeModal()">Cancel</button>
    <button class="btn danger" onclick="doDeleteProject('${esc(id)}')">Delete</button></div>`);
}
async function doDeleteProject(id) {
  if ($('#delConfirm').value !== id) { toast('Name mismatch', 'error'); return; }
  try {
    await api(`/projects/${id}`, {method:'DELETE'});
    closeModal(); toast('Project deleted', 'success');
    if (state.project === id) { state.project = null; state.page = 'overview'; state.table = null; }
    await loadProjects(); render();
  } catch (e) { toast(e.message, 'error'); }
}

// ============================================================
// CREATE / DROP TABLE
// ============================================================
function createTableModal() {
  showModal(`<h2>Create Table</h2>
    <div class="form-group"><label>Table Name</label><input id="ctName" placeholder="users"></div>
    <div id="ctColumns">
      <label style="font-size:12px;color:var(--fg2)">Columns</label>
      <div id="ctCols"></div>
      <button class="btn sm" type="button" onclick="addColRow()" style="margin-top:8px">+ Column</button>
    </div>
    <div class="modal-actions"><button class="btn" onclick="closeModal()">Cancel</button>
    <button class="btn primary" onclick="doCreateTable()">Create</button></div>`);
  addColRow('id', 'INTEGER', true, true);
  addColRow('created_at', 'DATETIME', false, false, 'CURRENT_TIMESTAMP');
}
function addColRow(name='', type='TEXT', pk=false, ai=false, def='') {
  const el = document.createElement('div');
  el.className = 'column-row';
  el.innerHTML = `
    <input placeholder="name" value="${esc(name)}" style="flex:1" class="cn">
    <select class="ct"><option ${type==='TEXT'?'selected':''}>TEXT</option>
      <option ${type==='INTEGER'?'selected':''}>INTEGER</option>
      <option ${type==='REAL'?'selected':''}>REAL</option>
      <option ${type==='BLOB'?'selected':''}>BLOB</option>
      <option ${type==='BOOLEAN'?'selected':''}>BOOLEAN</option>
      <option ${type==='DATE'?'selected':''}>DATE</option>
      <option ${type==='DATETIME'?'selected':''}>DATETIME</option>
      <option ${type==='JSON'?'selected':''}>JSON</option></select>
    <label class="checkbox-wrap"><input type="checkbox" class="cpk" ${pk?'checked':''}>PK</label>
    <label class="checkbox-wrap"><input type="checkbox" class="cai" ${ai?'checked':''}>AI</label>
    <label class="checkbox-wrap"><input type="checkbox" class="cnn">NN</label>
    <input placeholder="default" value="${esc(def)}" style="width:120px" class="cd">
    <button class="btn sm danger" onclick="this.parentElement.remove()">×</button>`;
  $('#ctCols').appendChild(el);
}
async function doCreateTable() {
  const name = $('#ctName').value.trim();
  if (!name) { toast('Table name required', 'error'); return; }
  const columns = $$('#ctCols .column-row').map(r => ({
    name: $('.cn', r).value.trim(),
    type: $('.ct', r).value,
    primary_key: $('.cpk', r).checked,
    auto_increment: $('.cai', r).checked,
    nullable: !$('.cnn', r).checked,
    default: $('.cd', r).value.trim() || null,
  })).filter(c => c.name);
  try {
    await api(`/project/${state.project}/table/${name}/create`, {
      method: 'POST', body: JSON.stringify({ columns })
    });
    closeModal(); toast('Table created', 'success'); render();
  } catch (e) { toast(e.message, 'error'); }
}
function renameTableModal(name) {
  showModal(`<h2>Rename Table</h2>
    <div class="form-group"><label>New name</label><input id="rtName" value="${esc(name)}"></div>
    <div class="modal-actions"><button class="btn" onclick="closeModal()">Cancel</button>
    <button class="btn primary" onclick="doRenameTable('${esc(name)}')">Rename</button></div>`);
}
async function doRenameTable(oldName) {
  const newName = $('#rtName').value.trim();
  try {
    await api(`/project/${state.project}/table/${oldName}/rename`, {
      method: 'POST', body: JSON.stringify({ new_name: newName })
    });
    closeModal(); toast('Table renamed', 'success');
    if (state.table === oldName) state.table = newName;
    render();
  } catch (e) { toast(e.message, 'error'); }
}
function dropTableConfirm(name) {
  confirmModal(`Drop table "${name}"?`, 'All data in this table will be permanently lost.', async () => {
    try {
      await api(`/project/${state.project}/table/${name}/drop`, {method:'POST'});
      toast('Table dropped', 'success');
      if (state.table === name) state.table = null;
      render();
    } catch (e) { toast(e.message, 'error'); }
  });
}

// ============================================================
// WEBSOCKET (realtime)
// ============================================================
function connectWS() {
  if (state.ws) try { state.ws.close(); } catch {}
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const url = `${proto}//${location.host}/ws` + (state.project ? `?project=${state.project}` : '');
  const ws = new WebSocket(url);
  state.ws = ws;
  ws.onmessage = (ev) => {
    try {
      const msg = JSON.parse(ev.data);
      if (msg.type === 'insert' || msg.type === 'update' || msg.type === 'delete') {
        if (state.page === 'database' && state.table === msg.table && state.tableTab === 'data') {
          renderTableData();
        }
      }
    } catch {}
  };
  ws.onclose = () => setTimeout(connectWS, 3000);
}

// ============================================================
// INIT
// ============================================================
async function init() {
  const t = localStorage.getItem('lb-theme');
  if (t) { state.theme = t; document.body.dataset.theme = t; }
  // responsive menu
  function updateMenu() {
    $('#menuBtn').style.display = window.innerWidth < 768 ? 'inline-block' : 'none';
  }
  window.addEventListener('resize', updateMenu);
  updateMenu();

  await loadProjects();
  render();
  connectWS();
  // keyboard
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeModal();
  });
}

init();
</script>
</body>
</html>
"""


# ============================================================
# ROUTES — DASHBOARD
# ============================================================

@app.get("/", response_class=HTMLResponse)
async def dashboard_root():
    return HTMLResponse(INDEX_HTML)


@app.get("/favicon.ico")
async def favicon():
    return PlainTextResponse("", status_code=204)


# ============================================================
# ENTRYPOINT
# ============================================================

def cli_create_project(pid: str) -> None:
    init_meta_db()
    try:
        proj = create_project(pid)
        print(f"✓ Created project: {proj['id']}")
    except HTTPException as e:
        print(f"✗ {e.detail}")
        sys.exit(1)


def cli_list_projects() -> None:
    init_meta_db()
    projects = list_projects()
    if not projects:
        print("No projects yet.")
        return
    print(f"{'ID':<24} {'NAME':<24} CREATED")
    for p in projects:
        print(f"{p['id']:<24} {p['name']:<24} {p['created_at'][:19]}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="localbase",
        description=f"{APP_NAME} — {VERSION} — Your self-hosted backend."
    )
    parser.add_argument("--host", default=os.environ.get("LOCALBASE_HOST", "127.0.0.1"),
                        help="Host to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("LOCALBASE_PORT", "8000")),
                        help="Port (default: 8000)")
    parser.add_argument("--data", default=None, help="Data directory")
    parser.add_argument("--version", action="store_true", help="Show version")
    parser.add_argument("--reload", action="store_true", help="Auto-reload (development)")
    sub = parser.add_subparsers(dest="cmd")
    sp1 = sub.add_parser("create-project", help="Create a project")
    sp1.add_argument("project_id")
    sub.add_parser("list-projects", help="List projects")

    args = parser.parse_args()

    if args.version:
        print(f"{APP_NAME} {VERSION}")
        return

    # Set config
    CONFIG["data_dir"] = get_data_dir(args.data)
    CONFIG["secret"] = os.environ.get("LOCALBASE_SECRET") or secrets.token_urlsafe(32)
    init_meta_db()

    if args.cmd == "create-project":
        cli_create_project(args.project_id)
        return
    if args.cmd == "list-projects":
        cli_list_projects()
        return

    # Banner
    print(f"""
  ╦  ╔═╗╔═╗╔═╗╦  ╔╗ ╔═╗╔═╗╔═╗
  ║  ║ ║║  ╠═╣║  ╠╩╗╠═╣╚═╗║╣
  ╩═╝╚═╝╚═╝╩ ╩╩═╝╚═╝╩ ╩╚═╝╚═╝   v{VERSION}

  Your self-hosted backend. Simple, local, and yours.

  Dashboard:  http://{args.host}:{args.port}
  API base:   http://{args.host}:{args.port}/api
  Docs:       http://{args.host}:{args.port}/docs
  Data dir:   {CONFIG['data_dir']}

  Press Ctrl+C to stop.
""")

    uvicorn.run(app, host=args.host, port=args.port,
                log_level="warning", reload=args.reload)


if __name__ == "__main__":
    main()
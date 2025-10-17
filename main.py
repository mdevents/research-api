# main.py
import os
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, HTTPException, Depends, Query, Header, Body
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from supabase import create_client, Client
from postgrest import APIError
from dotenv import load_dotenv

# ------------------ ENV ------------------
load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_ANON_KEY")  # für Reads reicht anon; für Writes ggf. Service Role nutzen
SERVER_API_KEY = os.getenv("API_KEY")          # eigener Proxy-Key, wird als X-API-Key erwartet

# ------------------ APP ------------------
app = FastAPI(title="Research DB API", version="1.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

class NormalizeSlashesMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        scope = request.scope
        path = scope.get("path", "")
        while '//' in path:
            path = path.replace('//', '/')
        scope['path'] = path
        request._scope = scope
        return await call_next(request)

app.add_middleware(NormalizeSlashesMiddleware)

# ------------------ UTILS ------------------
def require_env():
    missing = []
    if not SUPABASE_URL: missing.append("SUPABASE_URL")
    if not SUPABASE_KEY: missing.append("SUPABASE_ANON_KEY")
    if missing:
        raise HTTPException(status_code=500, detail={"error": "Missing environment variables", "missing": missing})

def get_client() -> Client:
    require_env()
    return create_client(SUPABASE_URL, SUPABASE_KEY)

def auth(x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
    # Wenn du ohne API-Key testen willst: Zeile darunter temporär auskommentieren.
    if SERVER_API_KEY and x_api_key != SERVER_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return True

# ------------------ HEALTH ------------------
@app.get("/health")
def health():
    return {
        "ok": True,
        "has_SUPABASE_URL": bool(SUPABASE_URL),
        "has_SUPABASE_ANON_KEY": bool(SUPABASE_KEY),
        "requires_api_key": bool(SERVER_API_KEY),
        "version": "1.2.0"
    }

# ------------------ STUDIES (READ) ------------------
@app.get("/studies")
def list_studies(
    # Freitext im Titel via ILIKE
    title: Optional[str] = Query(None, description="Case-insensitive Suche im Titel (ILIKE). Beispiel: magnesium"),
    # exakte Identifier
    doi: Optional[str] = Query(None, description="Exakter DOI-Match"),
    pmid: Optional[str] = Query(None, description="Exakter PMID-Match"),
    # Jahr-Filter
    year_gte: Optional[int] = Query(None, description="z. B. 2015"),
    year_lte: Optional[int] = Query(None, description="z. B. 2025"),
    # Array-Contains Filter
    tag: Optional[str] = Query(None, description="Element in tags[]"),
    outcome: Optional[str] = Query(None, description="Element in outcomes[]"),
    # Sortierung & Limit
    order: Optional[str] = Query(None, description="z. B. year.desc oder created_at.desc"),
    limit: int = Query(200, ge=1, le=2000),
    _=Depends(auth),
):
    """
    Liefert Studien aus public.studies gemäß deinem Schema:
      - id, doi, pmid, year, study_design, n_participants, title, journal, abstract,
        outcomes (text[]), tags (text[]), source_url, created_at, updated_at
    WICHTIG: Spalte heißt 'study_design' (nicht 'design').
    """
    sb = get_client()
    q = sb.table("studies").select(
        "id,doi,pmid,year,study_design,n_participants,title,journal,abstract,outcomes,tags,source_url,created_at,updated_at"
    )

    # Identifier-Filter
    if doi:
        q = q.eq("doi", doi)
    if pmid:
        q = q.eq("pmid", pmid)

    # Titel ILIKE
    if title:
        pattern = title if ("%" in title or "_" in title) else f"%{title}%"
        q = q.ilike("title", pattern)

    # Jahrbereich
    if year_gte is not None:
        q = q.gte("year", year_gte)
    if year_lte is not None:
        q = q.lte("year", year_lte)

    # Arrays: contains
    if tag:
        q = q.contains("tags", [tag])
    if outcome:
        q = q.contains("outcomes", [outcome])

    # Order
    if order:
        # Erwartet "col.dir", z. B. "year.desc"
        parts = order.split(".")
        col = parts[0]
        desc = len(parts) > 1 and parts[1].lower() == "desc"
        q = q.order(col, desc=desc, nullsfirst=False)

    try:
        res = q.limit(limit).execute()
        return res.data or []
    except APIError as e:
        detail = e.args[0] if e.args else {"message": "PostgREST error"}
        # typ. DB-Fehler (falsche Spalte etc.) → 400 an Client
        raise HTTPException(status_code=400, detail=detail)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ------------------ STUDIES MIN-VIEW (READ) ------------------
@app.get("/studies_min")
def list_studies_min(
    order: Optional[str] = Query(None, description="z. B. year.desc"),
    limit: int = Query(200, ge=1, le=2000),
    _=Depends(auth),
):
    """
    Optionaler Endpunkt für deine View public.studies_min.
    """
    sb = get_client()
    q = sb.rpc("rpc_passthrough", {})  # Platzhalter, falls du später RPC brauchst

    # Direkt auf View zugreifen:
    q = get_client().table("studies_min").select("id,identifier,year,study_design,n_participants,title,journal,tags,outcomes")
    if order:
        parts = order.split(".")
        col = parts[0]
        desc = len(parts) > 1 and parts[1].lower() == "desc"
        q = q.order(col, desc=desc, nullsfirst=False)

    try:
        res = q.limit(limit).execute()
        return res.data or []
    except APIError as e:
        raise HTTPException(status_code=400, detail=e.args[0] if e.args else "PostgREST error")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ------------------ STUDIES (UPSERT ONE) ------------------
@app.post("/studies")
def upsert_study(
    study: Dict[str, Any] = Body(..., description="Eine Studien-Zeile im JSON-Format"),
    on_conflict: Optional[str] = Query(None, description="Konfliktspalte: 'doi' oder 'pmid'. Wenn leer, wird automatisch gewählt."),
    _=Depends(auth),
):
    """
    Upsert EINER Studie. Nutzt Prefer 'merge-duplicates' + 'return=representation'.
    Achtung RLS: Für Writes ggf. Service-Role-Key setzen oder Policy erlauben.
    Auto-Handling:
      - Falls 'design' im Payload vorkommt, wird es nach 'study_design' gemappt.
      - Wenn 'on_conflict' nicht gesetzt ist:
          -> wenn doi vorhanden: on_conflict='doi'
          -> sonst, wenn pmid vorhanden: on_conflict='pmid'
          -> sonst Fehler (mind. doi oder pmid muss existieren; siehe DB-Check-Constraint)
    """
    sb = get_client()

    # Legacy-Mapping: design -> study_design
    if "design" in study and "study_design" not in study:
        study["study_design"] = study.pop("design")

    # Automatische Konfliktspalte bestimmen
    conflict_col = on_conflict
    if not conflict_col:
        doi = (study.get("doi") or "") if isinstance(study.get("doi"), str) else study.get("doi")
        pmid = (study.get("pmid") or "") if isinstance(study.get("pmid"), str) else study.get("pmid")
        if doi:
            conflict_col = "doi"
        elif pmid:
            conflict_col = "pmid"
        else:
            raise HTTPException(status_code=400, detail="Upsert erfordert mindestens doi oder pmid (siehe DB-Constraint).")

    try:
        res = sb.table("studies").upsert(
            study,
            on_conflict=conflict_col,
            returning="representation",
            ignore_duplicate_updates=False
        ).execute()
        return res.data or []
    except APIError as e:
        detail = e.args[0] if e.args else {"message": "PostgREST error"}
        # 401/403 → meist RLS/Key-Problem
        raise HTTPException(status_code=400, detail=detail)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ------------------ OPTIONALE LISTEN (falls du weitere Tabellen ergänzt) ------------------
# Placeholder-Endpunkte, falls du später normalisierte Tags/Outcomes einführst.

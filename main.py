import os
from typing import Optional, List
from fastapi import FastAPI, HTTPException, Depends, Query, Header
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_ANON_KEY")   # für Lesen reicht anon key
SERVER_API_KEY = os.getenv("API_KEY")

app = FastAPI(title="Research DB API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],            # bei Bedarf einschränken
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

from starlette.middleware.base import BaseHTTPMiddleware

class NormalizeSlashesMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        scope = request.scope
        path = scope.get("path", "")
        while '//' in path:
            path = path.replace('//', '/')
        scope['path'] = path
        request._scope = scope
        return await call_next(request)

def get_client() -> Client:
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError("Supabase env vars fehlen")
    return create_client(SUPABASE_URL, SUPABASE_KEY)

def auth(x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
    if not SERVER_API_KEY:        # falls du temporär ohne Key testen willst
        return True
    if x_api_key != SERVER_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return True

@app.get("/health")
def health():
    return {"ok": True}

# ---- High-level View (einfach) ----
@app.get("/measurements")
def measurements(
    topic: Optional[str] = Query(None),
    domain: Optional[str] = Query(None),
    variable: Optional[str] = Query(None),
    year_gte: Optional[int] = None,
    year_lte: Optional[int] = None,
    limit: int = Query(200, ge=1, le=2000),
    _=Depends(auth),
):
    sb = get_client()
    q = sb.table("v_topic_measurements").select("*")
    if topic:   q = q.eq("topic", topic)
    if domain:  q = q.eq("domain", domain)
    if variable:q = q.eq("variable", variable)
    if year_gte is not None: q = q.gte("year", year_gte)
    if year_lte is not None: q = q.lte("year", year_lte)
    res = q.limit(limit).execute()
    return res.data or []

# ---- Rohe Tabellen (volle DB) ----
@app.get("/studies")
def list_studies(
    title_ilike: Optional[str] = Query(None, description="z.B. %magnesium%"),
    year_gte: Optional[int] = None,
    year_lte: Optional[int] = None,
    limit: int = Query(200, ge=1, le=2000),
    _=Depends(auth),
):
    sb = get_client()
    q = sb.table("studies").select("id,title,year,journal,doi,design")
    if title_ilike: q = q.ilike("title", title_ilike)
    if year_gte is not None: q = q.gte("year", year_gte)
    if year_lte is not None: q = q.lte("year", year_lte)
    res = q.limit(limit).execute()
    return res.data or []

@app.get("/topics")
def list_topics(limit: int = Query(500, ge=1, le=5000), _=Depends(auth)):
    sb = get_client()
    res = sb.table("topics").select("*").order("name").limit(limit).execute()
    return res.data or []

@app.get("/outcome_domains")
def list_domains(limit: int = Query(500, ge=1, le=5000), _=Depends(auth)):
    sb = get_client()
    res = sb.table("outcome_domains").select("*").order("name").limit(limit).execute()
    return res.data or []

@app.get("/outcome_variables")
def list_variables(
    domain_name: Optional[str] = Query(None, description="Filter per Domain-Name"),
    limit: int = Query(1000, ge=1, le=5000),
    _=Depends(auth),
):
    sb = get_client()
    q = sb.table("outcome_variables").select("id,domain_id,name,unit_default")
    if domain_name:
        # 1) Domain-ID lookup
        d = sb.table("outcome_domains").select("id").eq("name", domain_name).limit(1).execute()
        if not d.data: return []
        q = q.eq("domain_id", d.data[0]["id"])
    res = q.order("name").limit(limit).execute()
    return res.data or []

@app.get("/study_topics")
def list_study_topics(limit: int = Query(1000, ge=1, le=10000), _=Depends(auth)):
    sb = get_client()
    res = sb.table("study_topics").select("*").limit(limit).execute()
    return res.data or []

@app.get("/populations")
def list_populations(limit: int = Query(1000, ge=1, le=10000), _=Depends(auth)):
    sb = get_client()
    res = sb.table("populations").select("*").limit(limit).execute()
    return res.data or []

@app.get("/evidence")
def list_evidence(limit: int = Query(1000, ge=1, le=10000), _=Depends(auth)):
    sb = get_client()
    res = sb.table("evidence").select("*").limit(limit).execute()
    return res.data or []

import os
from typing import Optional, Dict, Any
from fastapi import FastAPI, HTTPException, Depends, Query, Header, Body
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from supabase import create_client, Client
from postgrest import APIError
from dotenv import load_dotenv

# ------------------ ENV ------------------
load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_ANON_KEY")  # For writes consider Service Role if RLS blocks
SERVER_API_KEY = os.getenv("API_KEY")          # Expect as X-API-Key

# ------------------ APP ------------------
app = FastAPI(title="Research DB API", version="1.4.0")

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
    if not SUPABASE_URL:
        missing.append("SUPABASE_URL")
    if not SUPABASE_KEY:
        missing.append("SUPABASE_ANON_KEY")
    if missing:
        raise HTTPException(status_code=500, detail={"error": "Missing environment variables", "missing": missing})

def get_client() -> Client:
    require_env()
    return create_client(SUPABASE_URL, SUPABASE_KEY)

def auth(x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
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
        "version": "1.4.0"
    }

# ------------------ STUDIES (READ) ------------------
@app.get("/studies")
def list_studies(
    # text search
    title: Optional[str] = Query(None, description="ILIKE on title"),
    author: Optional[str] = Query(None, description="ILIKE on author"),
    population: Optional[str] = Query(None, description="ILIKE on population"),
    comparison_group: Optional[str] = Query(None, description="ILIKE on comparison_group"),
    # identifiers
    doi: Optional[str] = Query(None, description="exact DOI"),
    pmid: Optional[str] = Query(None, description="exact PMID"),
    # years
    year_gte: Optional[int] = Query(None),
    year_lte: Optional[int] = Query(None),
    # arrays
    tag: Optional[str] = Query(None, description="element in tags[]"),
    outcome: Optional[str] = Query(None, description="element in outcomes[]"),
    # duration filters
    duration_weeks_gte: Optional[float] = Query(None),
    duration_weeks_lte: Optional[float] = Query(None),
    # sorting & limit
    order: Optional[str] = Query(None, description="e.g. year.desc, created_at.desc, study_design.asc"),
    limit: int = Query(200, ge=1, le=2000),
    _=Depends(auth),
):
    """
    Returns rows from public.studies with full current schema:
      id, doi, pmid, year, study_design, n_participants, title, journal, abstract,
      outcomes (text[]), tags (text[]), source_url, population, intervention (jsonb),
      comparison_group, duration_weeks, author, created_at, updated_at.
    """
    sb = get_client()
    q = sb.table("studies").select(
        "id,doi,pmid,year,study_design,n_participants,title,journal,abstract,"
        "outcomes,tags,source_url,population,intervention,comparison_group,duration_weeks,author,"
        "created_at,updated_at"
    )

    # identifiers
    if doi:
        q = q.eq("doi", doi)
    if pmid:
        q = q.eq("pmid", pmid)

    # ILIKE helpers
    def ilike(qb, col, val):
        if not val:
            return qb
        pattern = val if ("%" in val or "_" in val) else f"%{val}%"
        return qb.ilike(col, pattern)

    q = ilike(q, "title", title)
    q = ilike(q, "author", author)
    q = ilike(q, "population", population)
    q = ilike(q, "comparison_group", comparison_group)

    # years
    if year_gte is not None:
        q = q.gte("year", year_gte)
    if year_lte is not None:
        q = q.lte("year", year_lte)

    # arrays
    if tag:
        q = q.contains("tags", [tag])
    if outcome:
        q = q.contains("outcomes", [outcome])

    # duration
    if duration_weeks_gte is not None:
        q = q.gte("duration_weeks", duration_weeks_gte)
    if duration_weeks_lte is not None:
        q = q.lte("duration_weeks", duration_weeks_lte)

    # order (map legacy 'design' -> 'study_design')
    if order:
        parts = order.split(".")
        col = parts[0].strip()
        if col == "design":
            col = "study_design"
        direction = (parts[1].lower() if len(parts) > 1 else "asc")
        desc = direction == "desc"
        q = q.order(col, desc=desc, nullsfirst=False)

    try:
        res = q.limit(limit).execute()
        return res.data or []
    except APIError as e:
        detail = e.args[0] if e.args else {"message": "PostgREST error"}
        raise HTTPException(status_code=400, detail=detail)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ------------------ STUDIES (UPSERT ONE) ------------------
@app.post("/studies")
def upsert_study(
    study: Dict[str, Any] = Body(..., description="One study row (JSON)"),
    on_conflict: Optional[str] = Query(None, description="Conflict column: 'doi' or 'pmid'. Auto if omitted."),
    _=Depends(auth),
):
    """
    Upsert ONE study into public.studies. Respects your check constraint (needs doi or pmid).
    Auto-maps legacy 'design' -> 'study_design'.
    """
    sb = get_client()

    # legacy mapping
    if "design" in study and "study_design" not in study:
        study["study_design"] = study.pop("design")

    # decide conflict column
    conflict_col = on_conflict
    if not conflict_col:
        if study.get("doi"):
            conflict_col = "doi"
        elif study.get("pmid"):
            conflict_col = "pmid"
        else:
            raise HTTPException(status_code=400, detail="Upsert requires at least doi or pmid.")

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
        raise HTTPException(status_code=400, detail=detail)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

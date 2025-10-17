from fastapi import FastAPI, HTTPException, Header, Depends, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client, Client
from postgrest import APIError
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv
from pydantic import BaseModel
import os

# ------------------ ENV ------------------
load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_ANON_KEY")
SERVER_API_KEY = os.getenv("API_KEY")

app = FastAPI(title="Research API", version="1.0.0")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------ Auth ------------------
def auth(x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
    if SERVER_API_KEY and x_api_key != SERVER_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return True

# ------------------ Supabase Client ------------------
def get_client() -> Client:
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise HTTPException(status_code=500, detail="Missing Supabase environment variables")
    return create_client(SUPABASE_URL, SUPABASE_KEY)

# ------------------ Models ------------------
class Intervention(BaseModel):
    name: Optional[str]
    dose: Optional[str]
    route: Optional[str]
    schedule: Optional[str]

class Study(BaseModel):
    doi: Optional[str]
    pmid: Optional[str]
    year: Optional[int]
    study_design: Optional[str]
    n_participants: Optional[int]
    title: str
    journal: Optional[str]
    abstract: Optional[str]
    population: Optional[str]
    comparison_group: Optional[str]
    duration_weeks: Optional[int]
    author: Optional[str]
    core_claim: Optional[str]
    evidence_grade: Optional[str]
    source_url: Optional[str]
    outcomes: List[str]
    tags: List[str]
    intervention: Optional[Intervention]

class Effect(BaseModel):
    outcome_name: str
    endpoint_level: Optional[str]
    effect_metric: str
    effect_value: float
    ci_low: Optional[float]
    ci_high: Optional[float]
    p_value: Optional[float]
    unit: Optional[str]
    direction: Optional[str]
    timepoint_weeks: Optional[int]
    adjusted: Optional[bool]
    notes: Optional[str]

class StudyBundle(BaseModel):
    study: Study
    effects: List[Effect] = []

# ------------------ Routes ------------------
@app.get("/health")
def health():
    return {
        "ok": True,
        "has_SUPABASE_URL": bool(SUPABASE_URL),
        "has_SUPABASE_ANON_KEY": bool(SUPABASE_KEY),
        "requires_api_key": bool(SERVER_API_KEY),
        "version": "1.0.0"
    }

@app.post("/studies")
def insert_study_bundle(bundle: StudyBundle, _=Depends(auth)):
    sb = get_client()
    study_data = bundle.study.dict()
    effects_data = [e.dict() for e in bundle.effects]

    conflict_col = None
    if study_data.get("doi"):
        conflict_col = "doi"
    elif study_data.get("pmid"):
        conflict_col = "pmid"
    else:
        raise HTTPException(status_code=400, detail="Study must have either doi or pmid for upsert.")

    try:
        study_res = sb.table("studies").upsert(
            study_data,
            on_conflict=conflict_col,
            returning="representation"
        ).execute()

        inserted_study = study_res.data[0]
        doi = inserted_study.get("doi")
        if not doi:
            raise HTTPException(status_code=500, detail="Inserted study has no DOI — required for linking.")

        for effect in effects_data:
            effect["doi"] = doi
        if effects_data:
            sb.table("study_effects").insert(effects_data).execute()

        return {
            "success": True,
            "inserted_study": inserted_study,
            "inserted_effects_count": len(effects_data)
        }

    except APIError as e:
        raise HTTPException(status_code=400, detail=e.args[0] if e.args else "Supabase error")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

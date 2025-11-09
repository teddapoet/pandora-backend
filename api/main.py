from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from uuid import uuid4 # randomly generated session id
from datetime import datetime

app = FastAPI(
    title="Handora Games API",
    description="API for Handora Games",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

# Pydantic models for checking and validation
class SessionStartResponse(BaseModel):
    session_id: str
    started_at: datetime


class WarmupPayload(BaseModel):
    warmup_max_flex: float = Field(gt=0, description="Max flex angle measured during warmup (degrees)")


class EventPayload(BaseModel):
    timestamp_ms: int # time when the event happened in milliseconds
    # tile_id: Optional[str] 
    hit: bool # hit or miss
    flex_angle: float # that was measured when pressing the tile


class FinishResponse(BaseModel):
    session_id: str
    baseline: float
    total_events: int   # can count miss rate 
    counted_hits: int
    score: int
    finished_at: datetime


class SessionDetail(BaseModel):
    session_id: str
    started_at: datetime
    finished_at: Optional[datetime]
    baseline: Optional[float]
    score: Optional[int]
    total_events: int


# In-memory, will replace alter
SESSIONS: Dict[str, Dict[str, Any]] = {}


@app.get("/")
def healthcheck() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/sessions/start", response_model=SessionStartResponse)
def start_session() -> SessionStartResponse:
    session_id = str(uuid4())
    now = datetime.utcnow()
    SESSIONS[session_id] = {
        "started_at": now,
        "finished_at": None,
        "baseline": None,
        "events": [],  # type: List[EventPayload]
        "score": None,
    }
    return SessionStartResponse(session_id=session_id, started_at=now)


@app.post("/api/v1/sessions/{session_id}/warmup")
def set_warmup_baseline(session_id: str, payload: WarmupPayload) -> Dict[str, float]:
    session = SESSIONS.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session is not found in our database")
    session["baseline"] = payload.warmup_max_flex
    return {"baseline": payload.warmup_max_flex}


@app.post("/api/v1/sessions/{session_id}/events")
def record_event(session_id: str, payload: EventPayload) -> Dict[str, int]:
    session = SESSIONS.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    session["events"].append(payload.model_dump())
    return {"total_events": len(session["events"])}


# Return the score and other details when the session is finished (summary)
@app.post("/api/v1/sessions/{session_id}/finish", response_model=FinishResponse)
def finish_session(session_id: str) -> FinishResponse:
    session = SESSIONS.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    baseline = session.get("baseline")
    if baseline is None:
        raise HTTPException(status_code=400, detail="Baseline not set. Run warmup first.")
    # lists of events, a list of dictionaries, return empty list by default
    events: List[Dict[str, Any]] = session.get("events", []) 
    counted_hits = sum(
        1 for e in events
        if bool(e.get("hit")) and float(e.get("flex_angle", 0.0)) >= float(baseline)
    )
    score = counted_hits

    finished_at = datetime.utcnow()
    session["finished_at"] = finished_at
    session["score"] = score

    return FinishResponse(
        session_id=session_id,
        baseline=float(baseline),
        total_events=len(events),
        counted_hits=counted_hits,
        score=score,
        finished_at=finished_at,
    )


@app.get("/api/v1/sessions/{session_id}", response_model=SessionDetail)
def get_session(session_id: str) -> SessionDetail:
    session = SESSIONS.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionDetail(
        session_id=session_id,
        started_at=session["started_at"],
        finished_at=session["finished_at"],
        baseline=session["baseline"],
        score=session["score"],
        total_events=len(session["events"]),
    )
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from uuid import uuid4 # randomly generated session id
from datetime import datetime
from enum import Enum
from dotenv import load_dotenv
import os
from fastapi import status
from supabase import create_client, Client

load_dotenv()

app = FastAPI(
    title="Handora Games API",
    description="API for Handora Games",
)

# Initialize Supabase client (prefer service role key on server)
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
supabase: Optional[Client] = None
if SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    except Exception as e:
        print("Supabase client init error:", e)
        supabase = None

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

class Finger(str, Enum):
    thumb = "thumb"
    index = "index"
    middle = "middle"
    ring = "ring"   
    pinky = "pinky"
    
class GameKey(str, Enum):
    piano_tiles = "piano_tiles"
    space_invader = "space_invader"
    dinosaur = "dinosaur"

# Pydantic models for checking and validation (minimal)
class SessionStartResponse(BaseModel):
    session_id: str

class SessionStartPayload(BaseModel):
    game_key: GameKey

class WarmupPayload(BaseModel):
    baseline_by_finger: Optional[Dict[str, float]] = Field(
        default=None,
        description="Per-finger baseline flex (degrees). Keys like 'thumb','index','middle','ring','pinky'.",
    )

# Event payload for recording events, fits for all games
class EventPayload(BaseModel):
    # General (optional across games)
    timestamp_ms: Optional[int] = None
    accuracy: Optional[float] = None
    rom_percent: Optional[float] = None
    # Piano tiles
    hit: Optional[bool] = None
    flex_angle: Optional[float] = None
    # Dinosaur
    reaction_time: Optional[int] = None
    smoothness: Optional[float] = None

class FinishPayload(EventPayload):
    score: int

class SessionDetail(BaseModel):
    score: Optional[int] = None
    baseline_by_finger: Optional[Dict[str, float]] = None
    game_key: Optional[GameKey] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

# In-memory, will replace later with supabase postgresql
SESSIONS: Dict[str, Dict[str, Any]] = {}


@app.get("/")
def healthcheck() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/sessions/start", response_model=SessionStartResponse)
def start_session(payload: SessionStartPayload) -> SessionStartResponse:
    session_id = str(uuid4())
    now = datetime.utcnow()
    SESSIONS[session_id] = {
        "started_at": now,
        "finished_at": None,
        "game_key": payload.game_key,
        "baseline_by_finger": None,
        "events": [],  # type: List[EventPayload]
        "score": None,
        "metrics": None,
    }
    # Persist to Supabase (best-effort)
    if supabase:
        try:
            supabase.table("sessions").insert({
                "id": session_id,
                "game_key": payload.game_key.value,
                "started_at": now.isoformat(),
                "score": 0,
                "baseline_by_finger": SESSIONS[session_id]["baseline_by_finger"] or {},
                "metrics": SESSIONS[session_id]["metrics"] or {},
            }).execute()
        except Exception as e:
            print("Supabase insert error (start_session):", e)
    return SessionStartResponse(session_id=session_id)


@app.post("/api/v1/sessions/{session_id}/warmup")
def set_warmup_baseline(session_id: str, payload: WarmupPayload) -> Dict[str, Dict[str, float]]:
    session = SESSIONS.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session is not found in our database")
    if payload.baseline_by_finger is not None:
        session["baseline_by_finger"] = payload.baseline_by_finger
        if supabase:
            try:
                supabase.table("sessions") \
                    .update({"baseline_by_finger": payload.baseline_by_finger}) \
                    .eq("id", session_id).execute()
            except Exception as e:
                print("Supabase update error (warmup):", e)
    return {"baseline_by_finger": session.get("baseline_by_finger") or {}}


@app.post("/api/v1/sessions/{session_id}/events")
def record_event(session_id: str, payload: EventPayload) -> Dict[str, int]:
    session = SESSIONS.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    session["events"].append(payload.model_dump())
    return {"total_events": len(session["events"])}


@app.post("/api/v1/sessions/{session_id}/finish", response_model=EventPayload)
def finish_session(session_id: str, payload: FinishPayload) -> EventPayload:
    session = SESSIONS.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    finished_at = datetime.utcnow()
    session["finished_at"] = finished_at
    session["score"] = payload.score
    # Extract only event-style traits from payload to store as metrics
    trait_keys = EventPayload.model_fields.keys()
    metrics: Dict[str, Any] = {
        k: v for k, v in payload.model_dump(exclude_none=True).items() if k in trait_keys
    }
    session["metrics"] = metrics
    if supabase:
        try:
            supabase.table("sessions") \
                .update({
                    "finished_at": finished_at.isoformat(),
                    "score": payload.score,
                    "metrics": metrics,
                }).eq("id", session_id).execute()
        except Exception as e:
            print("Supabase update error (finish):", e)

    return EventPayload(**metrics)


@app.get("/api/v1/sessions/{session_id}", response_model=SessionDetail)
def get_session(session_id: str) -> SessionDetail:
    # Prefer DB if available; fall back to in-memory
    if supabase:
        try:
            res = supabase.table("sessions").select("*").eq("id", session_id).single().execute()
            row = getattr(res, "data", None) or None
            if row:
                return SessionDetail(
                    baseline_by_finger=row.get("baseline_by_finger"),
                    score=row.get("score"),
                    game_key=row.get("game_key"),
                    started_at=row.get("started_at"),
                    finished_at=row.get("finished_at"),
                )
        except Exception as e:
            print("Supabase select error (get_session):", e)
    session = SESSIONS.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionDetail(
        baseline_by_finger=session.get("baseline_by_finger"),
        score=session.get("score"),
        game_key=session.get("game_key"),
        started_at=session.get("started_at"),
        finished_at=session.get("finished_at"),
    )


@app.get("/api/v1/analytics/highscores")
def get_highscores() -> Dict[str, int]:
    """
    Returns highest score per game as keys "1", "2", "3":
      "1" => piano_tiles
      "2" => space_invader
      "3" => dinosaur
    """
    max_by_game: Dict[GameKey, Optional[int]] = {
        GameKey.piano_tiles: None,
        GameKey.space_invader: None,
        GameKey.dinosaur: None,
    }
    for _sid, sess in SESSIONS.items():
        score = sess.get("score")
        game_key = sess.get("game_key")
        if score is None or game_key not in max_by_game:
            continue
        current = max_by_game[game_key]
        if current is None or score > current:
            max_by_game[game_key] = score

    return {
        "1": max_by_game[GameKey.piano_tiles] or 0,
        "2": max_by_game[GameKey.space_invader] or 0,
        "3": max_by_game[GameKey.dinosaur] or 0,
    }
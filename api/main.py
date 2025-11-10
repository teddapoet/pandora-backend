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
from google import genai
import json

load_dotenv()

app = FastAPI(
    title="Handora Games API",
    description="API for Handora Games",
)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
gemini_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])  
GEMINI_MODEL_ID = "gemini-2.5-flash"

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

class LLMAnalysisRequest(BaseModel):
    prompt: str
    metrics: Optional[Dict[str, Any]] = None

class LLMResp(BaseModel):
    analysis: str

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


@app.get("/api/v1/sessions/{session_id}/with-history")
def get_session_with_history(session_id: str) -> Dict[str, Any]:
    """Returns current session + previous sessions of the same game."""
    current = None
    history = []
    
    # Get current session
    if supabase:
        try:
            res = supabase.table("sessions").select("*").eq("id", session_id).single().execute()
            row = getattr(res, "data", None)
            if row:
                current = row
                game_key = row.get("game_key")
                # Get previous sessions of same game
                hist_res = supabase.table("sessions") \
                    .select("*") \
                    .eq("game_key", game_key) \
                    .neq("id", session_id) \
                    .order("started_at", desc=False) \
                    .limit(10) \
                    .execute()
                history = getattr(hist_res, "data", None) or []
        except Exception as e:
            print("Supabase error (get_session_with_history):", e)
    
    # Fallback to in-memory
    if not current:
        sess = SESSIONS.get(session_id)
        if not sess:
            raise HTTPException(status_code=404, detail="Session not found")
        current = {
            "id": session_id,
            "game_key": sess.get("game_key"),
            "score": sess.get("score"),
            "baseline_by_finger": sess.get("baseline_by_finger"),
            "metrics": sess.get("metrics"),
            "started_at": sess.get("started_at").isoformat() if sess.get("started_at") else None,
            "finished_at": sess.get("finished_at").isoformat() if sess.get("finished_at") else None,
        }
        game_key = sess.get("game_key")
        for sid, s in SESSIONS.items():
            if sid != session_id and s.get("game_key") == game_key:
                history.append({
                    "id": sid,
                    "score": s.get("score"),
                    "started_at": s.get("started_at").isoformat() if s.get("started_at") else None,
                })
    
    return {"current": current, "history": history}


@app.get("/api/v1/sessions")
def get_all_sessions() -> List[SessionDetail]:
    """Returns all sessions from DB (or in-memory fallback)."""
    sessions_list = []
    # Try Supabase first
    if supabase:
        try:
            res = supabase.table("sessions").select("*").order("started_at", desc=True).limit(50).execute()
            rows = getattr(res, "data", None) or []
            for row in rows:
                sessions_list.append(SessionDetail(
                    baseline_by_finger=row.get("baseline_by_finger"),
                    score=row.get("score"),
                    game_key=row.get("game_key"),
                    started_at=row.get("started_at"),
                    finished_at=row.get("finished_at"),
                ))
        except Exception as e:
            print("Supabase select error (get_all_sessions):", e)
    # Fallback to in-memory
    if not sessions_list:
        for sid, sess in SESSIONS.items():
            sessions_list.append(SessionDetail(
                baseline_by_finger=sess.get("baseline_by_finger"),
                score=sess.get("score"),
                game_key=sess.get("game_key"),
                started_at=sess.get("started_at"),
                finished_at=sess.get("finished_at"),
            ))
    return sessions_list


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
    # Try Supabase first
    if supabase:
        try:
            res = supabase.table("sessions").select("game_key,score").execute()
            rows = getattr(res, "data", None) or []
            for row in rows:
                gk = row.get("game_key")
                sc = row.get("score")
                if sc is not None and gk in [e.value for e in GameKey]:
                    game_enum = GameKey(gk)
                    if game_enum in max_by_game:
                        if max_by_game[game_enum] is None or sc > max_by_game[game_enum]:
                            max_by_game[game_enum] = sc
        except Exception as e:
            print("Supabase select error (get_highscores):", e)
    # Fallback to in-memory
    if all(v is None for v in max_by_game.values()):
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

@app.post("/api/v1/analytics/analyze", response_model=LLMResp)
def analyze_metrics(payload: LLMAnalysisRequest) -> LLMResp:
    if not gemini_client:
        raise HTTPException(status_code=503, detail="Gemini not configured")

    system_prompt = (
        "You are a rehab game assistant named Dora. Analyze the provided single-session metrics "
        "for a player's hand usage. Avoid medical diagnosis as you are not really a doctor; use neutral language "
        "like 'may indicate' or 'appears'. Focus on accuracy, rom_percent, flex_angle, "
        "reaction_time, smoothness, baseline_by_finger, and score if present. Provide 3–5 sentences plus 1–2 "
        "actionable tips. Keep it concise and encouraging."
    )

    metrics_json = json.dumps(payload.metrics or {})
    user_message = f"{payload.prompt}\n\nMETRICS_JSON:\n{metrics_json}"

    try:
        resp = gemini_client.models.generate_content(
            model=GEMINI_MODEL_ID,
            contents=f"{system_prompt}\n\n{user_message}"
        )
        return LLMResp(analysis=(resp.text or "").strip())
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gemini error: {e}")

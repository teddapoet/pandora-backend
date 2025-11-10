# Handora Backend API

Backend API for Handora - a rehabilitation gaming platform that uses hand gesture tracking for physical therapy games.

## Features

- 🎮 **Game Session Management**: Track multiple game types (Piano Tiles, Space Invaders, Dinosaur)
- 📊 **Metrics Tracking**: Record accuracy, ROM (Range of Motion), reaction time, and smoothness
- 🤖 **AI-Powered Analytics**: Google Gemini integration for personalized rehabilitation insights
- 🗄️ **Supabase Database**: Persistent storage for sessions and progress tracking
- 🔄 **Real-time Events**: Record gameplay events for detailed performance analysis

## Tech Stack

- **FastAPI**: Modern, fast web framework for building APIs
- **Supabase**: PostgreSQL database with real-time capabilities
- **Google Gemini AI**: AI-powered session analysis and recommendations
- **Pydantic**: Data validation using Python type hints
- **Uvicorn**: ASGI server for production deployment

## Prerequisites

- Python 3.8+
- Supabase account and project
- Google Gemini API key

## Installation

1. **Clone the repository**
   ```bash
   cd backend
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up environment variables**
   
   Create a `.env` file in the `backend` directory:
   ```env
   # Supabase Configuration
   SUPABASE_URL=your_supabase_project_url
   SUPABASE_SERVICE_ROLE_KEY=your_supabase_service_role_key
   
   # Google Gemini AI
   GEMINI_API_KEY=your_gemini_api_key
   ```

## Running the Server

### Development
```bash
uvicorn api.main:app --reload --port 8000
```

### Production
```bash
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8000`

## API Documentation

Once the server is running, visit:
- **Interactive Docs**: `http://localhost:8000/docs` (Swagger UI)
- **Alternative Docs**: `http://localhost:8000/redoc` (ReDoc)

## API Endpoints

### Health Check
```
GET /
```
Returns server status.

### Session Management

#### Start Session
```
POST /api/v1/sessions/start
```
**Body:**
```json
{
  "game_key": "piano_tiles" // or "space_invader", "dinosaur"
}
```
**Response:**
```json
{
  "session_id": "uuid-string"
}
```

#### Set Warmup Baseline
```
POST /api/v1/sessions/{session_id}/warmup
```
**Body:**
```json
{
  "baseline_by_finger": {
    "thumb": 45.0,
    "index": 50.0,
    "middle": 55.0,
    "ring": 48.0,
    "pinky": 42.0
  }
}
```

#### Record Event
```
POST /api/v1/sessions/{session_id}/events
```
**Body:**
```json
{
  "timestamp_ms": 1234567890,
  "hit": true,
  "flex_angle": 45.5,
  "accuracy": 0.95,
  "rom_percent": 0.85
}
```

#### Finish Session
```
POST /api/v1/sessions/{session_id}/finish
```
**Body:**
```json
{
  "score": 150,
  "accuracy": 0.92,
  "rom_percent": 0.85,
  "reaction_time": 250,
  "smoothness": 0.88
}
```

#### Get Session
```
GET /api/v1/sessions/{session_id}
```
Returns session details including score, metrics, and baseline data.

#### Get Session with History
```
GET /api/v1/sessions/{session_id}/with-history
```
Returns current session plus previous sessions of the same game type.

#### Get All Sessions
```
GET /api/v1/sessions
```
Returns all sessions from the database.

### Analytics

#### AI Analysis
```
POST /api/v1/analytics/analyze
```
**Body:**
```json
{
  "prompt": "Analyze this rehab session...",
  "metrics": {
    "score": 150,
    "accuracy": 0.92,
    "rom_percent": 0.85,
    "baseline_by_finger": {
      "thumb": 45.0,
      "index": 50.0,
      "middle": 55.0,
      "ring": 48.0,
      "pinky": 42.0
    }
  }
}
```
**Response:**
```json
{
  "analysis": "Based on your performance, you showed excellent progress..."
}
```

## Data Models

### Game Types
- `piano_tiles`: Piano Tiles rhythm game
- `space_invader`: Space Invaders shooting game
- `dinosaur`: Dinosaur jump game

### Metrics
- **accuracy**: Hit/miss ratio (0.0 - 1.0)
- **rom_percent**: Range of motion utilization (0.0 - 1.0)
- **reaction_time**: Response time in milliseconds
- **smoothness**: Movement quality score (0.0 - 1.0)
- **baseline_by_finger**: Per-finger flex angle thresholds

## Database Schema

The backend expects a Supabase table named `sessions` with the following structure:

```sql
CREATE TABLE sessions (
  id UUID PRIMARY KEY,
  game_key TEXT NOT NULL,
  score INTEGER,
  accuracy FLOAT,
  baseline_by_finger JSONB,
  metrics JSONB,
  started_at TIMESTAMP,
  finished_at TIMESTAMP,
  created_at TIMESTAMP DEFAULT NOW()
);
```

## CORS Configuration

The API is configured to accept requests from:
- `http://localhost:3000` (Next.js frontend)

To add more origins, modify the `allow_origins` in `api/main.py`:
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "https://yourdomain.com"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)
```

## Error Handling

The API returns standard HTTP status codes:
- `200`: Success
- `404`: Resource not found
- `500`: Internal server error

## Development

### Project Structure
```
backend/
├── api/
│   └── main.py          # Main FastAPI application
├── requirements.txt      # Python dependencies
├── .env                 # Environment variables (not in git)
├── .gitignore
└── README.md
```

### Adding New Game Types

1. Add to `GameKey` enum in `main.py`:
```python
class GameKey(str, Enum):
    piano_tiles = "piano_tiles"
    your_new_game = "your_new_game"
```

2. Add game-specific metrics to `EventPayload` if needed

## Deployment

### Docker (Recommended)

Create a `Dockerfile`:
```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Build and run:
```bash
docker build -t handora-backend .
docker run -p 8000:8000 --env-file .env handora-backend
```

### Railway / Render / Vercel

Set environment variables in the platform dashboard and use:
```bash
uvicorn api.main:app --host 0.0.0.0 --port $PORT
```

## Contributing

1. Create a feature branch
2. Make your changes
3. Test thoroughly
4. Submit a pull request

## License

MIT License

## Support

For issues or questions, please open an issue on GitHub.


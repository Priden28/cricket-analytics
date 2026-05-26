import json
import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List

from config import ALLOWED_ORIGINS, MODEL_PATH

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from pydantic import BaseModel, Field

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)s  %(levelname)s  %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Service initialisation
# ---------------------------------------------------------------------------
cricket_service    = None
db_manager         = None
analytics_service  = None
predictor_service  = None   # ML prediction service


@asynccontextmanager
async def lifespan(app: FastAPI):
    global cricket_service, db_manager, analytics_service, predictor_service
    # Services are initialised lazily — we do NOT block startup on DB connection.
    # Cloud Run health checks pass immediately; DB connects on first real request.
    try:
        from cricket_service   import CricketService
        from database          import DatabaseManager
        from analytics_service import AnalyticsService
        from predictor_service import PredictorService

        # Import classes only — don't call DatabaseManager() here as it
        # tries to connect to DB and blocks startup in Cloud Run.
        db_manager        = DatabaseManager.__new__(DatabaseManager)
        cricket_service   = CricketService.__new__(CricketService)
        analytics_service = AnalyticsService.__new__(AnalyticsService)

        # Initialise in background thread so startup completes immediately
        import threading
        def _init():
            global cricket_service, db_manager, analytics_service, predictor_service
            try:
                db_manager.__init__()
                from cricket_service import CricketService as CS
                cricket_service = CS()
                from analytics_service import AnalyticsService as AS
                analytics_service = AS(db_manager)
                try:
                    predictor_service = PredictorService.from_pkl(MODEL_PATH)
                    logger.info("PredictorService loaded successfully")
                except FileNotFoundError:
                    logger.warning("pkl not found — prediction endpoints will return 503")
                logger.info("All services initialised successfully")
            except Exception as e:
                logger.error(f"Background service init failed: {e}")

        threading.Thread(target=_init, daemon=True).start()
        logger.info("Startup complete — services initialising in background")
    except Exception as e:
        logger.error(f"Service init failed: {e}")
    yield
    logger.info("Shutting down")


app = FastAPI(
    title="Cricket Analytics API",
    description="Test-cricket stats: scrape, store, analyse, predict.",
    version="3.0.0",
    lifespan=lifespan,
)

# Origins: wildcard covers all cases.
# Origins are loaded from ALLOWED_ORIGINS env var (see config.py / .env)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR  = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require(service, name: str):
    if service is None:
        raise HTTPException(
            status_code=503,
            detail=f"{name} is not available. Check startup logs.",
        )


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse, tags=["UI"])
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# ---------------------------------------------------------------------------
# Meta
# ---------------------------------------------------------------------------

@app.get("/health", tags=["Meta"])
def health():
    return {
        "status": "ok",
        "services": {
            "cricket_service":   cricket_service   is not None,
            "db_manager":        db_manager         is not None,
            "analytics_service": analytics_service  is not None,
            "predictor_service": predictor_service  is not None,
        },
    }


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------

def _run_scrape(dataset_type: str):
    """
    Blocking scrape — called from a brand-new thread each time so there is
    no asyncio event loop present, which is what Playwright's sync API requires.
    """
    return cricket_service.scrape_and_process(dataset_type)


@app.post("/scrape/{dataset_type}", tags=["Ingestion"])
async def scrape(dataset_type: str):
    """
    Scrape & ingest new data from ESPN Cricinfo.
    Spawns a fresh thread for every request — Playwright's sync API
    requires a thread with no asyncio loop, and reusing a thread pool
    thread can carry over loop state from previous requests.
    """
    _require(cricket_service, "CricketService")
    try:
        loop = asyncio.get_event_loop()
        # max_workers=1, fresh executor each call = guaranteed clean thread
        with ThreadPoolExecutor(max_workers=1) as executor:
            df = await loop.run_in_executor(executor, _run_scrape, dataset_type)
        return {"message": f"Scrape complete for '{dataset_type}'", "rows_processed": len(df)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"/scrape/{dataset_type}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Players (existing)
# ---------------------------------------------------------------------------

@app.get("/api/players", tags=["Players"])
def get_batting_players():
    _require(db_manager, "DatabaseManager")
    return db_manager.fetch_unique_batting_players()


@app.get("/api/bowling-players", tags=["Players"])
def get_bowling_players():
    _require(db_manager, "DatabaseManager")
    return db_manager.fetch_unique_bowling_players()


# ---------------------------------------------------------------------------
# Teams + Players by team  (new — for prediction UI)
# ---------------------------------------------------------------------------

@app.get("/api/teams", tags=["Prediction"])
def get_teams():
    """Return all team names that have players in the database."""
    _require(predictor_service, "PredictorService")
    return predictor_service.teams


@app.get("/api/team-players/{team}", tags=["Prediction"])
def get_team_players(team: str):
    """
    Return all player names associated with a team.
    Players appear here if they have any batting or bowling record for that team.
    """
    _require(predictor_service, "PredictorService")
    players = predictor_service.players_for_team(team)
    if not players:
        raise HTTPException(status_code=404, detail=f"No players found for team '{team}'")
    return players


# ---------------------------------------------------------------------------
# Match Prediction  (new)
# ---------------------------------------------------------------------------

class PredictionRequest(BaseModel):
    team:        str         = Field(..., description="Team A name (predicting for)")
    team_players: List[str]  = Field(..., min_length=11, max_length=11,
                                     description="Exactly 11 player names for Team A")
    opposition:  str         = Field(..., description="Team B name")
    opp_players: List[str]   = Field(..., min_length=11, max_length=11,
                                     description="Exactly 11 player names for Team B")
    venue_type:  str         = Field("neutral",
                                     description="'home' | 'away' | 'neutral'  (from team's perspective)")


@app.post("/predict/match", tags=["Prediction"])
def predict_match(req: PredictionRequest):
    """
    Predict the outcome of a Test match given two Playing XIs and the venue.

    `venue_type` is always from **team**'s perspective:
      - `home`    → match is at team's home ground
      - `away`    → match is at opposition's home ground
      - `neutral` → neutral venue
    """
    _require(predictor_service, "PredictorService")
    try:
        result = predictor_service.predict(
            team=req.team,
            team_players=req.team_players,
            opposition=req.opposition,
            opp_players=req.opp_players,
            venue_type=req.venue_type,
        )
        return JSONResponse(content=result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"/predict/match error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/predict/model-info", tags=["Prediction"])
def model_info():
    """Return model accuracy and top feature importances."""
    _require(predictor_service, "PredictorService")
    return predictor_service.model_info()


# ---------------------------------------------------------------------------
# Plots (existing)
# ---------------------------------------------------------------------------

@app.get("/plot/batting", tags=["Plots"])
def batting_plot(player: str = Query(...)):
    _require(analytics_service, "AnalyticsService")
    result = analytics_service.generate_player_batting_average_plot(player)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No batting data for '{player}'")
    return JSONResponse(content=json.loads(result))


@app.get("/plot/bowling", tags=["Plots"])
def bowling_plot(player: str = Query(...)):
    _require(analytics_service, "AnalyticsService")
    result = analytics_service.generate_player_bowling_average_plot(player)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No bowling data for '{player}'")
    return JSONResponse(content=json.loads(result))


# ---------------------------------------------------------------------------
# Analysis (existing)
# ---------------------------------------------------------------------------

@app.get("/analysis/batsman-vs-bowler", tags=["Analysis"])
def batsman_vs_bowler(batsman: str = Query(...), bowler: str = Query(None)):
    _require(analytics_service, "AnalyticsService")
    result = analytics_service.analyze_batsman_vs_bowler(batsman, bowler)
    if result is None:
        raise HTTPException(status_code=500, detail="Analysis failed")
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@app.get("/analysis/batting-outcomes", tags=["Analysis"])
def batting_outcomes(player: str = Query(...), min_score: int = Query(..., ge=0)):
    _require(analytics_service, "AnalyticsService")
    result = analytics_service.analyze_batting_match_outcomes(player, min_score)
    if result is None:
        raise HTTPException(status_code=500, detail="Analysis failed")
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@app.get("/analysis/bowling-outcomes", tags=["Analysis"])
def bowling_outcomes(player: str = Query(...), min_wickets: int = Query(..., ge=0)):
    _require(analytics_service, "AnalyticsService")
    result = analytics_service.analyze_bowling_match_outcomes(player, min_wickets)
    if result is None:
        raise HTTPException(status_code=500, detail="Analysis failed")
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@app.get("/analysis/batting-by-country", tags=["Analysis"])
def batting_by_country(player: str = Query(...)):
    _require(analytics_service, "AnalyticsService")
    result = analytics_service.analyze_batting_by_country(player)
    if result is None:
        raise HTTPException(status_code=500, detail="Analysis failed")
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@app.get("/analysis/bowling-by-country", tags=["Analysis"])
def bowling_by_country(player: str = Query(...)):
    _require(analytics_service, "AnalyticsService")
    result = analytics_service.analyze_bowling_by_country(player)
    if result is None:
        raise HTTPException(status_code=500, detail="Analysis failed")
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result



@app.get("/plot/batting-comparison", tags=["Plots"])
def batting_comparison_plot(
    player1: str = Query(..., description="First player name"),
    player2: str = Query(..., description="Second player name"),
):
    """Yearly batting average comparison chart for two players (Plotly JSON)."""
    _require(analytics_service, "AnalyticsService")
    result = analytics_service.generate_batting_comparison_plot(player1, player2)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No data found for '{player1}' or '{player2}'")
    return JSONResponse(content=json.loads(result))


@app.get("/plot/bowling-comparison", tags=["Plots"])
def bowling_comparison_plot(
    player1: str = Query(..., description="First player name"),
    player2: str = Query(..., description="Second player name"),
):
    """Yearly bowling average comparison chart for two players (Plotly JSON)."""
    _require(analytics_service, "AnalyticsService")
    result = analytics_service.generate_bowling_comparison_plot(player1, player2)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No data found for '{player1}' or '{player2}'")
    return JSONResponse(content=json.loads(result))


@app.get("/plot/team-batting", tags=["Plots"])
def team_batting_plot():
    """Team batting averages bar chart (Plotly JSON)."""
    _require(analytics_service, "AnalyticsService")
    result = analytics_service.generate_team_batting_average_plot()
    if result is None:
        raise HTTPException(status_code=500, detail="Failed to generate team batting chart")
    return JSONResponse(content=json.loads(result))

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

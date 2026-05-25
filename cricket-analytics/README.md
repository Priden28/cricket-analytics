# Cricket Analytics — React Frontend

A React rewrite of the original HTML interface. **Backend interactions are 100% identical** — same endpoints, same request/response shapes. Just point the FastAPI server at `http://localhost:8000` (as before) and the app talks to it untouched.

## Run

```bash
npm install
npm run dev
```

App opens at `http://localhost:5173`. The FastAPI backend must be running on `http://localhost:8000`.

## What changed (UI only)

- **Editorial sports-magazine aesthetic** — willow-green + cream + ember-red palette, Fraunces display serif, Inter Tight body, JetBrains Mono for numbers.
- **Three tabs**: Analytics (six analysis tools), Prediction (XI builder + factor breakdown), Data (Cricinfo scrape).
- **Refined motion** — staggered fade-ins, animated probability bars, hover states throughout.
- **Plotly figures** automatically re-themed to match the dark palette.

## Backend endpoints used (unchanged)

```
GET  /api/players
GET  /api/bowling-players
GET  /api/teams
GET  /api/team-players/{team}

GET  /plot/batting?player=
GET  /plot/bowling?player=

GET  /analysis/batsman-vs-bowler?batsman=&bowler=
GET  /analysis/batting-outcomes?player=&min_score=
GET  /analysis/bowling-outcomes?player=&min_wickets=
GET  /analysis/batting-by-country?player=
GET  /analysis/bowling-by-country?player=

POST /predict/match
POST /scrape/batting | /scrape/bowling | /scrape/team
```

## CORS reminder

Your FastAPI server needs CORS enabled for `http://localhost:5173`:

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
```

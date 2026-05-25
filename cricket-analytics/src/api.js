// API base URL — set VITE_API_URL in .env for local dev,
// or in the Vite build environment for production.
const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'

async function json(url, opts) {
  const res = await fetch(url, opts)
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    throw new Error(data.detail || `Request failed: ${res.status}`)
  }
  return data
}

export const api = {
  // Dropdowns
  getBattingPlayers:  () => json(`${API}/api/players`),
  getBowlingPlayers:  () => json(`${API}/api/bowling-players`),
  getTeams:           () => json(`${API}/api/teams`),
  getTeamPlayers:     (team) => json(`${API}/api/team-players/${encodeURIComponent(team)}`),

  // Plots (return Plotly figure JSON)
  plotBatting: (player) => json(`${API}/plot/batting?player=${encodeURIComponent(player)}`),
  plotBowling: (player) => json(`${API}/plot/bowling?player=${encodeURIComponent(player)}`),
  plotBattingComparison: (p1, p2) =>
    json(`${API}/plot/batting-comparison?player1=${encodeURIComponent(p1)}&player2=${encodeURIComponent(p2)}`),
  plotBowlingComparison: (p1, p2) =>
    json(`${API}/plot/bowling-comparison?player1=${encodeURIComponent(p1)}&player2=${encodeURIComponent(p2)}`),
  plotTeamBatting: () => json(`${API}/plot/team-batting`),

  // Analysis
  batsmanVsBowler: (batsman, bowler) => {
    const url = bowler
      ? `${API}/analysis/batsman-vs-bowler?batsman=${encodeURIComponent(batsman)}&bowler=${encodeURIComponent(bowler)}`
      : `${API}/analysis/batsman-vs-bowler?batsman=${encodeURIComponent(batsman)}`
    return json(url)
  },
  battingOutcomes: (player, minScore) =>
    json(`${API}/analysis/batting-outcomes?player=${encodeURIComponent(player)}&min_score=${minScore}`),
  bowlingOutcomes: (player, minWickets) =>
    json(`${API}/analysis/bowling-outcomes?player=${encodeURIComponent(player)}&min_wickets=${minWickets}`),
  battingByCountry: (player) =>
    json(`${API}/analysis/batting-by-country?player=${encodeURIComponent(player)}`),
  bowlingByCountry: (player) =>
    json(`${API}/analysis/bowling-by-country?player=${encodeURIComponent(player)}`),

  // Prediction
  predictMatch: (payload) => json(`${API}/predict/match`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }),

  // Scrape
  scrape: (type) => json(`${API}/scrape/${type}`, { method: 'POST' }),
}

import React, { useEffect, useState } from 'react'
import Plot from 'react-plotly.js'
import { api } from '../api'
import { ErrorBanner, LoadingPanel, PercentageBar, SectionHeader } from './ui'

export function AnalyticsTab() {
  const [battingPlayers, setBattingPlayers] = useState([])
  const [bowlingPlayers, setBowlingPlayers] = useState([])

  useEffect(() => {
    api.getBattingPlayers().then(setBattingPlayers).catch(() => { })
    api.getBowlingPlayers().then(setBowlingPlayers).catch(() => { })
  }, [])

  return (
    <div className="space-y-8">
      <SectionHeader
        eyebrow="01 — Player Insights"
        title="Pick a player, read the story."
        description="Nine lenses on Test cricket: batting form, bowling form, head-to-head match-ups, impact on results, comparisons, and country-by-country breakdowns. Each tool shows its result right where you ran it."
      />

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        <BattingCard players={battingPlayers} />
        <BowlingCard players={bowlingPlayers} />
        <ComparisonCard batsmen={battingPlayers} bowlers={bowlingPlayers} />
        <BattingImpactCard players={battingPlayers} />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <BattingComparisonCard players={battingPlayers} />
        <BowlingComparisonCard players={bowlingPlayers} />
        <TeamBattingCard />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <BowlingImpactCard players={bowlingPlayers} />
        <BattingCountryCard players={battingPlayers} />
        <BowlingCountryCard players={bowlingPlayers} />
      </div>
    </div>
  )
}

// ─────────────────────────── HOOK: per-card state ────────────────────────────

function useCardState() {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [data, setData] = useState(null)

  async function run(fn) {
    setLoading(true); setError(null); setData(null)
    try {
      const result = await fn()
      setData(result)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  function clear() { setData(null); setError(null) }

  return { loading, error, data, run, clear }
}

// ─────────────────────────── BASE CARD WRAPPER ────────────────────────────

function ToolCard({ title, accent, children }) {
  const accentBar = {
    willow: 'before:bg-willow-500',
    cream: 'before:bg-cream-300',
    ember: 'before:bg-ember-500',
  }[accent || 'willow']
  return (
    <div className={`panel p-5 relative overflow-hidden flex flex-col
                     before:absolute before:left-0 before:top-0 before:bottom-0 before:w-[3px] ${accentBar}`}>
      <h3 className="font-display text-xl text-cream-50 mb-4 leading-tight">{title}</h3>
      <div className="space-y-3 flex flex-col flex-1">{children}</div>
    </div>
  )
}

function PlayerSelect({ value, onChange, players, placeholder }) {
  return (
    <select className="form-input" value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">{placeholder}</option>
      {players.map((p) => <option key={p} value={p}>{p}</option>)}
    </select>
  )
}

// Inline result zone that appears *inside the card itself*
function CardResult({ loading, error, data, render, onClear }) {
  if (!loading && !error && !data) return null
  return (
    <div className="mt-4 pt-4 border-t border-ink-700/60 anim-fade-in-up">
      {loading && (
        <div className="flex items-center justify-center py-6">
          <div className="anim-spin rounded-full border-2 border-willow-500/20 border-t-willow-400 w-6 h-6" />
        </div>
      )}
      {!loading && error && <ErrorBanner message={error} />}
      {!loading && !error && data && (
        <>
          <div className="flex justify-end mb-2">
            <button onClick={onClear} className="text-[11px] text-cream-300/40 hover:text-cream-200 transition-colors">
              Clear result
            </button>
          </div>
          {render(data)}
        </>
      )}
    </div>
  )
}

// ─────────────────────────── CARDS ────────────────────────────

function BattingCard({ players }) {
  const [p, setP] = useState('')
  const s = useCardState()
  return (
    <ToolCard title="Batting trajectory" accent="willow">
      <PlayerSelect value={p} onChange={setP} players={players} placeholder="Select a batting player" />
      <button
        disabled={!p}
        onClick={() => s.run(() => api.plotBatting(p))}
        className="btn-primary w-full disabled:opacity-40 disabled:cursor-not-allowed">
        Generate plot
      </button>
      <CardResult {...s} onClear={s.clear} render={(d) => <PlotResult data={d} compact />} />
    </ToolCard>
  )
}

function BowlingCard({ players }) {
  const [p, setP] = useState('')
  const s = useCardState()
  return (
    <ToolCard title="Bowling trajectory" accent="willow">
      <PlayerSelect value={p} onChange={setP} players={players} placeholder="Select a bowling player" />
      <button
        disabled={!p}
        onClick={() => s.run(() => api.plotBowling(p))}
        className="btn-primary w-full disabled:opacity-40 disabled:cursor-not-allowed">
        Generate plot
      </button>
      <CardResult {...s} onClear={s.clear} render={(d) => <PlotResult data={d} compact />} />
    </ToolCard>
  )
}

function ComparisonCard({ batsmen, bowlers }) {
  const [bat, setBat] = useState('')
  const [bow, setBow] = useState('')
  const s = useCardState()
  return (
    <ToolCard title="Batsman vs bowler" accent="cream">
      <PlayerSelect value={bat} onChange={setBat} players={batsmen} placeholder="Select batsman" />
      <PlayerSelect value={bow} onChange={setBow} players={bowlers} placeholder="Select bowler (optional)" />
      <button
        disabled={!bat}
        onClick={() => s.run(() => api.batsmanVsBowler(bat, bow || null))}
        className="btn-accent w-full disabled:opacity-40 disabled:cursor-not-allowed">
        Compare
      </button>
      <CardResult {...s} onClear={s.clear} render={(d) => <VsResult d={d} />} />
    </ToolCard>
  )
}

function BattingImpactCard({ players }) {
  const [p, setP] = useState('')
  const [min, setMin] = useState('')
  const s = useCardState()
  return (
    <ToolCard title="Batting impact" accent="ember">
      <PlayerSelect value={p} onChange={setP} players={players} placeholder="Select a batting player" />
      <input
        type="number" min="0"
        value={min} onChange={(e) => setMin(e.target.value)}
        placeholder="Minimum score"
        className="form-input" />
      <button
        disabled={!p || min === ''}
        onClick={() => s.run(() => api.battingOutcomes(p, min))}
        className="btn-danger w-full disabled:opacity-40 disabled:cursor-not-allowed">
        Analyse impact
      </button>
      <CardResult {...s} onClear={s.clear} render={(d) => <OutcomeResult d={d} kind="batting" />} />
    </ToolCard>
  )
}

function BattingComparisonCard({ players }) {
  const [p1, setP1] = useState('')
  const [p2, setP2] = useState('')
  const s = useCardState()
  const invalid = !p1 || !p2 || p1 === p2
  return (
    <ToolCard title="Batting comparison" accent="cream">
      <p className="text-xs text-cream-300/50 -mt-1 mb-1">Yearly batting average for two players on one chart.</p>
      <PlayerSelect value={p1} onChange={setP1} players={players} placeholder="Player 1" />
      <PlayerSelect value={p2} onChange={setP2} players={players} placeholder="Player 2" />
      <button
        disabled={invalid}
        onClick={() => s.run(() => api.plotBattingComparison(p1, p2))}
        className="btn-accent w-full disabled:opacity-40 disabled:cursor-not-allowed">
        Compare batters
      </button>
      <CardResult {...s} onClear={s.clear} render={(d) => <PlotResult data={d} compact />} />
    </ToolCard>
  )
}

function BowlingComparisonCard({ players }) {
  const [p1, setP1] = useState('')
  const [p2, setP2] = useState('')
  const s = useCardState()
  const invalid = !p1 || !p2 || p1 === p2
  return (
    <ToolCard title="Bowling comparison" accent="cream">
      <p className="text-xs text-cream-300/50 -mt-1 mb-1">Yearly bowling average for two players on one chart.</p>
      <PlayerSelect value={p1} onChange={setP1} players={players} placeholder="Player 1" />
      <PlayerSelect value={p2} onChange={setP2} players={players} placeholder="Player 2" />
      <button
        disabled={invalid}
        onClick={() => s.run(() => api.plotBowlingComparison(p1, p2))}
        className="btn-accent w-full disabled:opacity-40 disabled:cursor-not-allowed">
        Compare bowlers
      </button>
      <CardResult {...s} onClear={s.clear} render={(d) => <PlotResult data={d} compact />} />
    </ToolCard>
  )
}

function TeamBattingCard() {
  const s = useCardState()
  return (
    <ToolCard title="Team batting averages" accent="willow">
      <p className="text-xs text-cream-300/50 -mt-1 mb-1">All-time batting average for every team in the database.</p>
      <div className="flex-1" />
      <button
        onClick={() => s.run(() => api.plotTeamBatting())}
        className="btn-primary w-full mt-auto">
        Show all teams
      </button>
      <CardResult {...s} onClear={s.clear} render={(d) => <PlotResult data={d} compact />} />
    </ToolCard>
  )
}

function BowlingImpactCard({ players }) {
  const [p, setP] = useState('')
  const [min, setMin] = useState('')
  const s = useCardState()
  return (
    <ToolCard title="Bowling impact" accent="ember">
      <PlayerSelect value={p} onChange={setP} players={players} placeholder="Select a bowling player" />
      <input
        type="number" min="0"
        value={min} onChange={(e) => setMin(e.target.value)}
        placeholder="Minimum wickets"
        className="form-input" />
      <button
        disabled={!p || min === ''}
        onClick={() => s.run(() => api.bowlingOutcomes(p, min))}
        className="btn-danger w-full disabled:opacity-40 disabled:cursor-not-allowed">
        Analyse impact
      </button>
      <CardResult {...s} onClear={s.clear} render={(d) => <OutcomeResult d={d} kind="bowling" />} />
    </ToolCard>
  )
}

function BattingCountryCard({ players }) {
  const [p, setP] = useState('')
  const s = useCardState()
  return (
    <ToolCard title="Batting by country" accent="willow">
      <PlayerSelect value={p} onChange={setP} players={players} placeholder="Select a batting player" />
      <button
        disabled={!p}
        onClick={() => s.run(() => api.battingByCountry(p))}
        className="btn-primary w-full disabled:opacity-40 disabled:cursor-not-allowed">
        Analyse by country
      </button>
      <CardResult {...s} onClear={s.clear} render={(d) => <CountryResult d={d} kind="batting" />} />
    </ToolCard>
  )
}

function BowlingCountryCard({ players }) {
  const [p, setP] = useState('')
  const s = useCardState()
  return (
    <ToolCard title="Bowling by country" accent="willow">
      <PlayerSelect value={p} onChange={setP} players={players} placeholder="Select a bowling player" />
      <button
        disabled={!p}
        onClick={() => s.run(() => api.bowlingByCountry(p))}
        className="btn-primary w-full disabled:opacity-40 disabled:cursor-not-allowed">
        Analyse by country
      </button>
      <CardResult {...s} onClear={s.clear} render={(d) => <CountryResult d={d} kind="bowling" />} />
    </ToolCard>
  )
}

// ─────────────────────────── RESULT RENDERERS ────────────────────────────

function PlotResult({ data, compact = false }) {
  const layout = {
    ...data.layout,
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: { family: 'Inter Tight, sans-serif', color: '#e8dcbb', size: compact ? 10 : 12 },
    xaxis: {
      ...(data.layout?.xaxis || {}),
      gridcolor: 'rgba(232,220,187,0.08)',
      zerolinecolor: 'rgba(232,220,187,0.2)',
      // Preserve tickangle from backend (keeps labels from overlapping x-axis)
      tickangle: data.layout?.xaxis?.tickangle ?? -45,
    },
    yaxis: {
      ...(data.layout?.yaxis || {}),
      gridcolor: 'rgba(232,220,187,0.08)',
      zerolinecolor: 'rgba(232,220,187,0.2)',
    },
    // Use backend margin if provided (gives room for angled x-axis labels),
    // otherwise fall back to sensible defaults
    margin: data.layout?.margin
      ? { ...data.layout.margin }
      : { l: 55, r: 24, t: 48, b: 100 },
    legend: { ...(data.layout?.legend || {}), font: { size: 10, color: '#e8dcbb' } },
    hoverlabel: {
      ...(data.layout?.hoverlabel || {}),
      bgcolor: 'rgba(20,26,18,0.95)',
      bordercolor: 'rgba(94,139,61,0.6)',
      font: { color: '#e8dcbb', size: 12 },
      namelength: -1,
    },
  }
  return (
    <div className="bg-ink-950/40 rounded-md p-2">
      <Plot
        data={data.data}
        layout={layout}
        style={{ width: '100%', height: compact ? '360px' : '520px' }}
        useResizeHandler
        config={{
          displaylogo: false,
          responsive: true,
          // Show toolbar on hover so user can zoom, pan, reset
          displayModeBar: 'hover',
          modeBarButtonsToRemove: ['sendDataToCloud', 'editInChartStudio', 'lasso2d', 'select2d'],
          toImageButtonOptions: { format: 'png', scale: 2 },
        }}
      />
    </div>
  )
}

function MiniStatBlock({ label, value, sub, color = 'willow' }) {
  const colorClass = {
    willow: 'border-willow-500',
    cream: 'border-cream-300',
    ember: 'border-ember-500',
  }[color]
  return (
    <div className={`p-3 bg-ink-800/60 rounded-md border-l-2 ${colorClass}`}>
      <div className="label-eyebrow mb-1">{label}</div>
      <div className="font-display text-2xl text-cream-50 tabular-nums tracking-tight font-medium leading-none">{value}</div>
      {sub && <div className="mt-1.5 text-[11px] text-cream-300/60 font-mono leading-tight">{sub}</div>}
    </div>
  )
}

function VsResult({ d }) {
  return (
    <div className="space-y-3">
      <div className="text-center pb-2">
        <div className="label-eyebrow mb-1">Head-to-head</div>
        <h3 className="font-display text-xl text-cream-50">{d.batsman}</h3>
        <p className="text-xs text-cream-200/60 mt-0.5">
          {d.batsman_team}
          {d.bowler && <> · vs <span className="text-cream-100">{d.bowler}</span> ({d.bowler_team})</>}
        </p>
      </div>

      {d.analysis_type === 'with_bowler' ? (
        <>
          <div className="grid grid-cols-1 gap-2">
            <MiniStatBlock label="Overall avg" value={d.overall_average} sub={`${d.total_runs_overall} runs · ${d.total_outs_overall} outs`} color="cream" />
            <MiniStatBlock label={`With ${d.bowler}`} value={d.average_with_bowler} sub={`${d.total_runs_with_bowler} runs · ${d.total_outs_with_bowler} outs`} color="willow" />
            <MiniStatBlock label={`Without ${d.bowler}`} value={d.average_without_bowler} sub={`${d.total_runs_without_bowler} runs · ${d.total_outs_without_bowler} outs`} color="ember" />
          </div>
          <div className="grid grid-cols-3 gap-2 pt-3 border-t border-ink-700/60 text-center">
            <MiniNumeric label={`vs ${d.bowler_team}`} value={d.total_matches_vs_opposition} />
            <MiniNumeric label="With" value={d.matches_with_bowler} color="willow" />
            <MiniNumeric label="Without" value={d.matches_without_bowler} color="ember" />
          </div>
        </>
      ) : (
        <div className="grid grid-cols-1 gap-2">
          <MiniStatBlock label="Overall batting avg" value={d.overall_average} sub={`${d.total_runs_overall} runs · ${d.total_outs_overall} outs`} color="cream" />
          <MiniStatBlock label="Total matches" value={d.total_matches_vs_opposition} sub="All opposition" color="willow" />
        </div>
      )}
    </div>
  )
}

function MiniNumeric({ label, value, color }) {
  const colorClass = color === 'willow' ? 'text-willow-300' : color === 'ember' ? 'text-ember-500' : 'text-cream-100'
  return (
    <div>
      <div className={`font-display text-xl tabular-nums ${colorClass}`}>{value}</div>
      <div className="label-eyebrow mt-0.5 text-[9px]">{label}</div>
    </div>
  )
}

function OutcomeResult({ d, kind }) {
  const minLabel = kind === 'batting' ? `Min score ${d.min_score}` : `Min wickets ${d.min_wickets}`
  return (
    <div className="space-y-3">
      <div className="text-center pb-1">
        <div className="label-eyebrow mb-1">{kind === 'batting' ? 'Batting impact' : 'Bowling impact'}</div>
        <h3 className="font-display text-lg text-cream-50">{d.player}</h3>
        <p className="text-[11px] text-cream-200/60 mt-0.5">{d.team} · {minLabel}</p>
      </div>

      <div className="grid grid-cols-4 gap-2 text-center pb-1">
        <MiniNumeric label="Matches" value={d.total_matches} />
        <MiniNumeric label="Won" value={d.matches_won} color="willow" />
        <MiniNumeric label="Lost" value={d.matches_lost} color="ember" />
        <MiniNumeric label="Drawn" value={d.matches_drawn} />
      </div>

      <div className="space-y-2">
        <OutcomeBar label="Win" value={d.winning_percentage} color="willow" />
        <OutcomeBar label="Loss" value={d.losing_percentage} color="ember" delay={80} />
        <OutcomeBar label="Draw" value={d.drawing_percentage} color="gray" delay={160} />
      </div>
    </div>
  )
}

function OutcomeBar({ label, value, color, delay = 0 }) {
  return (
    <div>
      <div className="flex justify-between items-baseline mb-1">
        <span className="label-eyebrow">{label}</span>
        <span className="font-display text-sm text-cream-50 tabular-nums">{value}%</span>
      </div>
      <PercentageBar value={value} color={color} delay={delay} />
    </div>
  )
}

function CountryResult({ d, kind }) {
  const isB = kind === 'batting'
  return (
    <div className="space-y-3">
      <div className="text-center pb-1">
        <div className="label-eyebrow mb-1">{isB ? 'Batting by country' : 'Bowling by country'}</div>
        <h3 className="font-display text-lg text-cream-50">{d.player}</h3>
        <p className="text-[11px] text-cream-200/60 mt-0.5">{d.player_team} · {d.total_countries} countries</p>
      </div>

      <div className="space-y-1.5 max-h-72 overflow-y-auto pr-1">
        {d.country_statistics.map((c, i) => (
          <div
            key={c.country}
            className="flex items-center justify-between gap-3 p-2 bg-ink-800/60 rounded border-l-2 border-ink-600 hover:border-willow-500 transition-colors anim-fade-in-up"
            style={{ animationDelay: `${i * 20}ms` }}>
            <div className="flex items-center gap-2 min-w-0">
              <div className="font-display text-sm text-cream-400/70 tabular-nums w-5 text-right">{i + 1}</div>
              <div className="min-w-0">
                <div className="text-sm font-medium text-cream-50 truncate">{c.country}</div>
                <div className="text-[10px] text-cream-300/50 font-mono">{c.matches_played} matches</div>
              </div>
            </div>
            <div className="text-right shrink-0">
              <div className="font-display text-lg text-willow-300 tabular-nums leading-none">
                {isB ? c.batting_average : (c.bowling_average ?? 'N/A')}
              </div>
              <div className="text-[10px] text-cream-300/50 font-mono mt-0.5">
                {isB
                  ? `${c.total_runs}r · ${c.times_out}o`
                  : `${c.total_runs_conceded}r · ${c.total_wickets}w`}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
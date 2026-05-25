import React, { useEffect, useState } from 'react'
import { api } from '../api'
import { ErrorBanner, Field, LoadingPanel, SectionHeader, SeamDivider } from './ui'

export function PredictTab() {
  const [teams, setTeams] = useState([])

  const [teamA, setTeamA] = useState('')
  const [teamB, setTeamB] = useState('')
  const [poolA, setPoolA] = useState([])
  const [poolB, setPoolB] = useState([])
  const [xiA, setXiA] = useState([])
  const [xiB, setXiB] = useState([])
  const [venue, setVenue] = useState('neutral')

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)

  useEffect(() => {
    api.getTeams().then(setTeams).catch(() => { })
  }, [])

  useEffect(() => {
    setXiA([])
    if (!teamA) { setPoolA([]); return }
    api.getTeamPlayers(teamA).then(setPoolA).catch(() => setPoolA([]))
  }, [teamA])

  useEffect(() => {
    setXiB([])
    if (!teamB) { setPoolB([]); return }
    api.getTeamPlayers(teamB).then(setPoolB).catch(() => setPoolB([]))
  }, [teamB])

  function addPlayer(side, name) {
    if (!name) return
    const xi = side === 'a' ? xiA : xiB
    const other = side === 'a' ? xiB : xiA
    const setter = side === 'a' ? setXiA : setXiB
    if (xi.length >= 11) { alert('XI is full (11 players)'); return }
    if (xi.includes(name)) { alert(`${name} is already in the XI`); return }
    if (other.includes(name)) { alert(`${name} is already in the other team's XI`); return }
    setter([...xi, name])
  }

  function removePlayer(side, idx) {
    const setter = side === 'a' ? setXiA : setXiB
    const xi = side === 'a' ? xiA : xiB
    setter(xi.filter((_, i) => i !== idx))
  }

  async function predict() {
    if (!teamA || !teamB) { alert('Please select both teams.'); return }
    if (teamA === teamB) { alert('Teams must be different.'); return }
    if (xiA.length !== 11) { alert(`Team A needs exactly 11 players (currently ${xiA.length}).`); return }
    if (xiB.length !== 11) { alert(`Team B needs exactly 11 players (currently ${xiB.length}).`); return }

    setLoading(true); setError(null); setResult(null)
    try {
      const data = await api.predictMatch({
        team: teamA, team_players: xiA,
        opposition: teamB, opp_players: xiB,
        venue_type: venue,
      })
      setResult(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-8">
      <SectionHeader
        eyebrow="02 — Match Modelling"
        title="Build two XIs. See the verdict."
        description="The model weighs career and recent form for all 22 players. Pick your sides, set the venue, and let the maths speak."
      />

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
        <TeamPanel
          side="a"
          accentLabel="Predict for"
          accentColor="willow"
          teams={teams}
          team={teamA} onTeamChange={setTeamA}
          pool={poolA} xi={xiA}
          onAdd={(n) => addPlayer('a', n)}
          onRemove={(i) => removePlayer('a', i)}
          onClear={() => setXiA([])}
        />
        <TeamPanel
          side="b"
          accentLabel="Opposition"
          accentColor="ember"
          teams={teams}
          team={teamB} onTeamChange={setTeamB}
          pool={poolB} xi={xiB}
          onAdd={(n) => addPlayer('b', n)}
          onRemove={(i) => removePlayer('b', i)}
          onClear={() => setXiB([])}
        />
      </div>

      <VenuePanel teamA={teamA} teamB={teamB} venue={venue} onChange={setVenue} onPredict={predict} />

      {(loading || error || result) && (
        <>
          <SeamDivider />
          <div className="anim-fade-in-up">
            {loading && <LoadingPanel label="Running prediction model" />}
            {!loading && error && <ErrorBanner message={error} />}
            {!loading && !error && result && <PredictionResult d={result} />}
          </div>
        </>
      )}
    </div>
  )
}

// ─────────────────────────── TEAM PANEL ────────────────────────────

function TeamPanel({ side, accentLabel, accentColor, teams, team, onTeamChange, pool, xi, onAdd, onRemove, onClear }) {
  const [pickValue, setPickValue] = useState('')
  const accent = {
    willow: { dot: 'bg-willow-500', text: 'text-willow-300', label: side === 'a' ? 'A' : 'B' },
    ember: { dot: 'bg-ember-500', text: 'text-ember-500', label: side === 'a' ? 'A' : 'B' },
  }[accentColor]

  function handleAdd() {
    if (pickValue) {
      onAdd(pickValue)
      setPickValue('')
    }
  }

  return (
    <div className="panel p-5 md:p-6">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className={`w-9 h-9 rounded-full ${accent.dot} flex items-center justify-center font-display text-cream-50 font-medium`}>
            {accent.label}
          </div>
          <div>
            <div className="label-eyebrow">{accentLabel}</div>
            <div className="font-display text-xl text-cream-50">Team {accent.label}</div>
          </div>
        </div>
        <div className={`font-mono text-sm ${xi.length === 11 ? accent.text : 'text-cream-300/40'}`}>
          {xi.length}/11
        </div>
      </div>

      <div className="space-y-3 mb-4">
        <select className="form-input" value={team} onChange={(e) => onTeamChange(e.target.value)}>
          <option value="">Select team {accent.label}</option>
          {teams.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>

        <div className="flex gap-2">
          <select
            className="form-input flex-1"
            value={pickValue}
            disabled={!team}
            onChange={(e) => setPickValue(e.target.value)}>
            <option value="">Select player to add</option>
            {pool.map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
          <button onClick={handleAdd} disabled={!pickValue} className="btn-primary disabled:opacity-40 disabled:cursor-not-allowed">
            Add
          </button>
        </div>
      </div>

      <div className="bg-ink-950/40 rounded-md border border-ink-700/40 p-2 min-h-[120px]">
        {xi.length === 0 ? (
          <div className="flex items-center justify-center h-[120px] text-xs text-cream-300/30 italic font-display">
            No players added yet
          </div>
        ) : (
          <ol className="space-y-1">
            {xi.map((name, i) => (
              <li key={name} className="flex items-center gap-3 px-3 py-2 bg-ink-800/60 rounded hover:bg-ink-700/60 transition-colors group anim-fade-in-up">
                <span className="font-mono text-xs text-cream-300/40 w-5">{i + 1}.</span>
                <span className="flex-1 text-sm text-cream-100 truncate">{name}</span>
                <button
                  onClick={() => onRemove(i)}
                  className="opacity-0 group-hover:opacity-100 text-ember-500 hover:text-ember-600 text-xs px-1.5 py-0.5 rounded transition-opacity"
                  aria-label={`Remove ${name}`}>
                  ✕
                </button>
              </li>
            ))}
          </ol>
        )}
      </div>

      <div className="flex justify-end mt-3">
        <button onClick={onClear} className="text-xs text-cream-300/40 hover:text-ember-500 transition-colors">
          Clear XI
        </button>
      </div>
    </div>
  )
}

// ─────────────────────────── VENUE + PREDICT ────────────────────────────

function VenuePanel({ teamA, teamB, venue, onChange, onPredict }) {
  const options = [
    { value: 'home', label: teamA ? `${teamA} home` : 'Team A home', hint: 'Home advantage A' },
    { value: 'neutral', label: 'Neutral venue', hint: 'No advantage' },
    { value: 'away', label: teamB ? `${teamB} home` : 'Team B home', hint: 'Home advantage B' },
  ]

  return (
    <div className="panel p-5 md:p-6">
      <div className="flex flex-col lg:flex-row lg:items-end gap-5">
        <div className="flex-1">
          <div className="label-eyebrow mb-3">Venue</div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
            {options.map((o) => {
              const active = venue === o.value
              return (
                <button
                  key={o.value}
                  onClick={() => onChange(o.value)}
                  className={`text-left px-4 py-3 rounded-md border transition-all
                              ${active
                      ? 'border-willow-500 bg-willow-500/10 text-cream-50'
                      : 'border-ink-700 bg-ink-950/40 text-cream-200/70 hover:border-ink-600 hover:bg-ink-800/40'}`}>
                  <div className="text-sm font-medium">{o.label}</div>
                  <div className="text-xs text-cream-300/40 mt-0.5">{o.hint}</div>
                </button>
              )
            })}
          </div>
        </div>
        <button onClick={onPredict} className="btn-danger px-8 py-4 text-base font-semibold whitespace-nowrap shrink-0">
          Predict match →
        </button>
      </div>
    </div>
  )
}

// ─────────────────────────── RESULT ────────────────────────────

function PredictionResult({ d }) {
  const winnerIsA = d.predicted_outcome === 'Win'
  const probA = (d.win_probability * 100).toFixed(1)
  const probB = (d.loss_probability * 100).toFixed(1)
  const venueLabel = {
    home: `${d.team} home ground`,
    away: `${d.opposition} home ground`,
    neutral: 'Neutral venue',
  }[d.venue_type] || d.venue_type

  return (
    <div className="space-y-6">
      {/* Winner banner */}
      <div className="panel-elevated p-8 md:p-12 text-center relative overflow-hidden">
        <div className="absolute inset-0 opacity-10 pointer-events-none"
          style={{
            backgroundImage: 'radial-gradient(circle at 30% 50%, #5e8b3d 0%, transparent 60%), radial-gradient(circle at 70% 50%, #c8553d 0%, transparent 60%)',
          }} />
        <div className="relative">
          <div className="label-eyebrow mb-3">{venueLabel}</div>
          <div className="label-eyebrow text-cream-400 mb-1">Predicted winner</div>
          <h2 className="display-title text-5xl md:text-6xl mb-2 italic font-light tracking-tight">
            {winnerIsA ? d.team : d.opposition}
          </h2>
          <div className="text-xs font-mono text-cream-300/60 mt-3">
            {winnerIsA ? probA : probB}% confidence
          </div>
        </div>
      </div>

      {/* Probability split */}
      <div className="panel p-5 md:p-6">
        <div className="label-eyebrow mb-3">Win probability split</div>
        <div className="flex justify-between text-sm mb-3 font-medium">
          <span className="text-willow-300">{d.team} · {probA}%</span>
          <span className="text-ember-500">{probB}% · {d.opposition}</span>
        </div>
        <div className="h-3 bg-ink-950 rounded-full overflow-hidden relative flex">
          <div className="bg-willow-500 h-full anim-grow" style={{ width: `${probA}%` }} />
          <div className="bg-ember-500  h-full anim-grow" style={{ width: `${probB}%`, animationDelay: '120ms' }} />
        </div>
      </div>

      {/* Warnings */}
      {d.warnings && d.warnings.length > 0 && (
        <div className="rounded-md border border-cream-300/30 bg-cream-300/5 p-4">
          <div className="label-eyebrow text-cream-300 mb-2">Data quality notes</div>
          <ul className="space-y-1 text-sm text-cream-200/80">
            {d.warnings.map((w, i) => (
              <li key={i}>· <span className="font-medium text-cream-100">{w.team}</span>: {w.message}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Factor breakdown */}
      <div className="panel overflow-hidden">
        <div className="px-5 py-4 border-b border-ink-700/60">
          <div className="label-eyebrow">Factor breakdown</div>
          <div className="font-display text-lg text-cream-50">How the model arrived here</div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-cream-300/50 uppercase tracking-wider">
                <th className="py-3 px-5 font-medium">Factor</th>
                <th className="py-3 px-3 text-center font-medium text-willow-300">{d.team}</th>
                <th className="py-3 px-3 text-center font-medium text-ember-500">{d.opposition}</th>
                <th className="py-3 px-5 text-center font-medium">Edge</th>
              </tr>
            </thead>
            <tbody>
              {d.factors.map((f, i) => {
                const teamName = f.advantage === 'team' ? d.team.split(' ')[0]
                  : f.advantage === 'opposition' ? d.opposition.split(' ')[0] : null
                const edgeColor = f.advantage === 'team' ? 'text-willow-300'
                  : f.advantage === 'opposition' ? 'text-ember-500' : 'text-cream-300/40'
                const borderColor = f.advantage === 'team' ? 'border-l-willow-500'
                  : f.advantage === 'opposition' ? 'border-l-ember-500' : 'border-l-ink-600'
                return (
                  <tr key={i} className={`border-l-2 ${borderColor} border-b border-ink-800/60 hover:bg-ink-800/40 transition-colors`}>
                    <td className="py-3 px-5 text-cream-100">{f.name}</td>
                    <td className="py-3 px-3 text-center font-mono text-willow-200/80 tabular-nums">{f.team_value}</td>
                    <td className="py-3 px-3 text-center font-mono text-ember-500/80 tabular-nums">{f.opp_value}</td>
                    <td className={`py-3 px-5 text-center font-medium ${edgeColor}`}>
                      {teamName ? (f.advantage === 'team' ? `◀ ${teamName}` : `${teamName} ▶`) : '—'}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

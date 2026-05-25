import React, { useState } from 'react'
import { api } from '../api'
import { ErrorBanner, LoadingPanel, SectionHeader, SeamDivider } from './ui'

export function DataTab() {
  const [loading, setLoading] = useState(null) // 'batting' | 'bowling' | 'team' | null
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)

  async function scrape(type) {
    setLoading(type); setError(null); setResult(null)
    try {
      const data = await api.scrape(type)
      setResult({ type, data })
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(null)
    }
  }

  const sources = [
    { id: 'batting', title: 'Batting innings', desc: 'Fetch new batting innings from ESPN Cricinfo.', icon: '🏏' },
    { id: 'bowling', title: 'Bowling figures', desc: 'Fetch new bowling spells from ESPN Cricinfo.', icon: '⚡' },
    { id: 'team', title: 'Team results', desc: 'Fetch new team match records and outcomes.', icon: '🏆' },
  ]

  return (
    <div className="space-y-8">
      <SectionHeader
        eyebrow="03 — Data Sync"
        title="Pull fresh innings from Cricinfo."
        description="Scrapes only records newer than what's already stored locally. Run as often as you'd like — each request appends to the database."
      />

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {sources.map((s) => (
          <div key={s.id} className="panel p-6 flex flex-col">
            <div className="text-3xl mb-3 opacity-80">{s.icon}</div>
            <h3 className="font-display text-xl text-cream-50 mb-2">{s.title}</h3>
            <p className="text-sm text-cream-200/60 mb-5 flex-1">{s.desc}</p>
            <button
              onClick={() => scrape(s.id)}
              disabled={loading !== null}
              className="btn-primary w-full disabled:opacity-40 disabled:cursor-not-allowed">
              {loading === s.id ? 'Scraping…' : 'Start scrape'}
            </button>
          </div>
        ))}
      </div>

      {(loading || error || result) && (
        <>
          <SeamDivider />
          <div className="anim-fade-in-up">
            {loading && <LoadingPanel label={`Scraping ${loading} records`} />}
            {!loading && error && <ErrorBanner message={error} />}
            {!loading && !error && result && (
              <div className="panel p-5">
                <div className="label-eyebrow mb-3">Scrape result · {result.type}</div>
                <pre className="bg-ink-950/80 border border-ink-700/60 rounded-md p-4 text-xs text-cream-100 font-mono overflow-x-auto max-h-96">
                  {JSON.stringify(result.data, null, 2)}
                </pre>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}

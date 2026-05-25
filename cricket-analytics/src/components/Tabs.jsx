import React from 'react'

const TABS = [
  { id: 'analytics', label: 'Analytics', hint: 'Player insights' },
  { id: 'predict', label: 'Prediction', hint: 'Match modelling' },
  { id: 'data', label: 'Data', hint: 'Scrape & sync' },
]

export function Tabs({ active, onChange }) {
  return (
    <nav className="mt-8 mb-6">
      <div className="flex flex-wrap gap-1 border-b border-ink-700/60">
        {TABS.map((t) => {
          const isActive = active === t.id
          return (
            <button
              key={t.id}
              onClick={() => onChange(t.id)}
              className={`group relative px-5 py-3 transition-colors ${isActive ? 'text-cream-50' : 'text-cream-300/50 hover:text-cream-200'
                }`}
            >
              <div className="flex flex-col items-start">
                <span className="label-eyebrow opacity-70">{t.hint}</span>
                <span className="font-display text-lg leading-tight">{t.label}</span>
              </div>
              {isActive && (
                <span className="absolute -bottom-px left-0 right-0 h-[2px] bg-willow-400" />
              )}
            </button>
          )
        })}
      </div>
    </nav>
  )
}

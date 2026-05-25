import React, { useState } from 'react'
import { Header } from './components/Header'
import { Tabs } from './components/Tabs'
import { AnalyticsTab } from './components/AnalyticsTab'
import { PredictTab } from './components/PredictTab'
import { DataTab } from './components/DataTab'

export default function App() {
  const [tab, setTab] = useState('analytics')

  return (
    <div className="min-h-screen">
      <main className="max-w-7xl mx-auto px-5 md:px-8 pb-20">
        <Header />
        <Tabs active={tab} onChange={setTab} />

        <div className="anim-fade-in-up" key={tab}>
          {tab === 'analytics' && <AnalyticsTab />}
          {tab === 'predict'   && <PredictTab />}
          {tab === 'data'      && <DataTab />}
        </div>

        <footer className="mt-16 pt-6 border-t border-ink-700/40 text-xs text-cream-300/40 flex justify-between items-center">
          <span className="font-display italic">A reading room for Test cricket statistics.</span>
        </footer>
      </main>
    </div>
  )
}

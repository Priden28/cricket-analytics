import React from 'react'
import { SeamDivider } from './ui'

export function Header() {
  return (
    <header className="pt-10 pb-6 relative">
      <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-4">
        <div>
          <div className="flex items-center gap-3 mb-3">
            <CricketBallIcon />
            <span className="label-eyebrow">Vol. I — Test Match Intelligence</span>
          </div>
          <h1 className="display-title text-5xl md:text-7xl leading-[0.95] tracking-[-0.03em]">
            Cricket
            <span className="italic font-light text-willow-300"> Analytics</span>
          </h1>
        </div>
        <div className="md:text-right">
          <p className="font-display italic text-cream-200/70 text-base md:text-lg max-w-sm md:ml-auto leading-snug">
            A reading room for batting averages, bowling figures, and the long arithmetic of the longest format.
          </p>
        </div>
      </div>
      <div className="mt-8">
        <SeamDivider />
      </div>
    </header>
  )
}

function CricketBallIcon() {
  return (
    <svg width="28" height="28" viewBox="0 0 32 32" className="text-ember-500">
      <circle cx="16" cy="16" r="13" fill="currentColor" />
      <path
        d="M6 10 Q16 14 26 10 M6 22 Q16 18 26 22"
        stroke="#faf7f0"
        strokeWidth="0.6"
        fill="none"
        strokeDasharray="1.5 1.5"
        opacity="0.85"
      />
      <circle cx="16" cy="16" r="13" fill="none" stroke="#0a0d0b" strokeWidth="0.5" opacity="0.3" />
    </svg>
  )
}

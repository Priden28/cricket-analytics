import React from 'react'

export function Spinner({ size = 32, className = '' }) {
  return (
    <div
      className={`anim-spin rounded-full border-2 border-willow-500/20 border-t-willow-400 ${className}`}
      style={{ width: size, height: size }}
    />
  )
}

export function LoadingPanel({ label = 'Loading' }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 gap-4">
      <div className="relative">
        <Spinner size={40} />
        <div className="absolute inset-0 anim-pulse-ring rounded-full" />
      </div>
      <p className="label-eyebrow">{label}</p>
    </div>
  )
}

export function ErrorBanner({ message }) {
  if (!message) return null
  return (
    <div className="rounded-md border border-ember-500/40 bg-ember-500/10 px-4 py-3 text-sm text-ember-500">
      <span className="font-semibold mr-2">Error.</span>
      {message}
    </div>
  )
}

export function SectionHeader({ eyebrow, title, description }) {
  return (
    <div className="mb-6">
      {eyebrow && <div className="label-eyebrow mb-2">{eyebrow}</div>}
      <h2 className="display-title text-2xl md:text-3xl mb-1">{title}</h2>
      {description && <p className="text-sm text-cream-200/60 max-w-2xl">{description}</p>}
    </div>
  )
}

export function Field({ label, children }) {
  return (
    <label className="block">
      <span className="label-eyebrow block mb-1.5">{label}</span>
      {children}
    </label>
  )
}

export function SeamDivider({ className = '' }) {
  return <div className={`seam-line ${className}`} />
}

export function PercentageBar({ value, color = 'willow', delay = 0 }) {
  const colorMap = {
    willow: 'bg-willow-500',
    ember: 'bg-ember-500',
    cream: 'bg-cream-300',
    gray: 'bg-ink-600',
  }
  return (
    <div className="h-2 w-full bg-ink-950/80 rounded-full overflow-hidden">
      <div
        className={`h-full ${colorMap[color]} anim-grow rounded-full`}
        style={{ width: `${value}%`, animationDelay: `${delay}ms` }}
      />
    </div>
  )
}

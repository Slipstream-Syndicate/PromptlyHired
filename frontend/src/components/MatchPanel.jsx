/**
 * Match analysis display.
 *
 * The percentage is a single headline number, so it is a stat with a meter
 * rather than a chart. Colour is never the only signal - the number and a plain
 * text band always accompany it, which matters because the high/low ends are a
 * green/red pair that deuteranopes cannot separate by hue.
 */
function band(pct) {
  if (pct >= 75) return { key: 'strong', label: 'Strong match' }
  if (pct >= 50) return { key: 'partial', label: 'Partial match' }
  return { key: 'weak', label: 'Weak match' }
}

function Requirements({ title, items, tone }) {
  if (!items?.length) return null
  return (
    <div className="req-block">
      <h3 className="req-title" data-tone={tone}>
        {title} <span className="count-pill">{items.length}</span>
      </h3>
      <ul className="req-list" data-tone={tone}>
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  )
}

export default function MatchPanel({ match, analysing, onAnalyse, onReanalyse }) {
  if (!match) {
    return (
      <>
        <h2 className="section-title">Your match</h2>
        <div className="card">
          <p className="job-company" style={{ marginBottom: 12 }}>
            We haven’t analysed this role against your resume yet. Analysis reads the
            full advert and compares it with your experience.
          </p>
          <button className="btn primary" onClick={onAnalyse} disabled={analysing}>
            {analysing ? 'Analysing…' : 'Analyse my match'}
          </button>
        </div>
      </>
    )
  }

  const pct = Math.max(0, Math.min(100, match.match_percentage))
  const { key, label } = band(pct)

  return (
    <>
      <h2 className="section-title">Your match</h2>
      <div className="card">
        <div className="match-head">
          <div className="match-score" data-band={key}>
            {pct}
            <span className="match-pct">%</span>
          </div>
          <div className="job-main">
            <div className="match-band" data-band={key}>
              {label}
            </div>
            <div
              className="meter"
              role="meter"
              aria-valuenow={pct}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label="Match score"
            >
              <div className="meter-fill" data-band={key} style={{ width: `${pct}%` }} />
            </div>
          </div>
        </div>

        {match.rationale && <p className="job-blurb">{match.rationale}</p>}

        <Requirements
          title="You already meet"
          items={match.requirements_met}
          tone="met"
        />
        <Requirements
          title="Gaps to address"
          items={match.requirements_missing}
          tone="missing"
        />

        {/* An estimate from a language model, not a hiring prediction. Saying so
            is the honest thing and stops the number being over-read. */}
        <p className="fine-print">
          An AI estimate based on your resume and this advert — not a prediction of
          whether you will be hired. Use the gaps as a checklist, not a verdict.
        </p>

        <button className="btn" onClick={onReanalyse} disabled={analysing}>
          {analysing ? 'Re-analysing…' : 'Re-analyse'}
        </button>
      </div>
    </>
  )
}

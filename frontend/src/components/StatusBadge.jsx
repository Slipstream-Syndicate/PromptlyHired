// Icons are not decoration: offer/rejected are a red/green pair that
// deuteranopes cannot separate by hue, so identity never rests on colour.
export const STATUS_ICONS = {
  applied: '•',
  online_assessment: '◑',
  interview: '◕',
  offer: '✓',
  rejected: '✕',
  withdrawn: '⊘',
}

export const STATUS_LABELS = {
  applied: 'Applied',
  online_assessment: 'Online Assessment',
  interview: 'Interview',
  offer: 'Offer',
  rejected: 'Rejected',
  withdrawn: 'Withdrawn',
}

// Clicking cycles the happy path; the terminal states are picked explicitly
// from the menu rather than being cycled into by accident.
const CYCLE = ['applied', 'online_assessment', 'interview', 'offer']

export function nextStatus(current) {
  const i = CYCLE.indexOf(current)
  if (i === -1) return 'applied'
  return CYCLE[(i + 1) % CYCLE.length]
}

export default function StatusBadge({ status, onClick, disabled }) {
  return (
    <button
      className="status"
      data-s={status}
      onClick={onClick}
      disabled={disabled}
      title="Click to advance status"
    >
      <span aria-hidden="true">{STATUS_ICONS[status] ?? ''}</span>{' '}
      {STATUS_LABELS[status] ?? status}
    </button>
  )
}

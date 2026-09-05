import { NavLink } from 'react-router-dom'

/* Four slots, deliberately. Followed Companies lives inside Profile rather
   than taking a permanent nav slot. */
const ITEMS = [
  {
    to: '/',
    label: 'Search',
    path: 'M10 3a7 7 0 1 0 4.2 12.6l4.1 4.1 1.4-1.4-4.1-4.1A7 7 0 0 0 10 3Zm0 2a5 5 0 1 1 0 10 5 5 0 0 1 0-10Z',
  },
  {
    to: '/saved',
    label: 'Saved',
    path: 'M12 20.3 10.6 19C6 14.9 3.5 12.6 3.5 9.8 3.5 7.5 5.3 5.8 7.5 5.8c1.3 0 2.5.6 3.3 1.5l1.2 1.4 1.2-1.4a4.4 4.4 0 0 1 3.3-1.5c2.2 0 4 1.7 4 4 0 2.8-2.5 5.1-7.1 9.2L12 20.3Z',
  },
  {
    to: '/applications',
    label: 'Applications',
    path: 'M8 3h8a2 2 0 0 1 2 2v15l-6-3-6 3V5a2 2 0 0 1 2-2Zm0 2v11.4l4-2 4 2V5H8Z',
  },
  {
    to: '/profile',
    label: 'Profile',
    path: 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm0 2c-4 0-7 2.2-7 5v1h14v-1c0-2.8-3-5-7-5Z',
  },
]

export default function BottomNav() {
  return (
    <nav className="nav" aria-label="Primary">
      {ITEMS.map((item) => (
        <NavLink key={item.to} to={item.to} end={item.to === '/'}>
          <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <path d={item.path} />
          </svg>
          <span>{item.label}</span>
        </NavLink>
      ))}
    </nav>
  )
}

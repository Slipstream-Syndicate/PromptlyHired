/**
 * Export a generated document to PDF.
 *
 * Rendered as HTML/CSS in a print window and handed to the browser's own PDF
 * engine, rather than a server-side renderer. WeasyPrint would give a one-click
 * download but needs cairo/pango system libraries that Render's plain Python
 * runtime cannot install - that tradeoff is still an open decision in
 * CLAUDE.md. This works everywhere today with no new dependencies, and HTML/CSS
 * is what makes the template look conventional in the first place.
 *
 * Everything interpolated here is escaped: the content was produced by a model
 * that read an untrusted job advert, so it is treated as hostile string data.
 */

function esc(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

const STYLES = `
  @page { size: A4; margin: 18mm 16mm; }
  * { box-sizing: border-box; }
  body {
    font: 11pt/1.45 Georgia, 'Times New Roman', serif;
    color: #111; margin: 0;
  }
  h1 { font-size: 20pt; margin: 0 0 2mm; letter-spacing: -0.01em; }
  .headline { font-size: 11pt; color: #444; margin: 0 0 5mm; }
  h2 {
    font-size: 10pt; text-transform: uppercase; letter-spacing: 0.09em;
    border-bottom: 0.6pt solid #999; padding-bottom: 1.5mm;
    margin: 7mm 0 3mm;
  }
  p { margin: 0 0 3mm; }
  ul { margin: 0 0 3mm; padding-left: 5mm; }
  li { margin-bottom: 1.5mm; }
  .skills { font-size: 10pt; }
  /* Never split a section heading from the bullets it introduces. */
  h2, li { break-inside: avoid; }
  h2 { break-after: avoid; }
`

function resumeHtml(doc) {
  const sections = (doc.sections || [])
    .filter((s) => s.heading || (s.bullets || []).length)
    .map(
      (s) => `
        <h2>${esc(s.heading)}</h2>
        <ul>${(s.bullets || [])
          .filter(Boolean)
          .map((b) => `<li>${esc(b)}</li>`)
          .join('')}</ul>`,
    )
    .join('')

  const skills = (doc.skills || []).filter(Boolean)

  return `
    <h1>${esc(doc.full_name)}</h1>
    ${doc.headline ? `<p class="headline">${esc(doc.headline)}</p>` : ''}
    ${doc.summary ? `<h2>Summary</h2><p>${esc(doc.summary)}</p>` : ''}
    ${sections}
    ${skills.length ? `<h2>Skills</h2><p class="skills">${skills.map(esc).join(' · ')}</p>` : ''}
  `
}

function coverLetterHtml(doc) {
  return `
    <p>${esc(doc.greeting)}</p>
    ${(doc.paragraphs || [])
      .filter(Boolean)
      .map((p) => `<p>${esc(p)}</p>`)
      .join('')}
    <p>${esc(doc.closing)}</p>
  `
}

export function exportDocumentPdf(kind, doc) {
  const isResume = kind === 'resume'
  const title = isResume ? `${doc.full_name || 'Resume'}` : 'Cover letter'
  const body = isResume ? resumeHtml(doc) : coverLetterHtml(doc)

  const win = window.open('', '_blank')
  if (!win) {
    alert('Your browser blocked the print window. Allow pop-ups for this site and try again.')
    return
  }

  win.document.write(
    `<!doctype html><html><head><meta charset="utf-8">` +
      `<title>${esc(title)}</title><style>${STYLES}</style></head>` +
      `<body>${body}</body></html>`,
  )
  win.document.close()

  // Let the document lay out before invoking print, or Safari prints a blank page.
  win.onload = () => {
    win.focus()
    win.print()
  }
}

// Progressive enhancement only: without this file every mockup is listed and the reel shows the finished project.

// Tour: mockups as tabs (WAI-ARIA tabs pattern; up/down on the vertical list, left/right on mobile)
const tabs = [...document.querySelectorAll('.tour-tabs [role="tab"]')]

function select(tab, focus) {
  for (const t of tabs) {
    const on = t === tab
    t.setAttribute('aria-selected', String(on))
    t.tabIndex = on ? 0 : -1
    document.getElementById(t.getAttribute('aria-controls')).hidden = !on
  }
  if (focus) {
    tab.focus()
    tab.scrollIntoView({ block: 'nearest', inline: 'nearest' })
  }
}

// Mockups replay when their tab shows (CSS animations restart when a hidden frame shows);
// a click on the tab already open replays it too.
function replay(tab) {
  const frame = document.getElementById(tab.getAttribute('aria-controls'))
  for (const animation of frame.getAnimations?.({ subtree: true }) ?? []) {
    animation.cancel()
    animation.play()
  }
}

for (const tab of tabs) {
  tab.addEventListener('click', () => {
    if (tab.getAttribute('aria-selected') === 'true') replay(tab)
    else select(tab, false)
  })
  tab.addEventListener('keydown', (e) => {
    const i = tabs.indexOf(tab)
    const next = { ArrowDown: i + 1, ArrowRight: i + 1, ArrowUp: i - 1, ArrowLeft: i - 1, Home: 0, End: tabs.length - 1 }[e.key]
    if (next === undefined) return
    e.preventDefault()
    select(tabs[(next + tabs.length) % tabs.length], true)
  })
}
if (tabs.length) select(tabs[0], false)

// The first mockup waits, paused, until the tour scrolls into view
const tour = document.querySelector('.tour')
if (tour && 'IntersectionObserver' in window) {
  const observer = new IntersectionObserver((entries) => {
    if (entries.some((e) => e.isIntersecting)) {
      observer.disconnect()
      tour.classList.add('seen')
    }
  }, { threshold: 0.4 })
  observer.observe(tour)
} else if (tour) {
  tour.classList.add('seen')
}

// Copy buttons
for (const button of document.querySelectorAll('[data-copy]')) {
  button.addEventListener('click', async () => {
    const text = document.getElementById(button.dataset.copy).textContent
    try {
      await navigator.clipboard.writeText(text)
      button.textContent = 'Copied'
    } catch {
      button.textContent = 'Copy failed'
    }
    setTimeout(() => { button.textContent = 'Copy' }, 1600)
  })
}

// Reel: the playhead sweeps the project once, the first time it comes into view
const reel = document.querySelector('[data-reel]')
if (reel) {
  const scroller = reel.querySelector('.reel-scroll')
  const playhead = reel.querySelector('.playhead')

  // On narrow screens the reel scrolls: keep the playhead in view while it plays, like an editor does
  function follow() {
    if (scroller.scrollWidth <= scroller.clientWidth) return
    const end = performance.now() + 5000
    const step = () => {
      const x = playhead.getBoundingClientRect().left - scroller.getBoundingClientRect().left + scroller.scrollLeft
      scroller.scrollLeft = x - scroller.clientWidth / 2
      if (performance.now() < end) requestAnimationFrame(step)
    }
    requestAnimationFrame(step)
  }

  const run = () => setTimeout(() => {
    reel.classList.add('run')
    if (!matchMedia('(prefers-reduced-motion: reduce)').matches) follow()
  }, 350)
  if (!('IntersectionObserver' in window)) {
    reel.classList.add('run')
  } else {
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) {
        observer.disconnect()
        document.fonts.ready.then(run)
      }
    }, { threshold: 0.35 })
    observer.observe(reel)
  }
}

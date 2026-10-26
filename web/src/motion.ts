let activeFrame: number | null = null
let restoreScrollBehavior: (() => void) | null = null

export function scrollExactlyToTop() {
  if (activeFrame !== null) cancelAnimationFrame(activeFrame)
  restoreScrollBehavior?.()
  const root = (document.scrollingElement ?? document.documentElement) as HTMLElement
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    root.scrollTop = 0
    document.body.scrollTop = 0
    return
  }
  const previousRootBehavior = root.style.scrollBehavior
  const previousBodyBehavior = document.body.style.scrollBehavior
  root.style.scrollBehavior = 'auto'
  document.body.style.scrollBehavior = 'auto'
  restoreScrollBehavior = () => {
    root.style.scrollBehavior = previousRootBehavior
    document.body.style.scrollBehavior = previousBodyBehavior
    restoreScrollBehavior = null
  }
  const start = root.scrollTop
  const startedAt = performance.now()
  const duration = Math.min(700, Math.max(320, start * 0.35))
  const step = (now: number) => {
    const progress = Math.min(1, (now - startedAt) / duration)
    const eased = 1 - Math.pow(1 - progress, 3)
    const next = Math.max(0, Math.round(start * (1 - eased)))
    root.scrollTop = next
    document.body.scrollTop = next
    if (progress < 1) {
      activeFrame = requestAnimationFrame(step)
    } else {
      root.scrollTop = 0
      document.body.scrollTop = 0
      activeFrame = null
      restoreScrollBehavior?.()
    }
  }
  activeFrame = requestAnimationFrame(step)
}

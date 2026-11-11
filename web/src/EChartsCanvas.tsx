import { useEffect, useRef } from 'react'
import * as echarts from 'echarts/core'
import type { EChartsOption } from 'echarts'

export default function EChartsCanvas({ option, className = '', label = '数据可视化图表' }: { option: EChartsOption; className?: string; label?: string }) {
  const element = useRef<HTMLDivElement>(null)
  const instance = useRef<ReturnType<typeof echarts.init> | null>(null)
  useEffect(() => {
    if (!element.current) return
    const chart = echarts.init(element.current)
    instance.current = chart
    const resize = () => chart.resize()
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(resize)
    observer?.observe(element.current)
    window.addEventListener('resize', resize)
    return () => {
      observer?.disconnect()
      window.removeEventListener('resize', resize)
      chart.dispose()
      instance.current = null
    }
  }, [])
  useEffect(() => { instance.current?.setOption(option, { notMerge: true }) }, [option])
  return <div ref={element} className={`chart ${className}`} role="img" aria-label={label} />
}

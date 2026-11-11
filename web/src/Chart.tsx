import { useEffect, useRef } from 'react'
import * as echarts from 'echarts/core'
import { HeatmapChart, LineChart, ScatterChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, VisualMapComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { EChartsOption } from 'echarts'

echarts.use([LineChart, ScatterChart, HeatmapChart, GridComponent, TooltipComponent, VisualMapComponent, CanvasRenderer])

export default function Chart({ option, className = '', label = '数据可视化图表' }: { option: EChartsOption; className?: string; label?: string }) {
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

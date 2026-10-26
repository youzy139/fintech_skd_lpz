import { useEffect, useRef } from 'react'
import * as echarts from 'echarts/core'
import { LineChart, ScatterChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { EChartsOption } from 'echarts'

echarts.use([LineChart, ScatterChart, GridComponent, TooltipComponent, CanvasRenderer])

export default function Chart({ option, className = '' }: { option: EChartsOption; className?: string }) {
  const element = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!element.current) return
    const chart = echarts.init(element.current)
    chart.setOption(option)
    const resize = () => chart.resize()
    window.addEventListener('resize', resize)
    return () => {
      window.removeEventListener('resize', resize)
      chart.dispose()
    }
  }, [option])
  return <div ref={element} className={`chart ${className}`} role="img" />
}

import * as echarts from 'echarts/core'
import { HeatmapChart, ScatterChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, VisualMapComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import EChartsCanvas from './EChartsCanvas'
import type { EChartsOption } from 'echarts'

echarts.use([ScatterChart, HeatmapChart, GridComponent, TooltipComponent, VisualMapComponent, CanvasRenderer])

export default function RegimeChart(props: { option: EChartsOption; className?: string; label?: string }) {
  return <EChartsCanvas {...props} />
}

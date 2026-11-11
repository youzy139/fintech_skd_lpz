const paths: Record<string, string> = {
  home: 'm3 10 9-7 9 7v10H3Zm5 10v-7h8v7',
  overview: 'M3 3v18h18M6 15l4-5 4 3 6-8',
  regimes: 'M3 4h7v7H3Zm11 0h7v7h-7ZM3 15h7v6H3Zm11 0h7v6h-7Z',
  features: 'M2 12h3l3-8 5 16 3-8h6',
  alerts: 'm12 3 10 18H2ZM12 9v5m0 3v1',
  replay: 'M4 9a8 8 0 1 1 0 7M4 3v6h6m1 0 5 3-5 3Z',
  data: 'M3 4h18v16H3Zm0 5h18M8 9v11',
  arrow: 'M4 12h16m-6-6 6 6-6 6',
  download: 'M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5',
  refresh: 'M20 7v5h-5M4 17v-5h5m-5 0a8 8 0 0 1 14-6m2 6a8 8 0 0 1-14 6',
  menu: 'M3 6h18M3 12h18M3 18h18',
  close: 'm5 5 14 14M19 5 5 19',
}

export default function Icon({ name, className = '' }: { name: string; className?: string }) {
  return <svg className={`icon ${className}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name] ?? paths.overview} /></svg>
}

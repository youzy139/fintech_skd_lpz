const paths: Record<string, string> = {
  home: 'm3 10 9-7 9 7v10H3Zm5 10v-7h8v7',
  overview: 'M3 3v18h18M6 15l4-5 4 3 6-8',
  regimes: 'M3 4h7v7H3Zm11 0h7v7h-7ZM3 15h7v6H3Zm11 0h7v6h-7Z',
  features: 'M2 12h3l3-8 5 16 3-8h6',
  alerts: 'm12 3 10 18H2ZM12 9v5m0 3v1',
  replay: 'M4 9a8 8 0 1 1 0 7M4 3v6h6m1 0 5 3-5 3Z',
  data: 'M3 4h18v16H3Zm0 5h18M8 9v11',
  accounts: 'M16 20v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2m7-10a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm8-3v6m3-3h-6',
  audit: 'M6 3h12v18H6Zm3 5h6m-6 4h6m-6 4h4',
  system: 'M4 4h16v12H4Zm4 16h8m-4-4v4M7 8h2m2 0h6M7 12h6',
  arrow: 'M4 12h16m-6-6 6 6-6 6',
  download: 'M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5',
  refresh: 'M20 7v5h-5M4 17v-5h5m-5 0a8 8 0 0 1 14-6m2 6a8 8 0 0 1-14 6',
  menu: 'M3 6h18M3 12h18M3 18h18',
  close: 'm5 5 14 14M19 5 5 19',
  search: 'M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14Zm5-2 5 5',
  logout: 'M10 4H4v16h6m5-4 4-4-4-4m4 4H9',
}

export default function Icon({ name, className = '' }: { name: string; className?: string }) {
  return <svg className={`icon ${className}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name] ?? paths.overview} /></svg>
}

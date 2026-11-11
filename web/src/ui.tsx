import Icon from './Icon'
import { ruleNames } from './labels'
import type { Alert } from './types'

export function Panel({ title, subtitle, children, action, className = '' }: { title: string; subtitle?: string; children: React.ReactNode; action?: React.ReactNode; className?: string }) {
  return <section className={`panel ${className}`}><div className="panel-head"><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>{action && <div className="panel-action">{action}</div>}</div><div className="panel-body">{children}</div></section>
}

export function Metric({ label, value, detail, icon, featured = false, tone = '' }: { label: string; value: React.ReactNode; detail?: React.ReactNode; icon?: string; featured?: boolean; tone?: string }) {
  return <div className={`metric ${featured ? 'featured' : ''}`}><span>{label}{icon && <Icon name={icon} />}</span><strong className={tone}>{value}</strong>{detail && <small>{detail}</small>}</div>
}

export function Loading({ children = '正在加载数据…' }: { children?: React.ReactNode }) {
  return <div className="page-loading" role="status"><span className="loader" />{children}</div>
}

export function ErrorMessage({ message, onRetry, retryLabel = '重试' }: { message: string; onRetry?: () => void; retryLabel?: string }) {
  return <div className="error" role="alert"><span>{message}</span>{onRetry && <button onClick={onRetry}>{retryLabel}</button>}</div>
}

export function AlertList({ alerts, onEvidence, compact = false }: { alerts: Alert[]; onEvidence?: (alert: Alert, trigger: HTMLElement) => void; compact?: boolean }) {
  if (!alerts.length) return <div className="empty"><Icon name="alerts" /><p>当前查询范围内暂无预警</p></div>
  return <div className="table-wrap"><table className={`alert-table ${compact ? 'compact' : ''}`}><thead><tr><th>级别</th><th>预警信号</th><th>触发依据</th><th>规则</th><th>事件日期</th>{onEvidence && <th>操作</th>}</tr></thead><tbody>{alerts.map((item, index) => <tr key={`${item.date}-${item.rule}-${index}`}><td><span className={`alert-level ${item.level}`}>{item.level === 'high' ? '高' : '中'}</span></td><td><strong className="table-title">{item.title}</strong></td><td className="alert-evidence-cell">{item.evidence}</td><td><span className="rule-label">{ruleNames[item.rule] ?? item.rule}</span>{!compact && <small className="table-subtitle">{item.rule_version ?? item.rule}</small>}</td><td className="numeric">{item.date}</td>{onEvidence && <td><button className="text-button" onClick={event => onEvidence(item, event.currentTarget)}>查看证据</button></td>}</tr>)}</tbody></table></div>
}

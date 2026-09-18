import { useEffect, useMemo, useState } from 'react'
import {
  Bar, BarChart, CartesianGrid, Cell, LabelList, Legend, Line, LineChart,
  Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { PageContainer, LoadingState, ErrorState, EmptyState } from '../components/layout/PageContainer'
import { Card, Badge } from '../components/ui/Card'
import {
  BLUE, ClearChip, GREEN, LABEL, ORANGE, Panel, RED, StatTile, TEAL, TICK, TOOLTIP, VIOLET,
  SERIES_COLORS as BAR_COLORS,
} from '../components/ui/Dashboard'
import { fetchAnalyticsFilters, fetchPunchAnomalies, type AnalyticsFilters, type PunchAnalyticsResponse, type PunchAnomaly } from '../services/api'

const SEVERITY_BADGE: Record<string, string> = { High: 'failed', Medium: 'RUNNING', Low: 'not_applicable' }
const SEVERITY_COLOR: Record<string, string> = { High: RED, Medium: ORANGE, Low: '#94a3b8' }
const PAGE_SIZE = 25
/** Long rule names wrap badly on an axis, so shorten for the tick only. */
const shortType = (s: string) => s
  .replace('Potential ', '').replace('Suspicious Punch Pattern', 'Suspicious Pattern')
  .replace('Repeated Manual Edits', 'Manual Edits').replace('Excess Scheduled Hours', 'Excess Hours')

type Grain = 'hourly' | 'daily' | 'monthly'

const count = (rows: PunchAnomaly[], key: (a: PunchAnomaly) => string | null) => {
  const m = new Map<string, number>()
  rows.forEach((a) => {
    const k = key(a)
    if (k) m.set(k, (m.get(k) ?? 0) + 1)
  })
  return Array.from(m.entries())
    .map(([name, value]) => ({ name, value, short: shortType(name) }))
    .sort((a, b) => b.value - a.value)
}

export default function TimePunchAnalytics() {
  const [filterOptions, setFilterOptions] = useState<AnalyticsFilters | null>(null)
  const [locationId, setLocationId] = useState('')
  const [departmentId, setDepartmentId] = useState('')
  const [grain, setGrain] = useState<Grain>('daily')
  const [data, setData] = useState<PunchAnalyticsResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [typeFilter, setTypeFilter] = useState('')
  const [severityFilter, setSeverityFilter] = useState('')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState<PunchAnomaly | null>(null)

  useEffect(() => {
    fetchAnalyticsFilters().then(setFilterOptions)
  }, [])

  useEffect(() => {
    setLoading(true)
    setError(null)
    setPage(1)
    fetchPunchAnomalies({ location_id: locationId || undefined, department_id: departmentId || undefined, grain })
      .then((r) => (r.error ? setError(r.error) : setData(r)))
      .catch((err) => setError(err?.response?.data?.detail ?? String(err)))
      .finally(() => setLoading(false))
  }, [locationId, departmentId, grain])

  const anomalies = data?.anomalies ?? []
  const exceptionTypes = useMemo(() => Array.from(new Set(anomalies.map((a) => a.exception_type))), [anomalies])

  const matchesSearch = (a: PunchAnomaly) =>
    !search || `${a.employee_id} ${a.employee_name}`.toLowerCase().includes(search.toLowerCase())

  // Power BI convention: a visual never filters itself. The type chart honours the
  // severity + search selection, the severity donut honours type + search, and the
  // table honours everything - so you can always click a different slice to move
  // the selection instead of having to clear it first.
  const filtered = useMemo(
    () => anomalies.filter((a) =>
      (!typeFilter || a.exception_type === typeFilter) &&
      (!severityFilter || a.severity === severityFilter) &&
      matchesSearch(a)),
    [anomalies, typeFilter, severityFilter, search],
  )
  const forTypeChart = useMemo(
    () => anomalies.filter((a) => (!severityFilter || a.severity === severityFilter) && matchesSearch(a)),
    [anomalies, severityFilter, search],
  )
  const forSeverityChart = useMemo(
    () => anomalies.filter((a) => (!typeFilter || a.exception_type === typeFilter) && matchesSearch(a)),
    [anomalies, typeFilter, search],
  )

  const byType = useMemo(() => count(forTypeChart, (a) => a.exception_type), [forTypeChart])
  const bySeverity = useMemo(() => {
    const rows = count(forSeverityChart, (a) => a.severity)
    const order = ['High', 'Medium', 'Low']
    return rows.sort((a, b) => order.indexOf(a.name) - order.indexOf(b.name))
  }, [forSeverityChart])
  const byLocation = useMemo(() => count(filtered, (a) => a.location_name), [filtered])
  const byDepartment = useMemo(() => count(filtered, (a) => a.department_name), [filtered])
  const topEmployees = useMemo(
    () => count(filtered, (a) => `${a.employee_name} (${a.employee_id})`).slice(0, 8),
    [filtered],
  )

  const paged = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)
  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))

  const locName = filterOptions?.locations.find((l) => l.location_id === locationId)?.location_name
  const deptName = filterOptions?.departments.find((d) => d.department_id === departmentId)?.department_name
  const selectClass = 'rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-1.5 text-xs text-[var(--color-text)]'

  const toggle = (setter: (v: any) => void, current: string, value: string) => setter(current === value ? '' : value)
  const selectLocationByName = (name: string) => {
    const hit = filterOptions?.locations.find((l) => l.location_name === name)
    if (hit) setLocationId((cur) => (cur === hit.location_id ? '' : hit.location_id))
  }
  const selectDepartmentByName = (name: string) => {
    const hit = filterOptions?.departments.find((d) => d.department_name === name)
    if (hit) setDepartmentId((cur) => (cur === hit.department_id ? '' : hit.department_id))
  }

  const anySelection = typeFilter || severityFilter || search
  const clearAll = () => { setTypeFilter(''); setSeverityFilter(''); setSearch(''); setPage(1) }

  return (
    <PageContainer title="Time Punch Analytics">
      <Card className="!py-2.5">
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <select value={locationId} onChange={(e) => setLocationId(e.target.value)} className={selectClass}>
            <option value="">All locations</option>
            {filterOptions?.locations.map((l) => <option key={l.location_id} value={l.location_id}>{l.location_name}</option>)}
          </select>
          <select value={departmentId} onChange={(e) => setDepartmentId(e.target.value)} className={selectClass}>
            <option value="">All departments</option>
            {filterOptions?.departments.map((d) => <option key={d.department_id} value={d.department_id}>{d.department_name}</option>)}
          </select>
          <select value={grain} onChange={(e) => setGrain(e.target.value as Grain)} className={selectClass}>
            <option value="hourly">By hour of day</option>
            <option value="daily">By day</option>
            <option value="monthly">By month</option>
          </select>
          <input
            placeholder="Search employee…"
            value={search}
            onChange={(e) => { setSearch(e.target.value); setPage(1) }}
            className={selectClass}
          />
          {locName && <ClearChip label={locName} onClear={() => setLocationId('')} />}
          {deptName && <ClearChip label={deptName} onClear={() => setDepartmentId('')} />}
          {typeFilter && <ClearChip label={typeFilter} onClear={() => setTypeFilter('')} />}
          {severityFilter && <ClearChip label={`${severityFilter} severity`} onClear={() => setSeverityFilter('')} />}
          {anySelection && (
            <button onClick={clearAll} className="text-[10px] text-[var(--color-text-muted)] underline">clear all</button>
          )}
          {data && <span className="ml-auto text-[11px] text-[var(--color-text-muted)]">{data.window.start} → {data.window.end}</span>}
        </div>
        <p className="mt-1.5 text-[10px] text-[var(--color-text-muted)]">
          Click any column or donut slice to filter the page.
        </p>
      </Card>

      {loading && <LoadingState />}
      {error && <ErrorState message={error} />}

      {data && !error && (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
            <StatTile label="Total Punches" value={data.kpis.total_punches.toLocaleString()}
              spark={data.trend} sparkKey="punches" tint="blue" accent />
            <StatTile label="Exception Rate" value={data.kpis.exception_rate_pct != null ? `${data.kpis.exception_rate_pct}%` : '—'}
              spark={data.trend} sparkKey={data.trend.some((t) => t.issue_rate_pct != null) ? 'issue_rate_pct' : 'issues'}
              tint="red" />
            <StatTile label="Missed Punches" value={String(data.kpis.missed_punches)} tint="orange" />
            <StatTile label="Manual Edits" value={String(data.kpis.manual_edits)} tint="violet" />
            <StatTile label="In Selection" value={filtered.length.toLocaleString()}
              spark={data.trend} sparkKey="issues" tint="amber" />
          </div>

          <div className="grid grid-cols-1 gap-3 lg:grid-cols-4">
            <Panel
              title="By Severity" accent={RED}
              note="Click a ring segment to keep only that severity."
              action={severityFilter ? <ClearChip label="filtered" onClear={() => setSeverityFilter('')} /> : undefined}
            >
              <div className="relative">
                <ResponsiveContainer width="100%" height={196}>
                  <PieChart>
                    <Pie
                      data={bySeverity} dataKey="value" nameKey="name"
                      cx="50%" cy="46%" innerRadius={52} outerRadius={78} paddingAngle={2} stroke="none"
                      isAnimationActive={false} className="cursor-pointer"
                      onClick={(e: any) => e?.name && toggle(setSeverityFilter, severityFilter, e.name)}
                    >
                      {bySeverity.map((r) => (
                        <Cell key={r.name} fill={SEVERITY_COLOR[r.name] ?? '#94a3b8'}
                          opacity={severityFilter && r.name !== severityFilter ? 0.28 : 1} />
                      ))}
                    </Pie>
                    <Tooltip contentStyle={TOOLTIP} />
                    <Legend wrapperStyle={{ fontSize: 10, cursor: 'pointer' }}
                      onClick={(e: any) => e?.value && toggle(setSeverityFilter, severityFilter, e.value)} />
                  </PieChart>
                </ResponsiveContainer>
                <div className="pointer-events-none absolute inset-x-0 top-[26%] flex flex-col items-center">
                  <span className="text-base font-bold leading-none text-[var(--color-text)]">
                    {bySeverity.reduce((t, r) => t + r.value, 0).toLocaleString()}
                  </span>
                  <span className="text-[9px] uppercase tracking-wide text-[var(--color-text-muted)]">flagged</span>
                </div>
              </div>
            </Panel>

            <Panel
              title="By Issue Type" accent={ORANGE} className="lg:col-span-2"
              note="Click a column to drill the table into that issue type."
              action={typeFilter ? <ClearChip label="filtered" onClear={() => setTypeFilter('')} /> : undefined}
            >
              <ResponsiveContainer width="100%" height={196}>
                <BarChart data={byType} margin={{ top: 18, right: 6, left: -14, bottom: 0 }} barCategoryGap="22%">
                  <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis dataKey="short" tick={{ ...TICK, fontSize: 8.5 }} tickLine={false} interval={0} angle={-22} textAnchor="end" height={46} />
                  <YAxis tick={TICK} />
                  <Tooltip contentStyle={TOOLTIP} cursor={{ fill: 'rgba(234,88,12,0.06)' }}
                    labelFormatter={(_l: any, pl: any) => pl?.[0]?.payload?.name ?? ''} />
                  <Bar dataKey="value" radius={[5, 5, 0, 0]} isAnimationActive={false} className="cursor-pointer"
                    onClick={(e: any) => e?.name && toggle(setTypeFilter, typeFilter, e.name)}>
                    {byType.map((r, i) => (
                      <Cell key={r.name} fill={BAR_COLORS[i % BAR_COLORS.length]}
                        opacity={typeFilter && r.name !== typeFilter ? 0.28 : 1} />
                    ))}
                    <LabelList dataKey="value" position="top" style={LABEL} />
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </Panel>

            <Panel title="Top Employees" accent={VIOLET} note="Highest flag counts in the current selection.">
              <div className="flex flex-col gap-1.5">
                {topEmployees.length === 0 && <span className="text-[11px] text-[var(--color-text-muted)]">Nothing in this selection.</span>}
                {topEmployees.map((r, i) => {
                  const max = topEmployees[0]?.value || 1
                  return (
                    <div key={r.name}>
                      <div className="flex items-center justify-between text-[10px]">
                        <span className="truncate text-[var(--color-text-muted)]">{r.name}</span>
                        <span className="ml-2 shrink-0 font-semibold text-[var(--color-text)]">{r.value}</span>
                      </div>
                      <div className="mt-0.5 h-3 w-full rounded bg-[var(--color-surface-2)]">
                        <div className="h-full rounded" style={{ width: `${(r.value / max) * 100}%`, background: BAR_COLORS[i % BAR_COLORS.length] }} />
                      </div>
                    </div>
                  )
                })}
              </div>
            </Panel>
          </div>

          <div className="grid grid-cols-1 gap-3 lg:grid-cols-4">
            <Panel
              title={grain === 'hourly' ? 'Issues by Hour of Day' : grain === 'monthly' ? 'Issues by Month' : 'Issues by Day'}
              accent={BLUE} className="lg:col-span-2"
              note={grain === 'hourly'
                ? 'A spike at shift-change usually points to a device or process issue.'
                : 'Rising counts mean punch discipline is slipping.'}
            >
              <ResponsiveContainer width="100%" height={196}>
                <LineChart data={data.trend} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                  <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis dataKey="label" tick={TICK} minTickGap={20} tickLine={false} />
                  <YAxis tick={TICK} />
                  <Tooltip contentStyle={TOOLTIP} />
                  <Legend wrapperStyle={{ fontSize: 10 }} />
                  <Line type="monotone" dataKey="issues" name="Flagged issues" stroke={ORANGE} strokeWidth={2} dot={false} />
                  {grain === 'hourly' && (
                    <Line type="monotone" dataKey="issue_rate_pct" name="Issue rate %" stroke={BLUE} strokeWidth={1.6} strokeDasharray="4 3" dot={false} />
                  )}
                </LineChart>
              </ResponsiveContainer>
            </Panel>

            <Panel title="By Location" accent={TEAL} note="Click a column to filter the page to that site.">
              <ResponsiveContainer width="100%" height={196}>
                <BarChart data={byLocation} margin={{ top: 18, right: 6, left: -14, bottom: 0 }} barCategoryGap="28%">
                  <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis dataKey="short" tick={{ ...TICK, fontSize: 9 }} tickLine={false} interval={0} />
                  <YAxis tick={TICK} />
                  <Tooltip contentStyle={TOOLTIP} cursor={{ fill: 'rgba(13,148,136,0.06)' }}
                    labelFormatter={(_l: any, pl: any) => pl?.[0]?.payload?.name ?? ''} />
                  <Bar dataKey="value" radius={[5, 5, 0, 0]} isAnimationActive={false} className="cursor-pointer"
                    onClick={(e: any) => e?.name && selectLocationByName(e.name)}>
                    {byLocation.map((r, i) => <Cell key={r.name} fill={BAR_COLORS[i % BAR_COLORS.length]} />)}
                    <LabelList dataKey="value" position="top" style={LABEL} />
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </Panel>

            <Panel title="By Department" accent={GREEN} note="Click a column to filter the page to that department.">
              <ResponsiveContainer width="100%" height={196}>
                <BarChart data={byDepartment} margin={{ top: 18, right: 6, left: -14, bottom: 0 }} barCategoryGap="28%">
                  <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis dataKey="short" tick={{ ...TICK, fontSize: 9 }} tickLine={false} interval={0} />
                  <YAxis tick={TICK} />
                  <Tooltip contentStyle={TOOLTIP} cursor={{ fill: 'rgba(22,163,74,0.06)' }}
                    labelFormatter={(_l: any, pl: any) => pl?.[0]?.payload?.name ?? ''} />
                  <Bar dataKey="value" radius={[5, 5, 0, 0]} isAnimationActive={false} className="cursor-pointer"
                    onClick={(e: any) => e?.name && selectDepartmentByName(e.name)}>
                    {byDepartment.map((r, i) => <Cell key={r.name} fill={BAR_COLORS[(i + 3) % BAR_COLORS.length]} />)}
                    <LabelList dataKey="value" position="top" style={LABEL} />
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </Panel>
          </div>

          {data.alerts.length > 0 && (
            <Panel title="Alerts" accent={RED}>
              <div className="grid grid-cols-1 gap-2 lg:grid-cols-2">
                {data.alerts.map((a, i) => (
                  <div key={i} className="flex items-start gap-2.5 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-2)] px-3 py-2">
                    <Badge status={SEVERITY_BADGE[a.level] ?? 'not_applicable'}>{a.level}</Badge>
                    <div className="text-[11px]">
                      <div className="font-medium text-[var(--color-text)]">{a.title}</div>
                      <div className="text-[var(--color-text-muted)]">{a.detail}</div>
                    </div>
                  </div>
                ))}
              </div>
            </Panel>
          )}

          <Card>
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <h3 className="text-[11px] font-semibold uppercase tracking-[0.06em] text-[var(--color-text)]">Flagged issue detail</h3>
              <select value={typeFilter} onChange={(e) => { setTypeFilter(e.target.value); setPage(1) }} className={selectClass}>
                <option value="">All issue types</option>
                {exceptionTypes.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
              <select value={severityFilter} onChange={(e) => { setSeverityFilter(e.target.value); setPage(1) }} className={selectClass}>
                <option value="">All severities</option>
                <option value="High">High</option><option value="Medium">Medium</option><option value="Low">Low</option>
              </select>
              <span className="ml-auto text-xs text-[var(--color-text-muted)]">{filtered.length} flagged issues · click a row for the full reason</span>
            </div>

            {filtered.length === 0 ? (
              <EmptyState message="No flagged issues match these filters." />
            ) : (
              <>
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs">
                    <thead>
                      <tr className="text-[var(--color-text-muted)]">
                        <th className="pb-2">Employee</th><th className="pb-2">Location / Dept</th><th className="pb-2">Shift Date</th>
                        <th className="pb-2">Issue Type</th><th className="pb-2">Severity</th><th className="pb-2">Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {paged.map((a) => (
                        <tr key={a.id} onClick={() => setSelected(a)} className="cursor-pointer border-t border-[var(--color-border)] hover:bg-[var(--color-surface-2)]">
                          <td className="py-2 text-[var(--color-text)]">{a.employee_name} <span className="text-[var(--color-text-muted)]">({a.employee_id})</span></td>
                          <td className="py-2 text-[var(--color-text-muted)]">{a.location_name} / {a.department_name}</td>
                          <td className="py-2 text-[var(--color-text-muted)]">{a.shift_date}</td>
                          <td className="py-2 text-[var(--color-text)]">{a.exception_type}</td>
                          <td className="py-2"><Badge status={SEVERITY_BADGE[a.severity] ?? 'not_applicable'}>{a.severity}</Badge></td>
                          <td className="py-2"><Badge status="RUNNING">{a.status}</Badge></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="mt-3 flex items-center justify-between text-xs text-[var(--color-text-muted)]">
                  <span>Page {page} of {totalPages}</span>
                  <div className="flex gap-2">
                    <button disabled={page <= 1} onClick={() => setPage((p) => p - 1)} className="rounded border border-[var(--color-border)] px-2 py-1 disabled:opacity-40">Prev</button>
                    <button disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)} className="rounded border border-[var(--color-border)] px-2 py-1 disabled:opacity-40">Next</button>
                  </div>
                </div>
              </>
            )}
          </Card>
        </>
      )}

      {selected && (
        <div className="fixed inset-0 z-50 flex justify-end bg-black/50" onClick={() => setSelected(null)}>
          <div onClick={(e) => e.stopPropagation()} className="h-full w-full max-w-md overflow-y-auto border-l border-[var(--color-border)] bg-[var(--color-surface)] p-5">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-sm font-semibold text-[var(--color-text)]">{selected.exception_type}</h2>
              <button onClick={() => setSelected(null)} className="text-[var(--color-text-muted)]">✕</button>
            </div>
            <div className="flex flex-col gap-3 text-xs">
              <Detail label="Employee" value={`${selected.employee_name} (${selected.employee_id})`} />
              <Detail label="Location / Department" value={`${selected.location_name} / ${selected.department_name}`} />
              <Detail label="Shift Date" value={selected.shift_date} />
              <Detail label="Problem" value={selected.problem} />
              <Detail label="Expected Value" value={selected.expected_value} />
              <Detail label="Actual Value" value={selected.actual_value} />
              <Detail label="Variance" value={selected.variance} />
              <Detail label="Rule Triggered" value={selected.rule_triggered} />
              <Detail label="Root Cause" value={selected.root_cause} />
              <Detail label="Potential Impact" value={selected.potential_impact} />
              <Detail label="Recommended Action" value={selected.recommended_action} />
              <div className="flex items-center gap-2">
                <Badge status={SEVERITY_BADGE[selected.severity] ?? 'not_applicable'}>{selected.severity} severity</Badge>
                <Badge status="RUNNING">{selected.status}</Badge>
              </div>
            </div>
          </div>
        </div>
      )}
    </PageContainer>
  )
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-[var(--color-text-muted)]">{label}</div>
      <div className="text-[var(--color-text)]">{value}</div>
    </div>
  )
}

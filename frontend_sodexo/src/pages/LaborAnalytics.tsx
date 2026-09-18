import { useEffect, useMemo, useState } from 'react'
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, LabelList, Legend, Line, LineChart,
  Pie, PieChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { PageContainer, LoadingState, ErrorState } from '../components/layout/PageContainer'
import { Card } from '../components/ui/Card'
import {
  AMBER, BLUE, ClearChip, GREEN, LABEL, MiniTable, ORANGE, Panel, RED, SERIES_COLORS,
  StatTile, TEAL, TICK, TOOLTIP, VIOLET, money, num,
} from '../components/ui/Dashboard'
import { fetchAnalyticsFilters, fetchAnalyticsSummary, type AnalyticsFilters, type AnalyticsSummary } from '../services/api'

type Grain = 'daily' | 'weekly' | 'monthly'

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

function fmtTick(value: string, grain: Grain): string {
  const [y, m, d] = String(value).split('-')
  const month = MONTHS[Number(m) - 1] ?? m
  if (grain === 'monthly') return `${month} ${y?.slice(2)}`
  return `${Number(d)} ${month}`
}

const short = (s: string) => s.replace(' Services', '').replace('Regional Medical Center', 'Regional Med Ctr').replace('Community Hospital', 'Community Hosp')

/** Axis tick that prints the department name with its cost centre beneath it. */
function DeptTick(props: any) {
  const { x, y, payload, rows } = props
  const cc = rows?.[payload?.index]?.cost_center_id
  return (
    <g transform={`translate(${x},${y})`}>
      <text x={0} y={0} dy={11} textAnchor="middle" fontSize={9} fill="var(--color-text-muted)">{payload?.value}</text>
      {cc && <text x={0} y={0} dy={22} textAnchor="middle" fontSize={8} fill="var(--color-text-muted)" opacity={0.65}>{cc}</text>}
    </g>
  )
}

export default function LaborAnalytics() {
  const [filters, setFilters] = useState<AnalyticsFilters | null>(null)
  const [locationId, setLocationId] = useState('')
  const [departmentId, setDepartmentId] = useState('')
  const [grain, setGrain] = useState<Grain>('daily')
  const [lastDays, setLastDays] = useState<number | ''>(30)
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchAnalyticsFilters().then(setFilters)
  }, [])

  useEffect(() => {
    setLoading(true)
    setError(null)
    fetchAnalyticsSummary({
      location_id: locationId || undefined,
      department_id: departmentId || undefined,
      grain,
      last_days: lastDays === '' ? undefined : lastDays,
    })
      .then((r) => (r.error ? setError(r.error) : setSummary(r)))
      .catch((err) => setError(err?.response?.data?.detail ?? String(err)))
      .finally(() => setLoading(false))
  }, [locationId, departmentId, grain, lastDays])

  const locName = filters?.locations.find((l) => l.location_id === locationId)?.location_name
  const deptName = filters?.departments.find((d) => d.department_id === departmentId)?.department_name

  // Cross-filter: clicking a slice, column or legend entry sets the matching page
  // filter, the way a Power BI visual filters the rest of the report. Clicking the
  // already-selected item clears it.
  const selectLocationByName = (name: string) => {
    const hit = filters?.locations.find((l) => short(l.location_name) === name || l.location_name === name)
    if (hit) setLocationId((cur) => (cur === hit.location_id ? '' : hit.location_id))
  }
  const selectDepartmentByName = (name: string) => {
    const hit = filters?.departments.find((d) => short(d.department_name) === name || d.department_name === name)
    if (hit) setDepartmentId((cur) => (cur === hit.department_id ? '' : hit.department_id))
  }

  const withLabel = (rows: any[] | undefined) => (rows ?? []).map((p) => ({ ...p, label: fmtTick(String(p.date), grain) }))
  const costTrend = useMemo(() => withLabel(summary?.labor_cost.trend), [summary, grain])
  const otTrend = useMemo(() => withLabel(summary?.overtime.trend), [summary, grain])
  const effTrend = useMemo(() => withLabel(summary?.efficiency.trend), [summary, grain])
  const attTrend = useMemo(() => withLabel(summary?.attendance.trend), [summary, grain])
  const svaTrend = useMemo(() => withLabel(summary?.scheduled_vs_actual.trend), [summary, grain])
  const locTrend = useMemo(() => withLabel(summary?.labor_cost.by_location_over_time), [summary, grain])

  const deptCost = useMemo(
    () => (summary?.labor_cost.by_department ?? []).map((r) => ({ ...r, name: short(r.department_name) })),
    [summary],
  )
  const deptOt = useMemo(
    () => (summary?.overtime.by_department ?? []).map((r) => ({ ...r, name: short(r.department_name) })),
    [summary],
  )
  const locCost = useMemo(
    () => (summary?.labor_cost.by_location ?? []).map((r) => ({ ...r, name: short(r.location_name) })),
    [summary],
  )
  const totalCost = useMemo(() => locCost.reduce((s, r) => s + r.cost, 0), [locCost])

  // Real cross-tab: cost per site x department. manager_performance is the only
  // response block that carries both dimensions on one row.
  const siteByDept = useMemo(() => {
    const rows = summary?.manager_performance ?? []
    const depts = Array.from(new Set(rows.map((r) => short(r.department_name))))
    const bySite = new Map<string, Record<string, any>>()
    rows.forEach((r) => {
      const site = short(r.location_name)
      const entry = bySite.get(site) ?? { name: site }
      entry[short(r.department_name)] = r.labor_cost
      bySite.set(site, entry)
    })
    return { depts, data: Array.from(bySite.values()) }
  }, [summary])

  // Hours per department: which department works its roster and which drifts off it.
  const deptHours = useMemo(
    () => (summary?.labor_cost.by_department ?? []).map((r) => ({
      name: short(r.department_name), scheduled: r.scheduled_hours, actual: r.actual_hours,
    })),
    [summary],
  )

  const avgCostPerHour = useMemo(() => {
    const vals = (summary?.efficiency.trend ?? []).map((p) => p.cost_per_hour).filter((v): v is number => v != null)
    return vals.length ? vals.reduce((s, v) => s + v, 0) / vals.length : null
  }, [summary])

  const selectClass = 'rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-1.5 text-xs text-[var(--color-text)]'
  const dimDept = (id: string) => (departmentId && id !== departmentId ? 0.28 : 1)
  const dimLoc = (id: string) => (locationId && id !== locationId ? 0.28 : 1)

  return (
    <PageContainer title="Labor Analytics">
      {/* Filter bar */}
      <Card className="!py-2.5">
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <select value={lastDays} onChange={(e) => setLastDays(e.target.value === '' ? '' : Number(e.target.value))} className={selectClass}>
            <option value={30}>Last 30 days</option>
            <option value={60}>Last 60 days</option>
            <option value={90}>Last 90 days</option>
            <option value="">All data</option>
          </select>
          <select value={locationId} onChange={(e) => setLocationId(e.target.value)} className={selectClass}>
            <option value="">All locations</option>
            {filters?.locations.map((l) => <option key={l.location_id} value={l.location_id}>{l.location_name}</option>)}
          </select>
          <select value={departmentId} onChange={(e) => setDepartmentId(e.target.value)} className={selectClass}>
            <option value="">All departments</option>
            {filters?.departments.map((dd) => <option key={dd.department_id} value={dd.department_id}>{dd.department_name}</option>)}
          </select>
          <select value={grain} onChange={(e) => setGrain(e.target.value as Grain)} className={selectClass}>
            <option value="daily">By day</option>
            <option value="weekly">By week</option>
            <option value="monthly">By month</option>
          </select>

          {locName && <ClearChip label={locName} onClear={() => setLocationId('')} />}
          {deptName && <ClearChip label={deptName} onClear={() => setDepartmentId('')} />}

          {summary && (
            <span className="ml-auto text-[11px] text-[var(--color-text-muted)]">
              {summary.window.start} → {summary.window.end}
            </span>
          )}
        </div>
        <p className="mt-1.5 text-[10px] text-[var(--color-text-muted)]">
          Click any column, slice or legend entry to filter the whole page.
        </p>
      </Card>

      {loading && <LoadingState />}
      {error && <ErrorState message={error} />}

      {summary && !error && (
        <>
          {/* KPI tiles */}
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatTile label="Total Labor Cost" value={money(summary.kpis.total_labor_cost)}
              spark={costTrend} sparkKey="cost" tint="blue" accent />
            <StatTile label="Overtime Cost" value={money(summary.kpis.overtime_cost)}
              spark={otTrend} sparkKey="overtime_cost" tint="orange" />
            <StatTile label="Attendance Rate" value={summary.kpis.attendance_rate_pct != null ? `${summary.kpis.attendance_rate_pct}%` : '—'}
              spark={attTrend} sparkKey="present_pct" tint="green" />
            <StatTile label="Labor Utilization" value={summary.kpis.labor_utilization_pct != null ? `${summary.kpis.labor_utilization_pct}%` : '—'}
              spark={effTrend} sparkKey="utilization_pct" tint="teal" />
          </div>

          {/* Breakdown row - donut + three column charts */}
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-4">
            <Panel
              title="Cost by Location" accent={BLUE} note="Click a ring segment to filter to that site."
              action={locName ? <ClearChip label="filtered" onClear={() => setLocationId('')} /> : undefined}
            >
              <div className="relative">
                <ResponsiveContainer width="100%" height={196}>
                  <PieChart>
                    <Pie
                      data={locCost} dataKey="cost" nameKey="name"
                      cx="50%" cy="46%" innerRadius={52} outerRadius={78} paddingAngle={2} stroke="none"
                      isAnimationActive={false} className="cursor-pointer"
                      onClick={(e: any) => e?.name && selectLocationByName(e.name)}
                    >
                      {locCost.map((r, i) => (
                        <Cell key={r.location_id} fill={SERIES_COLORS[i % SERIES_COLORS.length]} opacity={dimLoc(r.location_id)} />
                      ))}
                    </Pie>
                    <Tooltip formatter={(v: any) => money(Number(v))} contentStyle={TOOLTIP} />
                    <Legend wrapperStyle={{ fontSize: 10, cursor: 'pointer' }} onClick={(e: any) => e?.value && selectLocationByName(e.value)} />
                  </PieChart>
                </ResponsiveContainer>
                <div className="pointer-events-none absolute inset-x-0 top-[26%] flex flex-col items-center">
                  <span className="text-base font-bold leading-none text-[var(--color-text)]">{money(totalCost)}</span>
                  <span className="text-[9px] uppercase tracking-wide text-[var(--color-text-muted)]">total</span>
                </div>
              </div>
            </Panel>

            <Panel
              title="Cost by Department" accent={TEAL} note="Cost centre shown under each column."
              action={deptName ? <ClearChip label="filtered" onClear={() => setDepartmentId('')} /> : undefined}
            >
              <ResponsiveContainer width="100%" height={196}>
                <BarChart data={deptCost} margin={{ top: 18, right: 6, left: -12, bottom: 0 }} barCategoryGap="28%">
                  <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                  {/* Two-line tick: department on top, its cost centre underneath.
                      A second <XAxis> would do this too but is fussy about layout. */}
                  <XAxis dataKey="name" tick={<DeptTick rows={deptCost} />} height={32} tickLine={false} interval={0} />
                  <YAxis tick={TICK} tickFormatter={(v) => money(Number(v))} />
                  <Tooltip formatter={(v: any) => money(Number(v))} contentStyle={TOOLTIP} cursor={{ fill: 'rgba(37,99,235,0.06)' }} />
                  <Bar dataKey="cost" radius={[5, 5, 0, 0]} isAnimationActive={false} className="cursor-pointer"
                    onClick={(e: any) => e?.name && selectDepartmentByName(e.name)}>
                    {deptCost.map((r, i) => (
                      <Cell key={r.department_id} fill={SERIES_COLORS[i % SERIES_COLORS.length]} opacity={dimDept(r.department_id)} />
                    ))}
                    <LabelList dataKey="cost" position="top" formatter={(v: any) => money(Number(v))} style={LABEL} />
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </Panel>

            <Panel title="Overtime Hours by Department" accent={ORANGE} note="Click a column to filter to that department.">
              <ResponsiveContainer width="100%" height={196}>
                <BarChart data={deptOt} margin={{ top: 18, right: 6, left: -12, bottom: 0 }} barCategoryGap="28%">
                  <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis dataKey="name" tick={{ ...TICK, fontSize: 9 }} tickLine={false} />
                  <YAxis tick={TICK} />
                  <Tooltip formatter={(v: any) => `${Number(v).toFixed(1)} h`} contentStyle={TOOLTIP} cursor={{ fill: 'rgba(234,88,12,0.06)' }} />
                  <Bar dataKey="overtime_hours" radius={[5, 5, 0, 0]} isAnimationActive={false} className="cursor-pointer"
                    onClick={(e: any) => e?.name && selectDepartmentByName(e.name)}>
                    {deptOt.map((r) => <Cell key={r.department_id} fill={ORANGE} opacity={dimDept(r.department_id)} />)}
                    <LabelList dataKey="overtime_hours" position="top" formatter={(v: any) => Math.round(Number(v))} style={LABEL} />
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </Panel>

            <Panel title="Cost by Site × Department" accent={VIOLET} note="Each column is a site, split by department.">
              <ResponsiveContainer width="100%" height={196}>
                <BarChart data={siteByDept.data} margin={{ top: 8, right: 6, left: -12, bottom: 0 }} barCategoryGap="30%">
                  <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis dataKey="name" tick={{ ...TICK, fontSize: 9 }} tickLine={false} />
                  <YAxis tick={TICK} tickFormatter={(v) => money(Number(v))} />
                  <Tooltip formatter={(v: any) => money(Number(v))} contentStyle={TOOLTIP} cursor={{ fill: 'rgba(124,58,237,0.06)' }} />
                  <Legend wrapperStyle={{ fontSize: 9, cursor: 'pointer' }} onClick={(e: any) => e?.value && selectDepartmentByName(e.value)} />
                  {siteByDept.depts.map((dep, i) => (
                    <Bar key={dep} dataKey={dep} stackId="a" fill={SERIES_COLORS[(i + 1) % SERIES_COLORS.length]}
                      radius={i === siteByDept.depts.length - 1 ? [5, 5, 0, 0] : undefined}
                      isAnimationActive={false} className="cursor-pointer"
                      onClick={() => selectDepartmentByName(dep)} />
                  ))}
                </BarChart>
              </ResponsiveContainer>
            </Panel>
          </div>

          {/* Trend row */}
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
            <Panel title="Labor Cost Trend" accent={BLUE} className="lg:col-span-2">
              <ResponsiveContainer width="100%" height={200}>
                <AreaChart data={costTrend} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id="costFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={BLUE} stopOpacity={0.32} />
                      <stop offset="100%" stopColor={BLUE} stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis dataKey="label" tick={TICK} minTickGap={18} tickLine={false} />
                  <YAxis tick={TICK} tickFormatter={(v) => money(Number(v))} />
                  <Tooltip formatter={(v: any) => money(Number(v))} contentStyle={TOOLTIP} />
                  <Area type="monotone" dataKey="cost" stroke={BLUE} fill="url(#costFill)" strokeWidth={2} dot={false} isAnimationActive={false} />
                </AreaChart>
              </ResponsiveContainer>
            </Panel>

            <Panel title="Scheduled vs Actual Hours" accent={TEAL} note="Where the two separate, roster and reality disagree.">
              <ResponsiveContainer width="100%" height={200}>
                <LineChart data={svaTrend} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                  <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis dataKey="label" tick={TICK} minTickGap={22} tickLine={false} />
                  <YAxis tick={TICK} />
                  <Tooltip contentStyle={TOOLTIP} />
                  <Legend wrapperStyle={{ fontSize: 10 }} />
                  <Line type="monotone" dataKey="scheduled" name="Scheduled" stroke="#94a3b8" strokeWidth={1.5} strokeDasharray="4 3" dot={false} />
                  <Line type="monotone" dataKey="actual" name="Actual" stroke={TEAL} strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </Panel>
          </div>

          <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
            <Panel title="Overtime Trend" accent={ORANGE}>
              <ResponsiveContainer width="100%" height={180}>
                <AreaChart data={otTrend} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id="otFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={ORANGE} stopOpacity={0.3} />
                      <stop offset="100%" stopColor={ORANGE} stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis dataKey="label" tick={TICK} minTickGap={22} tickLine={false} />
                  <YAxis tick={TICK} />
                  <Tooltip contentStyle={TOOLTIP} />
                  <Area type="monotone" dataKey="overtime_hours" name="OT hours" stroke={ORANGE} fill="url(#otFill)" strokeWidth={2} dot={false} isAnimationActive={false} />
                </AreaChart>
              </ResponsiveContainer>
            </Panel>

            <Panel title="Efficiency" accent={TEAL} note="Dashed line is a perfect match between roster and hours worked.">
              <ResponsiveContainer width="100%" height={180}>
                <LineChart data={effTrend} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                  <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis dataKey="label" tick={TICK} minTickGap={22} tickLine={false} />
                  <YAxis tick={TICK} unit="%" />
                  <Tooltip contentStyle={TOOLTIP} />
                  <Legend wrapperStyle={{ fontSize: 10 }} />
                  <ReferenceLine y={100} stroke="#94a3b8" strokeDasharray="4 4" />
                  <Line type="monotone" dataKey="utilization_pct" name="Utilization" stroke={TEAL} strokeWidth={2} dot={false} />
                  <Line type="monotone" dataKey="overtime_share_pct" name="OT share" stroke={ORANGE} strokeWidth={1.6} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </Panel>

            <Panel title="Attendance Mix" accent={GREEN}>
              <ResponsiveContainer width="100%" height={180}>
                <LineChart data={attTrend} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                  <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis dataKey="label" tick={TICK} minTickGap={22} tickLine={false} />
                  <YAxis tick={TICK} unit="%" />
                  <Tooltip contentStyle={TOOLTIP} />
                  <Legend wrapperStyle={{ fontSize: 10 }} />
                  <Line type="monotone" dataKey="present_pct" name="Present" stroke={GREEN} strokeWidth={2} dot={false} />
                  <Line type="monotone" dataKey="absent_pct" name="Absent" stroke={RED} strokeWidth={1.6} dot={false} />
                  <Line type="monotone" dataKey="late_pct" name="Late" stroke={AMBER} strokeWidth={1.6} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </Panel>
          </div>

          <div className="grid grid-cols-1 gap-3 lg:grid-cols-4">
            <Panel title="Cost by Location over Time" accent={BLUE} className="lg:col-span-2"
              note="One line per site — shows which site is driving a movement in the total. Click a legend entry to filter.">
              <ResponsiveContainer width="100%" height={186}>
                <LineChart data={locTrend} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                  <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis dataKey="label" tick={TICK} minTickGap={22} tickLine={false} />
                  <YAxis tick={TICK} tickFormatter={(v) => money(Number(v))} />
                  <Tooltip formatter={(v: any) => money(Number(v))} contentStyle={TOOLTIP} />
                  <Legend wrapperStyle={{ fontSize: 10, cursor: 'pointer' }} onClick={(e: any) => e?.value && selectLocationByName(e.value)} />
                  {summary.labor_cost.location_names.map((name, i) => (
                    <Line key={name} type="monotone" dataKey={name} stroke={SERIES_COLORS[i % SERIES_COLORS.length]}
                      strokeWidth={locName === name ? 2.6 : 1.7}
                      strokeOpacity={locName && locName !== name ? 0.3 : 1} dot={false} />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            </Panel>

            <Panel title="Hours by Department" accent={VIOLET} note="Grey = rostered, solid = actually worked.">
              <ResponsiveContainer width="100%" height={186}>
                <BarChart data={deptHours} margin={{ top: 16, right: 6, left: -12, bottom: 0 }} barCategoryGap="26%">
                  <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis dataKey="name" tick={{ ...TICK, fontSize: 9 }} tickLine={false} />
                  <YAxis tick={TICK} tickFormatter={(v) => num(Number(v))} />
                  <Tooltip formatter={(v: any) => `${num(Number(v))} h`} contentStyle={TOOLTIP} cursor={{ fill: 'rgba(124,58,237,0.06)' }} />
                  <Legend wrapperStyle={{ fontSize: 9 }} />
                  <Bar dataKey="scheduled" name="Scheduled" fill="#cbd5e1" radius={[4, 4, 0, 0]} isAnimationActive={false} />
                  <Bar dataKey="actual" name="Actual" fill={VIOLET} radius={[4, 4, 0, 0]} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </Panel>

            <Panel title="Cost per Hour Worked" accent={AMBER} note="Dashed line is the window average. Spikes usually mean overtime.">
              <ResponsiveContainer width="100%" height={186}>
                <LineChart data={effTrend} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                  <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis dataKey="label" tick={TICK} minTickGap={22} tickLine={false} />
                  <YAxis tick={TICK} tickFormatter={(v) => `$${Number(v).toFixed(0)}`} />
                  <Tooltip formatter={(v: any) => `$${Number(v).toFixed(2)}`} contentStyle={TOOLTIP} />
                  {avgCostPerHour != null && (
                    <ReferenceLine y={avgCostPerHour} stroke="#94a3b8" strokeDasharray="5 4"
                      label={{ value: `avg $${avgCostPerHour.toFixed(2)}`, position: 'insideTopRight', fill: '#64748b', fontSize: 9 }} />
                  )}
                  <Line type="monotone" dataKey="cost_per_hour" name="Cost per hour" stroke={AMBER} strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </Panel>
          </div>

          {/* Productivity + utilization */}
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            <Panel title="Productivity" accent={TEAL} note="Output per labor hour, from the real demand driver for each department.">
              <MiniTable rows={summary.productivity.map((p) => ({
                label: `${p.location_id} / ${p.department_id} · ${p.signal.replace(/_/g, ' ')}`,
                value: p.flow_per_labor_hour != null ? `${p.flow_per_labor_hour}` : 'n/a',
              }))} />
            </Panel>
            <Panel title="Shift Utilization" accent={VIOLET} note="Average hours actually worked against average hours rostered.">
              <MiniTable rows={summary.shift_utilization.map((s) => ({
                label: `${s.location_id} / ${s.department_id}`,
                value: `${s.utilization_pct}%  (${s.avg_actual_hours}h of ${s.avg_scheduled_hours}h)`,
              }))} />
            </Panel>
          </div>

          <ManagerScorecard summary={summary} />
        </>
      )}
    </PageContainer>
  )
}

const METRIC_LABELS: Record<string, string> = {
  overtime_control: 'Overtime',
  punch_accuracy: 'Punch accuracy',
  schedule_adherence: 'Schedule adherence',
  budget_control: 'Cost vs budget',
}

function MetricBar({
  metric, score, value, scale,
}: {
  metric: string
  score: number | null
  value: number | null
  scale: { good: number; poor: number; target: number; higher_is_better: boolean }
}) {
  const targetPos = Math.max(0, Math.min(100, ((scale.poor - scale.target) / (scale.poor - scale.good)) * 100))
  const meetsTarget = value == null ? null : scale.higher_is_better ? value >= scale.target : value <= scale.target
  return (
    <div>
      <div className="flex items-baseline justify-between">
        <span className="text-[10px] text-[var(--color-text-muted)]">{METRIC_LABELS[metric] ?? metric}</span>
        <span className="text-[11px] font-semibold text-[var(--color-text)]">
          {value == null ? '—' : `${value > 0 && metric === 'budget_control' ? '+' : ''}${value}%`}
        </span>
      </div>
      <div className="relative mt-1 h-2 w-full overflow-hidden rounded-full bg-[var(--color-surface-2)]">
        <div className="h-full rounded-full" style={{ width: `${score ?? 0}%`, background: meetsTarget === false ? '#94a3b8' : 'var(--color-text)' }} />
        <div className="absolute top-0 h-full border-l border-dashed border-[var(--color-text-muted)]" style={{ left: `${targetPos}%` }} />
      </div>
      <div className="mt-0.5 text-[9px] text-[var(--color-text-muted)]">
        {score != null && <span className="text-[var(--color-text)]">{score}/100</span>}
        {' · target '}{scale.higher_is_better ? '≥' : '≤'}{scale.target}%
        {meetsTarget === false && <span className="font-medium text-[var(--color-danger)]"> · off target</span>}
      </div>
    </div>
  )
}

function ManagerScorecard({ summary }: { summary: AnalyticsSummary }) {
  const scales = summary.manager_scales
  const sites = summary.manager_performance
  if (!sites.length) return null
  const metrics = Object.keys(scales)

  return (
    <div className="flex flex-col gap-3">
      <Panel title="Manager Scorecard" accent={VIOLET}
        note="Each site scores out of 100 across four operational measures. The dashed mark on each bar is that measure's target. This rates how a site is running, never an individual.">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-[11px]">
            <thead>
              <tr className="text-[var(--color-text-muted)]">
                <th className="pb-1 pr-3">Measure</th><th className="pb-1 pr-3">Scores 100</th>
                <th className="pb-1 pr-3">Scores 0</th><th className="pb-1">Target</th>
              </tr>
            </thead>
            <tbody>
              {metrics.map((m) => (
                <tr key={m} className="border-t border-[var(--color-border)]">
                  <td className="py-1 pr-3 text-[var(--color-text)]">{METRIC_LABELS[m] ?? m}</td>
                  <td className="py-1 pr-3 text-[var(--color-text-muted)]">{scales[m].good}%</td>
                  <td className="py-1 pr-3 text-[var(--color-text-muted)]">{scales[m].poor}%</td>
                  <td className="py-1 text-[var(--color-text-muted)]">{scales[m].higher_is_better ? '≥' : '≤'}{scales[m].target}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2 xl:grid-cols-4">
        {sites.map((m) => {
          const offTarget = metrics.filter((metric) => {
            const v = m.metric_values[metric]
            if (v == null) return false
            return scales[metric].higher_is_better ? v < scales[metric].target : v > scales[metric].target
          }).length
          return (
            <Card key={`${m.location_id}-${m.department_id}`}>
              <div className="mb-2 flex items-start gap-2">
                <div className="flex h-11 w-11 shrink-0 flex-col items-center justify-center rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-2)]">
                  <span className="text-sm font-bold leading-none text-[var(--color-text)]">{m.score ?? '—'}</span>
                  <span className="text-[8px] uppercase tracking-wide text-[var(--color-text-muted)]">score</span>
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5 text-[10px]">
                    <span className="font-semibold text-[var(--color-text-muted)]">#{m.rank}</span>
                    <span className={offTarget > 0 ? 'text-[var(--color-danger)]' : 'text-[var(--color-text-muted)]'}>
                      {offTarget > 0 ? `${offTarget}/${metrics.length} off target` : 'all on target'}
                    </span>
                  </div>
                  <div className="truncate text-[11px] font-semibold text-[var(--color-text)]">{m.location_name}</div>
                  <div className="truncate text-[10px] text-[var(--color-text-muted)]">{m.department_name}</div>
                  <div className="mt-0.5 text-[9px] text-[var(--color-text-muted)]">
                    {m.headcount} staff · {money(m.labor_cost)}
                  </div>
                </div>
              </div>
              <div className="flex flex-col gap-2">
                {metrics.map((metric) => (
                  <MetricBar key={metric} metric={metric}
                    score={m.score_components[metric] ?? null}
                    value={m.metric_values[metric] ?? null}
                    scale={scales[metric]} />
                ))}
              </div>
              {m.worst_metric && (
                <div className="mt-2 rounded bg-[var(--color-surface-2)] px-2 py-1.5 text-[10px]">
                  <span className="font-medium text-[var(--color-text)]">Focus: </span>
                  <span className="text-[var(--color-text-muted)]">{METRIC_LABELS[m.worst_metric] ?? m.worst_metric}</span>
                </div>
              )}
            </Card>
          )
        })}
      </div>
    </div>
  )
}

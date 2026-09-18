import { useEffect, useState } from 'react'
import { PageContainer } from '../components/layout/PageContainer'
import { Card } from '../components/ui/Card'
import { fetchIngestionStatus, runIngestion } from '../services/api'

export default function Overview() {
  const [ingesting, setIngesting] = useState(false)
  const [ingestionMessage, setIngestionMessage] = useState<string | null>(null)
  const [ingestionError, setIngestionError] = useState<string | null>(null)
  const [lastSynced, setLastSynced] = useState<{ sources: number; completedAt: string | null } | null | undefined>(undefined)

  const loadSyncStatus = () => {
    fetchIngestionStatus()
      .then((sources) => {
        if (!sources.length) {
          setLastSynced(null)
          return
        }
        const completedAt = sources.map((s: any) => s.completed_at).filter(Boolean).sort().at(-1) ?? null
        setLastSynced({ sources: sources.length, completedAt })
      })
      .catch(() => setLastSynced(null))
  }

  useEffect(() => {
    loadSyncStatus()
  }, [])

  const handleSyncData = async () => {
    setIngesting(true)
    setIngestionError(null)
    setIngestionMessage(null)
    try {
      const result = await runIngestion()
      const totalLoaded = result.batches.reduce((sum, b) => sum + b.records_loaded, 0)
      setIngestionMessage(`Synced ${result.batches.length} sources, ${totalLoaded.toLocaleString()} records loaded. Labor Analytics, Time Punch Analytics, and Predictive Analytics are ready now. Open Labor Forecasting → Model Training to train the 13 forecasting models.`)
      loadSyncStatus()
    } catch (err: any) {
      setIngestionError(err?.response?.data?.detail ?? String(err))
    } finally {
      setIngesting(false)
    }
  }

  return (
    <PageContainer title="Overview" subtitle="Sodexo Healthcare · Labor Forecasting & Workforce Intelligence">
      <Card className="border-[var(--color-primary)]">
        <h2 className="mb-3 text-sm font-semibold text-[var(--color-text)]">Data sync</h2>
        <button onClick={handleSyncData} disabled={ingesting} className="rounded-lg bg-[var(--color-primary)] px-4 py-2 text-xs font-semibold text-white hover:bg-[var(--color-primary-dark)] disabled:opacity-50">
          {ingesting ? 'Syncing…' : 'Sync Data from API'}
        </button>
        {ingestionError && <div className="mt-3 rounded-lg border border-red-200 bg-red-50 p-2 text-xs text-red-700">{ingestionError}</div>}
        {ingestionMessage && <div className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50 p-2 text-xs text-emerald-700">{ingestionMessage}</div>}
        {!ingestionMessage && lastSynced && (
          <div className="mt-3 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-2)] p-2 text-xs text-[var(--color-text-muted)]">
            Last synced {lastSynced.completedAt ? new Date(lastSynced.completedAt).toLocaleString() : 'recently'} · {lastSynced.sources} sources
          </div>
        )}
        {!ingestionMessage && lastSynced === null && (
          <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-2 text-xs text-amber-700">
            Not synced yet
          </div>
        )}
      </Card>
    </PageContainer>
  )
}

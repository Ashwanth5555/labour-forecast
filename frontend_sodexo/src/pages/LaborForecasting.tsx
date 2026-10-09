import { useNavigate, useParams } from 'react-router-dom'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { PageContainer } from '../components/layout/PageContainer'
import { LABOR_FORECASTING_SECTIONS } from '../components/layout/Sidebar'
import { SeriesSelect, useSeriesOptions } from '../components/forecasting/SeriesSelect'
import { ForecastExplorerTab } from '../components/forecasting/ForecastExplorerTab'
import { DemandDriversTab } from '../components/forecasting/DemandDriversTab'
import { DataAnalysisTab } from '../components/forecasting/DataAnalysisTab'
import { DataPreprocessingTab } from '../components/forecasting/DataPreprocessingTab'
import { ModelTrainingTab } from '../components/forecasting/ModelTrainingTab'
import { DriftTab } from '../components/forecasting/DriftTab'
import { StaffingImpactTab } from '../components/forecasting/StaffingImpactTab'
import { ModelPerformanceTab } from '../components/forecasting/ModelPerformanceTab'

const SECTION_TITLES: Record<string, string> = {
  'demand-drivers': 'Demand Drivers & Feature Mapping',
  'data-analysis': 'Data Analysis',
  'data-preprocessing': 'Data Pre-processing',
  'model-training': 'Model Training',
  'forecast-explorer': 'Forecast Explorer',
  'drift-monitoring': 'Drift Monitoring',
  'staffing-impact': 'Staffing Impact',
  'model-performance': 'Model Performance',
}

const NO_SERIES_SELECT_SECTIONS = new Set(['model-training', 'model-performance'])

export default function LaborForecasting() {
  const { section = 'demand-drivers' } = useParams<{ section: string }>()
  const { options, seriesKey, setSeriesKey } = useSeriesOptions()
  const navigate = useNavigate()

  const stepIndex = LABOR_FORECASTING_SECTIONS.findIndex((s) => s.slug === section)
  const prevStep = stepIndex > 0 ? LABOR_FORECASTING_SECTIONS[stepIndex - 1] : null
  const nextStep = stepIndex >= 0 && stepIndex < LABOR_FORECASTING_SECTIONS.length - 1 ? LABOR_FORECASTING_SECTIONS[stepIndex + 1] : null

  return (
    <PageContainer title={`Labor Forecasting - ${SECTION_TITLES[section] ?? section}`}>
      {!NO_SERIES_SELECT_SECTIONS.has(section) && (
        <div className="flex justify-end">
          <SeriesSelect options={options} value={seriesKey} onChange={setSeriesKey} />
        </div>
      )}

      {section === 'forecast-explorer' && <ForecastExplorerTab seriesOptions={options} seriesKey={seriesKey} />}
      {section === 'demand-drivers' && <DemandDriversTab seriesKey={seriesKey} />}
      {section === 'data-analysis' && <DataAnalysisTab seriesKey={seriesKey} />}
      {section === 'data-preprocessing' && <DataPreprocessingTab seriesKey={seriesKey} />}
      {section === 'model-training' && <ModelTrainingTab />}
      {section === 'drift-monitoring' && <DriftTab seriesKey={seriesKey} />}
      {section === 'staffing-impact' && <StaffingImpactTab seriesKey={seriesKey} />}
      {section === 'model-performance' && <ModelPerformanceTab />}

      {stepIndex >= 0 && (
        <div className="flex items-center justify-between border-t border-[var(--color-border)] pt-4">
          {prevStep ? (
            <button
              onClick={() => navigate(`/labor-forecasting/${prevStep.slug}`)}
              className="flex items-center gap-1 rounded-lg border border-[var(--color-border)] px-4 py-2 text-xs font-semibold text-[var(--color-text-muted)] hover:bg-[var(--color-surface-2)] hover:text-[var(--color-text)]"
            >
              <ChevronLeft size={14} /> {prevStep.label}
            </button>
          ) : <span />}
          <span className="text-xs text-[var(--color-text-muted)]">
            Step {stepIndex + 1} of {LABOR_FORECASTING_SECTIONS.length}
          </span>
          {nextStep ? (
            <button
              onClick={() => navigate(`/labor-forecasting/${nextStep.slug}`)}
              className="flex items-center gap-1 rounded-lg bg-[var(--color-primary)] px-4 py-2 text-xs font-semibold text-white hover:bg-[var(--color-primary-dark)]"
            >
              Next: {nextStep.label} <ChevronRight size={14} />
            </button>
          ) : <span />}
        </div>
      )}
    </PageContainer>
  )
}

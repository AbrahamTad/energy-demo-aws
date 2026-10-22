
import { useEffect, useState } from 'react'

// FastAPI records have IDs; Lambda sample records do not.
type EnergyRecord = {
  id?: number
  source: string
  production: number
  unit: string
}

// Shared response structure for FastAPI and Lambda.
type EnergyResponse = {
  project: string
  status: string
  records: EnergyRecord[]
}

function App() {
  const dataSource = import.meta.env.MODE === 'floci'
    ? 'Lambda sample data (local Floci API Gateway)'
    : import.meta.env.MODE === 'aws'
      ? 'Lambda sample data (AWS)'
      : 'PostgreSQL'
  const [energy, setEnergy] = useState<EnergyResponse | null>(null)
  const [error, setError] = useState('')

  // Vite forwards this request to the API selected by the development mode.
  useEffect(() => {
    fetch('/api/energy')
      .then((response) => {
        if (!response.ok) {
          throw new Error('Failed to fetch energy data')
        }
        return response.json()
      })
      .then((data: EnergyResponse) => setEnergy(data))
      .catch(() => setError('Cannot connect to the API'))
  }, [])

  if (error) return <p>{error}</p>
  if (!energy) return <p>Loading energy data...</p>

  return (
    <main>
      <h1>⚡ Energy Dashboard</h1>
      <h2>{energy.project}</h2>

      <div className="energy-grid">
        {energy.records.map((record) => (
          <div className="energy-card" key={record.id ?? record.source}>
            <h3>{record.source}</h3>
            <p className="production">
              {record.production} {record.unit}
            </p>
          </div>
        ))}
      </div>

      <p>API Status: {energy.status}</p>
      <p>Data source: {dataSource}</p>
    </main>
  )
}

export default App

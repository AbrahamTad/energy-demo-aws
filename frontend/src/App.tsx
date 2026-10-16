
import { useEffect, useState } from 'react'

// Structure of one PostgreSQL record
type EnergyRecord = {
  id: number
  source: string
  production: number
  unit: string
}

// Structure of the FastAPI response
type EnergyResponse = {
  project: string
  status: string
  records: EnergyRecord[]
}

function App() {
  const [energy, setEnergy] = useState<EnergyResponse | null>(null)
  const [error, setError] = useState('')

  // Get energy records from Python FastAPI
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
          <div className="energy-card" key={record.id}>
            <h3>{record.source}</h3>
            <p className="production">
              {record.production} {record.unit}
            </p>
          </div>
        ))}
      </div>

      <p>API Status: {energy.status}</p>
      <p>Data source: PostgreSQL</p>
    </main>
  )
}

export default App

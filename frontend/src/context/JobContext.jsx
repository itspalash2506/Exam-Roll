import { createContext, useContext, useState, useCallback } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { getJobs } from '../api/client.js'

const JobContext = createContext(null)

export function JobProvider({ children }) {
  const [currentJob, setCurrentJob] = useState(null)
  const queryClient = useQueryClient()

  const { data: jobs = [], isLoading } = useQuery({
    queryKey: ['jobs'],
    queryFn: async () => {
      const res = await getJobs()
      return res.data ?? []
    },
    staleTime: 30_000,
  })

  const refreshJobs = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['jobs'] })
  }, [queryClient])

  return (
    <JobContext.Provider value={{ jobs, currentJob, setCurrentJob, refreshJobs, isLoading }}>
      {children}
    </JobContext.Provider>
  )
}

export function useJobContext() {
  const ctx = useContext(JobContext)
  if (!ctx) throw new Error('useJobContext must be used within JobProvider')
  return ctx
}

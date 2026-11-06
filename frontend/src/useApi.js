import { useEffect, useState } from 'react'
import { get } from './api'

/** Fetch several endpoints in parallel and re-run whenever `deps` change. */
export function useApi(requests, deps) {
  const [state, setState] = useState({ data: null, loading: true, error: '' })

  useEffect(() => {
    let cancelled = false
    if (!requests) return undefined
    setState((s) => ({ ...s, loading: true, error: '' }))
    const entries = Object.entries(requests)
    Promise.all(entries.map(([, [path, params]]) => get(path, params)))
      .then((results) => {
        if (cancelled) return
        setState({ data: Object.fromEntries(entries.map(([k], i) => [k, results[i]])), loading: false, error: '' })
      })
      .catch((e) => { if (!cancelled) setState((s) => ({ ...s, loading: false, error: e.message })) })
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  return state
}

/** Intake: one box, one submit. The request is owned before this screen returns. */

import { FormEvent, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError } from '../lib/api'
import { Button, Callout, Card, ErrorNote } from '../components/primitives'

const EXAMPLE = 'Can someone introduce us to the VP of Security at Apex Logistics?'

export default function IntakePage() {
  const navigate = useNavigate()
  const [ask, setAsk] = useState('')
  const [requester, setRequester] = useState('')
  const [suggestions, setSuggestions] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    const term = requester.trim()
    if (term.length < 2) {
      setSuggestions([])
      return
    }
    let cancelled = false
    const handle = window.setTimeout(() => {
      api
        .search(term, 10)
        .then((result) => {
          if (cancelled) return
          setSuggestions(result.people.filter((person) => person.is_internal).map((person) => person.display_name))
        })
        .catch(() => setSuggestions([]))
    }, 200)
    return () => {
      cancelled = true
      window.clearTimeout(handle)
    }
  }, [requester])

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (busy) return
    setBusy(true)
    setError('')
    try {
      const result = await api.startIntake({ raw_ask: ask.trim(), requester_name: requester.trim() })
      navigate(`/requests/${result.request.request_id}?saved=1`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
      setBusy(false)
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">New introduction request</h1>
        <p className="mt-1 text-sm text-muted">
          Paste the ask as it was written. Halyard saves and assigns it the moment you submit, then works out
          what it means — nothing is lost if you leave this screen.
        </p>
      </div>

      <Card>
        <form onSubmit={submit} className="space-y-4">
          <div>
            <label htmlFor="ask" className="text-sm font-medium">
              Introduction request
            </label>
            <textarea
              id="ask"
              required
              rows={3}
              value={ask}
              disabled={busy}
              onChange={(event) => setAsk(event.target.value)}
              placeholder={EXAMPLE}
              className="mt-1 w-full rounded-md border border-line px-3 py-2 text-sm disabled:bg-slate-50"
            />
            <button
              type="button"
              disabled={busy}
              onClick={() => setAsk(EXAMPLE)}
              className="mt-1 text-xs text-accent hover:underline"
            >
              Use example
            </button>
          </div>
          <div>
            <label htmlFor="requester" className="text-sm font-medium">
              Requested by
            </label>
            <input
              id="requester"
              required
              list="requester-options"
              autoComplete="off"
              value={requester}
              disabled={busy}
              onChange={(event) => setRequester(event.target.value)}
              placeholder="Who is asking"
              className="mt-1 w-full rounded-md border border-line px-3 py-2 text-sm disabled:bg-slate-50"
            />
            <datalist id="requester-options">
              {suggestions.map((name) => (
                <option key={name} value={name} />
              ))}
            </datalist>
            <p className="mt-1 text-xs text-muted">
              This request is assigned immediately. You can confirm or change the owner during review.
            </p>
          </div>
          {error && <ErrorNote error={error} />}
          {busy && (
            <Callout level="healthy" title="Saving and analysing…">
              The request is stored and owned first; target, account and routes follow.
            </Callout>
          )}
          <Button type="submit" disabled={busy || !ask.trim() || !requester.trim()}>
            {busy ? 'Saving…' : 'Save & analyze'}
          </Button>
        </form>
      </Card>
    </div>
  )
}

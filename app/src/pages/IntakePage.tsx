/** Intake: one box, one submit. The request is owned before this screen returns. */

import { FormEvent, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError } from '../lib/api'
import { Button, Card, ErrorNote } from '../components/primitives'

const EXAMPLE = 'Can someone introduce us to the VP of Security at Apex Logistics?'

export default function IntakePage() {
  const navigate = useNavigate()
  const [ask, setAsk] = useState('')
  const [requester, setRequester] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const result = await api.startIntake({ raw_ask: ask.trim(), requester_name: requester.trim() })
      navigate(`/requests/${result.request.request_id}`)
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
          Paste the ask as it was written. Halyard records and assigns it immediately, then works out what it
          means — nothing is lost if you leave this screen.
        </p>
      </div>

      <Card>
        <form onSubmit={submit} className="space-y-4">
          <div>
            <label htmlFor="ask" className="text-sm font-medium">
              The ask
            </label>
            <textarea
              id="ask"
              required
              rows={3}
              value={ask}
              onChange={(event) => setAsk(event.target.value)}
              placeholder={EXAMPLE}
              className="mt-1 w-full rounded-md border border-line px-3 py-2 text-sm"
            />
            <button
              type="button"
              onClick={() => setAsk(EXAMPLE)}
              className="mt-1 text-xs text-accent hover:underline"
            >
              use the example ask
            </button>
          </div>
          <div>
            <label htmlFor="requester" className="text-sm font-medium">
              Requester
            </label>
            <input
              id="requester"
              required
              value={requester}
              onChange={(event) => setRequester(event.target.value)}
              placeholder="who is asking"
              className="mt-1 w-full rounded-md border border-line px-3 py-2 text-sm"
            />
            <p className="mt-1 text-xs text-muted">
              An owner is resolved on the server: the configured triage owner if there is one, otherwise the
              requester. A request is never stored without one.
            </p>
          </div>
          {error && <ErrorNote error={error} />}
          <Button type="submit" disabled={busy}>
            {busy ? 'Recording…' : 'Record request'}
          </Button>
        </form>
      </Card>
    </div>
  )
}

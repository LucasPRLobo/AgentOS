/** SessionDashboard — real-time monitoring of a running session. */

import { useCallback, useEffect, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import {
  getSession,
  getSessionEvents,
  stopSession,
  EventStreamClient,
} from '../api/client';
import type { EventResponse, SessionDetail } from '../api/types';
import DagGraph from '../components/DagGraph';
import EventLog from '../components/EventLog';

const STATE_BADGES: Record<string, string> = {
  CREATED: 'bg-gray-700 text-gray-300',
  RUNNING: 'bg-blue-600 text-white',
  SUCCEEDED: 'bg-green-600 text-white',
  FAILED: 'bg-red-600 text-white',
  STOPPED: 'bg-yellow-600 text-white',
};

export default function SessionDashboard() {
  const { id } = useParams<{ id: string }>();
  const [session, setSession] = useState<SessionDetail | null>(null);
  const [events, setEvents] = useState<EventResponse[]>([]);
  const [elapsed, setElapsed] = useState(0);
  const streamRef = useRef<EventStreamClient | null>(null);
  const startTime = useRef(Date.now());

  // Fetch initial session + events
  useEffect(() => {
    if (!id) return;
    getSession(id).then(setSession);
    getSessionEvents(id).then(setEvents);
  }, [id]);

  // WebSocket event stream
  useEffect(() => {
    if (!id) return;
    const client = new EventStreamClient();
    streamRef.current = client;

    client.subscribe('*', (event) => {
      setEvents((prev) => {
        // Deduplicate by run_id+seq
        const key = `${event.run_id}-${event.seq}`;
        if (prev.some((e) => `${e.run_id}-${e.seq}` === key)) return prev;
        return [...prev, event];
      });
    });

    client.connect(id);
    return () => client.disconnect();
  }, [id]);

  // Elapsed time ticker
  useEffect(() => {
    const interval = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startTime.current) / 1000));
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  // Poll session state
  useEffect(() => {
    if (!id) return;
    const interval = setInterval(() => {
      getSession(id).then(setSession);
    }, 2000);
    return () => clearInterval(interval);
  }, [id]);

  const handleStop = useCallback(async () => {
    if (id) {
      await stopSession(id);
      getSession(id).then(setSession);
    }
  }, [id]);

  if (!session) return <div className="text-gray-400">Loading session...</div>;

  // Build DAG nodes from events
  const dagNodes = session.agents.map((agent) => {
    const taskEvents = events.filter(
      (e) =>
        (e.event_type === 'TaskStarted' || e.event_type === 'TaskFinished') &&
        typeof e.payload.task_name === 'string' &&
        (e.payload.task_name as string).toLowerCase().includes(agent.role),
    );
    const finished = taskEvents.find(
      (e) => e.event_type === 'TaskFinished',
    );
    let state: 'pending' | 'running' | 'succeeded' | 'failed' = 'pending';
    if (finished) {
      state = (finished.payload.state as string) === 'SUCCEEDED' ? 'succeeded' : 'failed';
    } else if (taskEvents.length > 0) {
      state = 'running';
    }
    return { id: agent.role, label: agent.role, state };
  });

  const badgeClass = STATE_BADGES[session.state] ?? STATE_BADGES.CREATED;

  return (
    <div className="max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-4">
          <h2 className="text-xl font-bold text-white">
            Session {session.session_id.slice(0, 8)}...
          </h2>
          <span className={`px-3 py-1 rounded-full text-xs font-semibold ${badgeClass}`}>
            {session.state}
          </span>
          <span className="text-sm text-gray-500">{elapsed}s elapsed</span>
        </div>
        {session.state === 'RUNNING' && (
          <button
            onClick={handleStop}
            className="bg-red-600 hover:bg-red-500 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
          >
            Stop Session
          </button>
        )}
      </div>

      {/* DAG visualization */}
      <div className="bg-gray-900 border border-gray-800 rounded-lg px-6 py-2 mb-6">
        <DagGraph nodes={dagNodes} />
      </div>

      {/* Main content: events */}
      <div className="bg-gray-900 border border-gray-800 rounded-lg p-4" style={{ height: '500px' }}>
        <h3 className="text-sm font-semibold text-gray-400 uppercase mb-3">
          Event Log ({events.length} events)
        </h3>
        <div style={{ height: 'calc(100% - 2rem)' }}>
          <EventLog events={events} />
        </div>
      </div>

      {session.error && (
        <div className="mt-4 bg-red-900/20 border border-red-800 rounded-lg p-4 text-red-300 text-sm">
          Error: {session.error}
        </div>
      )}
    </div>
  );
}

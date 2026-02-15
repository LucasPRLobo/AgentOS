/** SessionDashboard — real-time monitoring of a running session. */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import {
  getSession,
  getSessionEvents,
  stopSession,
  EventStreamClient,
} from '../api/client';
import type { EventResponse, SessionDetail } from '../api/types';
import ArtifactBrowser from '../components/ArtifactBrowser';
import DagGraph from '../components/DagGraph';
import EventLog from '../components/EventLog';

const STATE_BADGES: Record<string, string> = {
  CREATED: 'bg-gray-700 text-gray-300',
  RUNNING: 'bg-blue-600 text-white',
  SUCCEEDED: 'bg-green-600 text-white',
  FAILED: 'bg-red-600 text-white',
  STOPPED: 'bg-yellow-600 text-white',
};

/** Estimate token cost from events (rough heuristic). */
function estimateCost(events: EventResponse[]): {
  totalTokens: number;
  toolCalls: number;
} {
  let totalTokens = 0;
  let toolCalls = 0;

  for (const e of events) {
    if (e.event_type === 'ToolCallFinished') {
      toolCalls++;
    }
    if (
      e.event_type === 'LMResponseReceived' ||
      e.event_type === 'AgentStepCompleted'
    ) {
      const tokens =
        (e.payload.tokens_used as number) ||
        (e.payload.prompt_tokens as number ?? 0) +
          (e.payload.completion_tokens as number ?? 0);
      if (tokens > 0) totalTokens += tokens;
    }
  }

  return { totalTokens, toolCalls };
}

export default function SessionDashboard() {
  const { id } = useParams<{ id: string }>();
  const [session, setSession] = useState<SessionDetail | null>(null);
  const [events, setEvents] = useState<EventResponse[]>([]);
  const [elapsed, setElapsed] = useState(0);
  const [activeTab, setActiveTab] = useState<'events' | 'artifacts'>('events');
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

  const cost = useMemo(() => estimateCost(events), [events]);

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
        <div className="flex items-center gap-4">
          {/* Cost/token display */}
          <div className="flex gap-3 text-xs text-gray-500">
            {cost.totalTokens > 0 && (
              <span>{cost.totalTokens.toLocaleString()} tokens</span>
            )}
            <span>{cost.toolCalls} tool calls</span>
            <span>{events.length} events</span>
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
      </div>

      {/* DAG visualization */}
      <div className="bg-gray-900 border border-gray-800 rounded-lg px-6 py-2 mb-6">
        <DagGraph nodes={dagNodes} />
      </div>

      {/* Tabbed content: Events / Artifacts */}
      <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden" style={{ height: '500px' }}>
        {/* Tab bar */}
        <div className="flex border-b border-gray-800">
          <button
            onClick={() => setActiveTab('events')}
            className={`px-4 py-2 text-xs font-semibold uppercase transition-colors ${
              activeTab === 'events'
                ? 'text-blue-400 border-b-2 border-blue-400'
                : 'text-gray-500 hover:text-gray-300'
            }`}
          >
            Event Log ({events.length})
          </button>
          <button
            onClick={() => setActiveTab('artifacts')}
            className={`px-4 py-2 text-xs font-semibold uppercase transition-colors ${
              activeTab === 'artifacts'
                ? 'text-blue-400 border-b-2 border-blue-400'
                : 'text-gray-500 hover:text-gray-300'
            }`}
          >
            Artifacts
          </button>
        </div>

        {/* Tab content */}
        <div className="p-4" style={{ height: 'calc(100% - 2.5rem)' }}>
          {activeTab === 'events' ? (
            <EventLog events={events} />
          ) : (
            <ArtifactBrowser events={events} />
          )}
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

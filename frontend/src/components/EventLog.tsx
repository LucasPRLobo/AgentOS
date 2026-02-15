/** EventLog — scrollable, filterable event stream. */

import { useEffect, useRef, useState } from 'react';
import type { EventResponse } from '../api/types';

const EVENT_COLORS: Record<string, string> = {
  SessionStarted: 'text-purple-400',
  SessionFinished: 'text-purple-400',
  RunStarted: 'text-blue-400',
  RunFinished: 'text-blue-400',
  TaskStarted: 'text-cyan-400',
  TaskFinished: 'text-cyan-400',
  AgentStepStarted: 'text-green-400',
  AgentStepFinished: 'text-green-400',
  ToolCallStarted: 'text-yellow-400',
  ToolCallFinished: 'text-yellow-400',
  LMCallStarted: 'text-gray-400',
  LMCallFinished: 'text-gray-400',
  BudgetExceeded: 'text-red-400',
  PolicyDecision: 'text-orange-400',
};

interface Props {
  events: EventResponse[];
}

export default function EventLog({ events }: Props) {
  const [filter, setFilter] = useState('');
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [events.length]);

  const filtered = filter
    ? events.filter(
        (e) =>
          e.event_type.toLowerCase().includes(filter.toLowerCase()) ||
          JSON.stringify(e.payload).toLowerCase().includes(filter.toLowerCase()),
      )
    : events;

  return (
    <div className="flex flex-col h-full">
      <input
        type="text"
        placeholder="Filter events..."
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        className="bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm text-gray-200 mb-2 focus:outline-none focus:border-blue-500"
      />
      <div className="flex-1 overflow-y-auto space-y-1 font-mono text-xs">
        {filtered.length === 0 && (
          <div className="flex items-center justify-center h-full text-gray-600 text-sm">
            {filter ? 'No events match your filter.' : 'Waiting for events...'}
          </div>
        )}
        {filtered.map((event, i) => {
          const color = EVENT_COLORS[event.event_type] ?? 'text-gray-500';
          return (
            <div key={`${event.run_id}-${event.seq}-${i}`} className="flex gap-2 py-0.5">
              <span className="text-gray-600 w-8 text-right shrink-0">
                {event.seq}
              </span>
              <span className={`w-40 shrink-0 ${color}`}>
                {event.event_type}
              </span>
              <span className="text-gray-400 truncate">
                {JSON.stringify(event.payload)}
              </span>
            </div>
          );
        })}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}

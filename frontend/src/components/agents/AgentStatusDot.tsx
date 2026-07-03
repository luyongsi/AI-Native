'use client';

interface AgentStatusDotProps {
  status: 'running' | 'idle' | 'waiting' | 'error';
  size?: 'sm' | 'md';
}

const dotColors: Record<string, string> = {
  running: 'bg-emerald-500',
  idle: 'bg-slate-300',
  waiting: 'bg-amber-400',
  error: 'bg-red-500',
};

export default function AgentStatusDot({ status, size = 'sm' }: AgentStatusDotProps) {
  const sizeClass = size === 'md' ? 'w-2 h-2' : 'w-1.5 h-1.5';
  return <span className={`${sizeClass} rounded-full flex-shrink-0 ${dotColors[status] || 'bg-slate-300'}`} />;
}

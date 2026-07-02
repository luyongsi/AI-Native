'use client';

import { useEffect, useRef } from 'react';
import { useActivityStream } from '@/hooks/useActivityStream';
import { ConnectionStatus } from '@/lib/activity';
import type { Activity } from '@/lib/activity';

interface ActivityStreamProps {
  reqId?: string;
  autoReconnect?: boolean;
  reconnectDelay?: number;
  maxRetries?: number;
  onActivityUpdate?: (activity: Activity) => void;
}

const statusColors: Record<string, string> = {
  running: 'bg-emerald-50 border-emerald-200 text-emerald-700',
  idle: 'bg-slate-50 border-slate-200 text-slate-700',
  waiting: 'bg-amber-50 border-amber-200 text-amber-700',
  error: 'bg-red-50 border-red-200 text-red-700',
  success: 'bg-emerald-50 border-emerald-200 text-emerald-700',
  pending: 'bg-slate-50 border-slate-200 text-slate-700',
};

const eventTypeLabels: Record<string, string> = {
  status: '状态',
  progress: '进度',
  artifact: '产物',
  message: '消息',
};

const eventTypeColors: Record<string, string> = {
  status: 'text-blue-600 bg-blue-50 border-blue-100',
  progress: 'text-emerald-600 bg-emerald-50 border-emerald-100',
  artifact: 'text-purple-600 bg-purple-50 border-purple-100',
  message: 'text-slate-600 bg-slate-100 border-slate-200',
};

function formatTime(timestamp: string): string {
  try {
    const date = new Date(timestamp);
    const hours = String(date.getHours()).padStart(2, '0');
    const minutes = String(date.getMinutes()).padStart(2, '0');
    const seconds = String(date.getSeconds()).padStart(2, '0');
    return `${hours}:${minutes}:${seconds}`;
  } catch {
    return timestamp;
  }
}

function ConnectionIndicator({ status }: { status: ConnectionStatus }) {
  const statusConfig: Record<ConnectionStatus, { label: string; color: string; dot: string }> = {
    [ConnectionStatus.Connected]: {
      label: '已连接',
      color: 'text-emerald-600',
      dot: 'bg-emerald-500',
    },
    [ConnectionStatus.Connecting]: {
      label: '连接中',
      color: 'text-amber-600',
      dot: 'bg-amber-500 animate-pulse',
    },
    [ConnectionStatus.Disconnected]: {
      label: '已断开',
      color: 'text-slate-500',
      dot: 'bg-slate-400',
    },
    [ConnectionStatus.Error]: {
      label: '错误',
      color: 'text-red-600',
      dot: 'bg-red-500',
    },
  };

  const config = statusConfig[status];

  return (
    <div className={`flex items-center gap-2 text-sm font-medium ${config.color}`}>
      <span className={`w-2 h-2 rounded-full ${config.dot}`} />
      {config.label}
    </div>
  );
}

function ProgressBar({ percentage, label }: { percentage: number; label?: string }) {
  const clampedPercentage = Math.min(100, Math.max(0, percentage));

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs">
        <span className="text-slate-600">{label || '进度'}</span>
        <span className="text-slate-500 font-medium">{clampedPercentage}%</span>
      </div>
      <div className="w-full h-1.5 bg-slate-200 rounded-full overflow-hidden">
        <div
          className="h-full bg-emerald-500 transition-all duration-300 ease-out"
          style={{ width: `${clampedPercentage}%` }}
        />
      </div>
    </div>
  );
}

function ActivityCard({ activity }: { activity: Activity }) {
  return (
    <div className="p-3 border border-slate-200 rounded-lg bg-white hover:shadow-sm transition-shadow">
      {/* Header */}
      <div className="flex items-start justify-between gap-2 mb-2">
        <div className="flex items-center gap-2 flex-1 min-w-0">
          <span
            className={`text-xs font-medium px-2 py-1 rounded border flex-shrink-0 ${
              eventTypeColors[activity.type] || 'text-slate-600 bg-slate-100 border-slate-200'
            }`}
          >
            {eventTypeLabels[activity.type] || activity.type}
          </span>
          <span className="text-xs font-semibold text-slate-900 truncate">
            {activity.agentName || activity.agentId}
          </span>
        </div>
        <span className="text-xs text-slate-400 flex-shrink-0">{formatTime(activity.timestamp)}</span>
      </div>

      {/* Status Badge */}
      {activity.status && (
        <div className="mb-2">
          <span
            className={`inline-block text-xs px-2 py-1 rounded border ${
              statusColors[activity.status] || statusColors.pending
            }`}
          >
            {activity.status}
          </span>
        </div>
      )}

      {/* Message */}
      {activity.message && (
        <p className="text-sm text-slate-700 mb-2 break-words">{activity.message}</p>
      )}

      {/* Progress */}
      {activity.progress && (
        <div className="mb-2">
          <ProgressBar
            percentage={activity.progress.percentage}
            label={activity.progress.step}
          />
          {activity.progress.current !== undefined && activity.progress.total !== undefined && (
            <span className="text-xs text-slate-500">
              {activity.progress.current} / {activity.progress.total}
            </span>
          )}
        </div>
      )}

      {/* Artifact */}
      {activity.artifact && (
        <div className="bg-slate-50 border border-slate-200 rounded p-2 text-xs">
          <div className="font-medium text-slate-700 mb-1">{activity.artifact.type}</div>
          {activity.artifact.path && (
            <div className="text-slate-600 mb-1 font-mono text-[10px] break-all">
              {activity.artifact.path}
            </div>
          )}
          {activity.artifact.content && (
            <div className="text-slate-600 max-h-24 overflow-y-auto font-mono text-[10px] whitespace-pre-wrap break-words">
              {activity.artifact.content}
            </div>
          )}
        </div>
      )}

      {/* Details */}
      {activity.details && Object.keys(activity.details).length > 0 && (
        <div className="mt-2 text-xs text-slate-600 bg-slate-50 p-2 rounded border border-slate-200">
          {Object.entries(activity.details).map(([key, value]) => (
            <div key={key} className="flex gap-2">
              <span className="font-medium text-slate-700 flex-shrink-0">{key}:</span>
              <span className="text-slate-600 break-all">
                {typeof value === 'object' ? JSON.stringify(value) : String(value)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function ActivityStream({
  reqId,
  autoReconnect = true,
  reconnectDelay = 3000,
  maxRetries = 5,
  onActivityUpdate,
}: ActivityStreamProps) {
  const { activities, isConnected, error, lastUpdate } = useActivityStream({
    reqId,
    autoReconnect,
    reconnectDelay,
    maxRetries,
  });

  const containerRef = useRef<HTMLDivElement>(null);
  const lastActivityCountRef = useRef(activities.length);

  // Auto-scroll to latest activity
  useEffect(() => {
    if (activities.length > lastActivityCountRef.current && containerRef.current) {
      const { scrollHeight } = containerRef.current;
      containerRef.current.scrollTop = scrollHeight;
      lastActivityCountRef.current = activities.length;
    }
  }, [activities]);

  // Notify on new activity
  useEffect(() => {
    if (activities.length > lastActivityCountRef.current) {
      const newActivity = activities[activities.length - 1];
      onActivityUpdate?.(newActivity);
    }
  }, [activities, onActivityUpdate]);

  return (
    <div className="flex flex-col h-full bg-white rounded-lg border border-slate-200">
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-slate-200">
        <h2 className="text-lg font-semibold text-slate-900">Agent 活动流</h2>
        <ConnectionIndicator status={isConnected} />
      </div>

      {/* Error Banner */}
      {error && (
        <div className="px-4 py-3 bg-red-50 border-b border-red-200">
          <p className="text-sm text-red-700">
            <span className="font-medium">连接错误:</span> {error.message}
          </p>
        </div>
      )}

      {/* Activity List */}
      <div
        ref={containerRef}
        className="flex-1 overflow-y-auto p-4 space-y-3"
      >
        {activities.length === 0 ? (
          <div className="flex items-center justify-center h-full text-slate-400">
            <div className="text-center">
              <div className="text-sm mb-1">等待活动中...</div>
              {isConnected === ConnectionStatus.Connected && (
                <div className="text-xs text-slate-500">连接已建立，等待事件...</div>
              )}
            </div>
          </div>
        ) : (
          activities.map((activity) => (
            <ActivityCard key={activity.id} activity={activity} />
          ))
        )}
      </div>

      {/* Footer */}
      {lastUpdate && (
        <div className="px-4 py-2 bg-slate-50 border-t border-slate-200 text-xs text-slate-500">
          最后更新: {formatTime(lastUpdate)}
        </div>
      )}
    </div>
  );
}

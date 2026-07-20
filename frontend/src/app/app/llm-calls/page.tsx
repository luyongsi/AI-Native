'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api';
import type { LLMCallItem } from '@/lib/types';

const PAGE_SIZE = 50;

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function formatRelativeTime(iso: string): string {
  if (!iso) return '-';
  const now = Date.now();
  const then = new Date(iso).getTime();
  const diff = now - then;
  if (diff < 60000) return '<1 min';
  if (diff < 3600000) return Math.floor(diff / 60000) + ' min ago';
  if (diff < 86400000) return Math.floor(diff / 3600000) + 'h ago';
  return Math.floor(diff / 86400000) + 'd ago';
}

function formatTokens(prompt: number, completion: number): string {
  const total = prompt + completion;
  if (total >= 1000) return (total / 1000).toFixed(1) + 'k';
  return String(total);
}

export default function LLMCallsPage() {
  const router = useRouter();
  const [calls, setCalls] = useState<LLMCallItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);

  // Filters
  const [filterAgentId, setFilterAgentId] = useState('');
  const [filterReqId, setFilterReqId] = useState('');
  const [filterTaskType, setFilterTaskType] = useState('');
  const [filterStatus, setFilterStatus] = useState('');

  function doFetch(pageNum: number) {
    setLoading(true);
    setError(null);
    api.getLLMCalls({
      agent_id: filterAgentId || undefined,
      req_id: filterReqId || undefined,
      task_type: filterTaskType || undefined,
      status: filterStatus || undefined,
      limit: PAGE_SIZE,
      offset: pageNum * PAGE_SIZE,
    })
      .then((res) => {
        setCalls(res.items ?? []);
        setTotal(res.total ?? 0);
        setPage(pageNum);
        setLoading(false);
      })
      .catch((err) => {
        console.error('LLM calls fetch error:', err);
        setError(err instanceof Error ? err.message : 'Failed to fetch LLM calls');
        setLoading(false);
      });
  }

  useEffect(() => {
    doFetch(0);
  }, []);

  const handleSearch = () => doFetch(0);
  const handleReset = () => {
    setFilterAgentId('');
    setFilterReqId('');
    setFilterTaskType('');
    setFilterStatus('');
    // reset filters then fetch 鈥?use the fresh values directly
    setLoading(true);
    setError(null);
    api.getLLMCalls({ limit: PAGE_SIZE, offset: 0 })
      .then((res) => {
        setCalls(res.items ?? []);
        setTotal(res.total ?? 0);
        setPage(0);
        setLoading(false);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : 'Failed to fetch LLM calls');
        setLoading(false);
      });
  };

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="p-6 max-w-[1600px] mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-lg font-semibold text-slate-100">LLM 璋冪敤鐩戞帶</h1>
          <p className="text-xs text-slate-400 mt-0.5">
            鎬昏皟鐢ㄦ鏁? {total} 路 鏄剧ず绗?{page * PAGE_SIZE + 1}-{Math.min((page + 1) * PAGE_SIZE, total)} 鏉?
          </p>
        </div>
      </div>

      {/* Filter Bar */}
      <div className="flex flex-wrap gap-2 mb-4 p-3 bg-slate-800 rounded-lg border border-slate-700">
        <input
          type="text"
          placeholder="Agent ID"
          value={filterAgentId}
          onChange={(e) => setFilterAgentId(e.target.value)}
          className="px-2.5 py-1.5 text-xs border border-slate-700 rounded-md w-28 focus:outline-none focus:border-slate-400"
        />
        <input
          type="text"
          placeholder="Req ID"
          value={filterReqId}
          onChange={(e) => setFilterReqId(e.target.value)}
          className="px-2.5 py-1.5 text-xs border border-slate-700 rounded-md w-28 focus:outline-none focus:border-slate-400"
        />
        <input
          type="text"
          placeholder="Task Type"
          value={filterTaskType}
          onChange={(e) => setFilterTaskType(e.target.value)}
          className="px-2.5 py-1.5 text-xs border border-slate-700 rounded-md w-36 focus:outline-none focus:border-slate-400"
        />
        <select
          value={filterStatus}
          onChange={(e) => setFilterStatus(e.target.value)}
          className="px-2.5 py-1.5 text-xs border border-slate-700 rounded-md bg-slate-800 focus:outline-none focus:border-slate-400"
        >
          <option value="">全部状态</option>
          <option value="success">鎴愬姛</option>
          <option value="error">澶辫触</option>
        </select>
        <button
          onClick={handleSearch}
          className="px-4 py-1.5 text-xs font-medium bg-slate-900 text-white rounded-md hover:bg-slate-800"
        >
          鏌ヨ
        </button>
        <button
          onClick={handleReset}
          className="px-4 py-1.5 text-xs text-slate-400 bg-slate-800 border border-slate-700 rounded-md hover:bg-slate-800/50"
        >
          閲嶇疆
        </button>
      </div>

      {/* Content */}
      {loading ? (
        <div className="flex items-center justify-center min-h-[300px]">
          <div className="flex flex-col items-center gap-3">
            <div className="w-8 h-8 border-2 border-slate-700 border-t-slate-600 rounded-full animate-spin" />
            <span className="text-xs text-slate-400">鍔犺浇 LLM 璋冪敤璁板綍涓?..</span>
          </div>
        </div>
      ) : error ? (
        <div className="flex items-center justify-center min-h-[300px]">
          <div className="flex flex-col items-center gap-3">
            <svg className="w-8 h-8 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z" />
            </svg>
            <span className="text-xs text-slate-400">{error}</span>
            <button
              onClick={() => doFetch(page)}
              className="px-3 py-1.5 text-xs text-slate-400 bg-slate-800 border border-slate-700 rounded-lg hover:bg-slate-800/50"
            >
              閲嶈瘯
            </button>
          </div>
        </div>
      ) : (
        /* Table */
        <div className="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-slate-700 bg-slate-800/50/50">
                  <th className="text-left px-4 py-2.5 font-medium text-slate-400">Call ID</th>
                  <th className="text-left px-4 py-2.5 font-medium text-slate-400">Agent</th>
                  <th className="text-left px-4 py-2.5 font-medium text-slate-400">Req ID</th>
                  <th className="text-left px-4 py-2.5 font-medium text-slate-400">Task</th>
                  <th className="text-left px-4 py-2.5 font-medium text-slate-400">Model</th>
                  <th className="text-left px-4 py-2.5 font-medium text-slate-400">Status</th>
                  <th className="text-right px-4 py-2.5 font-medium text-slate-400">Tokens</th>
                  <th className="text-right px-4 py-2.5 font-medium text-slate-400">Duration</th>
                  <th className="text-right px-4 py-2.5 font-medium text-slate-400">Time</th>
                </tr>
              </thead>
              <tbody>
                {calls.length === 0 ? (
                  <tr>
                    <td colSpan={9} className="text-center py-12 text-slate-400">
                      鏆傛棤 LLM 璋冪敤璁板綍
                    </td>
                  </tr>
                ) : (
                  calls.map((call) => (
                    <tr
                      key={call.call_id}
                      onClick={() => router.push('/app/llm-calls/' + call.call_id)}
                      className="border-b border-slate-50 hover:bg-slate-800/50/50 cursor-pointer transition-colors"
                    >
                      <td className="px-4 py-2.5 font-mono text-[11px] text-slate-400">
                        {call.call_id ? call.call_id.slice(0, 12) : '-'}
                      </td>
                      <td className="px-4 py-2.5">
                        <span className="px-1.5 py-0.5 rounded bg-slate-700 text-slate-600 font-medium">
                          {call.agent_id || '-'}
                        </span>
                      </td>
                      <td className="px-4 py-2.5 font-mono text-[11px] text-slate-400">
                        {(call.req_id || '-').slice(0, 12)}
                      </td>
                      <td className="px-4 py-2.5">
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-50 text-blue-700">
                          {call.task_type || '-'}
                        </span>
                      </td>
                      <td className="px-4 py-2.5 text-slate-400">
                        {call.provider ? call.provider + ' / ' + call.model : (call.model || '-')}
                      </td>
                      <td className="px-4 py-2.5">
                        <span className={'text-[10px] px-1.5 py-0.5 rounded font-medium ' + (
                          call.status === 'success' ? 'bg-emerald-50 text-emerald-700' :
                          call.status === 'error' ? 'bg-red-50 text-red-700' :
                          'bg-amber-50 text-amber-700'
                        )}>
                          {call.status === 'success' ? '鎴愬姛' :
                           call.status === 'error' ? '澶辫触' : call.status}
                        </span>
                      </td>
                      <td className="px-4 py-2.5 text-right font-mono text-[11px] text-slate-400" title={'prompt: ' + call.prompt_tokens + ' 路 completion: ' + call.completion_tokens}>
                        {formatTokens(call.prompt_tokens, call.completion_tokens)}
                      </td>
                      <td className="px-4 py-2.5 text-right font-mono text-[11px] text-slate-400">
                        {formatDuration(call.duration_ms)}
                      </td>
                      <td className="px-4 py-2.5 text-right text-slate-400" title={call.started_at}>
                        {formatRelativeTime(call.started_at)}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {total > PAGE_SIZE && (
            <div className="flex items-center justify-between px-4 py-3 border-t border-slate-800">
              <span className="text-xs text-slate-400">
                鍏?{total} 鏉¤褰?路 绗?{page + 1}/{totalPages} 椤?
              </span>
              <div className="flex gap-1">
                <button
                  disabled={page === 0}
                  onClick={() => doFetch(page - 1)}
                  className="px-3 py-1.5 text-xs border border-slate-700 rounded-md disabled:opacity-30 disabled:cursor-not-allowed hover:bg-slate-800/50"
                >
                  涓婁竴椤?
                </button>
                <button
                  disabled={page >= totalPages - 1}
                  onClick={() => doFetch(page + 1)}
                  className="px-3 py-1.5 text-xs border border-slate-700 rounded-md disabled:opacity-30 disabled:cursor-not-allowed hover:bg-slate-800/50"
                >
                  涓嬩竴椤?
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

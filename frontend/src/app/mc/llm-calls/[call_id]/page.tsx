'use client';

import { useState, useEffect, use } from 'react';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api';
import type { LLMCallDetail } from '@/lib/types';

function formatDuration(ms: number): string {
  if (ms < 1000) return ms + 'ms';
  return (ms / 1000).toFixed(1) + 's';
}

function statusBadge(status: string) {
  var colors =
    status === 'success'
      ? 'bg-emerald-50 text-emerald-700'
      : status === 'error'
        ? 'bg-red-50 text-red-700'
        : 'bg-amber-50 text-amber-700';
  var label =
    status === 'success' ? '成功' : status === 'error' ? '失败' : status;
  return (
    <span className={'text-[10px] px-1.5 py-0.5 rounded font-medium ' + colors}>
      {label}
    </span>
  );
}

interface ParsedMessage {
  role: string;
  content: string;
}

function tryParsePrompt(prompt: string | null): ParsedMessage[] {
  if (!prompt) return [];
  try {
    const parsed = JSON.parse(prompt);
    if (Array.isArray(parsed)) return parsed;
    return [];
  } catch {
    return [{ role: 'raw', content: prompt }];
  }
}

export default function LLMCallDetailPage({
  params,
}: {
  params: Promise<{ call_id: string }>;
}) {
  const { call_id } = use(params);
  const router = useRouter();
  const [call, setCall] = useState<LLMCallDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showRawPrompt, setShowRawPrompt] = useState(false);

  useEffect(() => {
    api
      .getLLMCall(call_id)
      .then(setCall)
      .catch((err) =>
        setError(err instanceof Error ? err.message : '获取调用详情失败')
      )
      .finally(() => setLoading(false));
  }, [call_id]);

  if (loading) {
    return (
      <div className="p-6 max-w-[1200px] mx-auto flex items-center justify-center min-h-[400px]">
        <div className="flex flex-col items-center gap-3">
          <div className="w-8 h-8 border-2 border-slate-200 border-t-slate-600 rounded-full animate-spin" />
          <span className="text-xs text-slate-400">加载调用详情...</span>
        </div>
      </div>
    );
  }

  if (error || !call) {
    return (
      <div className="p-6 max-w-[1200px] mx-auto flex items-center justify-center min-h-[400px]">
        <div className="flex flex-col items-center gap-3">
          <svg className="w-8 h-8 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z" />
          </svg>
          <span className="text-xs text-slate-500">{error || '调用记录不存在'}</span>
          <button
            onClick={() => router.push('/mc/llm-calls')}
            className="px-3 py-1.5 text-xs text-slate-600 bg-white border border-slate-200 rounded-lg hover:bg-slate-50"
          >
            返回列表
          </button>
        </div>
      </div>
    );
  }

  var messages = tryParsePrompt(call.prompt);
  var tokenTotal = call.prompt_tokens + call.completion_tokens;
  var promptPct = tokenTotal > 0 ? (call.prompt_tokens / tokenTotal) * 100 : 0;
  var completionPct = tokenTotal > 0 ? (call.completion_tokens / tokenTotal) * 100 : 0;

  var roleClass = function(role: string): string {
    if (role === 'system') return 'bg-purple-50 text-purple-700';
    if (role === 'user') return 'bg-blue-50 text-blue-700';
    if (role === 'assistant') return 'bg-emerald-50 text-emerald-700';
    if (role === 'tool') return 'bg-amber-50 text-amber-700';
    return 'bg-slate-100 text-slate-600';
  };

  return (
    <div className="p-6 max-w-[1200px] mx-auto">
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <button
          onClick={() => router.push('/mc/llm-calls')}
          className="p-1.5 rounded-lg hover:bg-slate-100 text-slate-400 transition-colors"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
          </svg>
        </button>
        <div>
          <h1 className="text-lg font-semibold text-slate-900 flex items-center gap-2">
            <span className="font-mono text-sm text-slate-500">{call.call_id ? call.call_id.slice(0, 12) : '-'}</span>
            {statusBadge(call.status)}
          </h1>
          <p className="text-xs text-slate-500 mt-0.5">LLM 调用详情</p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left: Metadata Card */}
        <div className="lg:col-span-1">
          <div className="bg-white rounded-xl border border-slate-200 p-4 space-y-3">
            <h2 className="text-xs font-semibold text-slate-500 uppercase tracking-wider">调用信息</h2>

            <Field label="Agent" value={call.agent_id || '-'} />
            <Field label="Req ID" value={call.req_id || '-'} mono />
            <Field label="Workflow" value={call.workflow_id || '-'} mono />
            <Field label="Task Type" value={call.task_type || '-'} badge />
            <Field label="Provider" value={call.provider || '-'} />
            <Field label="Model" value={call.model || '-'} mono />
            <Field label="Started" value={call.started_at ? new Date(call.started_at).toLocaleString() : '-'} />
            <Field label="Ended" value={call.ended_at ? new Date(call.ended_at).toLocaleString() : '-'} />
            <Field label="Duration" value={formatDuration(call.duration_ms)} />

            <hr className="border-slate-100" />

            <h2 className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Token 用量</h2>
            <div className="space-y-2">
              <div className="flex justify-between text-xs">
                <span className="text-slate-500">Prompt</span>
                <span className="font-mono text-slate-700">{call.prompt_tokens.toLocaleString()}</span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-slate-500">Completion</span>
                <span className="font-mono text-slate-700">{call.completion_tokens.toLocaleString()}</span>
              </div>
              <div className="flex justify-between text-xs font-semibold">
                <span className="text-slate-700">Total</span>
                <span className="font-mono text-slate-900">{tokenTotal.toLocaleString()}</span>
              </div>
              <div className="flex h-2 rounded-full overflow-hidden bg-slate-100">
                <div
                  className="bg-blue-400 transition-all"
                  style={{ width: promptPct + '%' }}
                  title={'Prompt: ' + call.prompt_tokens}
                />
                <div
                  className="bg-emerald-400 transition-all"
                  style={{ width: completionPct + '%' }}
                  title={'Completion: ' + call.completion_tokens}
                />
              </div>
              <div className="flex gap-3 text-[10px] text-slate-400">
                <span className="flex items-center gap-1">
                  <span className="w-2 h-2 rounded-full bg-blue-400" /> Prompt
                </span>
                <span className="flex items-center gap-1">
                  <span className="w-2 h-2 rounded-full bg-emerald-400" /> Completion
                </span>
              </div>
            </div>

            <div className="flex justify-between text-xs">
              <span className="text-slate-500">Prompt chars</span>
              <span className="font-mono text-slate-700">{call.prompt_chars.toLocaleString()}</span>
            </div>
            <div className="flex justify-between text-xs">
              <span className="text-slate-500">Response chars</span>
              <span className="font-mono text-slate-700">{call.response_chars.toLocaleString()}</span>
            </div>

            {call.error_type && (
              <>
                <hr className="border-slate-100" />
                <div className="p-3 rounded-lg bg-red-50 border border-red-100">
                  <div className="text-[10px] font-semibold text-red-700 mb-1">{call.error_type}</div>
                  <div className="text-xs text-red-600">{call.error_message || '-'}</div>
                </div>
              </>
            )}
          </div>
        </div>

        {/* Right: Prompt + Response */}
        <div className="lg:col-span-2 space-y-6">
          {/* Prompt */}
          <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
            <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100 bg-slate-50/50">
              <h2 className="text-xs font-semibold text-slate-700">
                Prompt ({messages.length} messages)
              </h2>
              <button
                onClick={() => setShowRawPrompt(!showRawPrompt)}
                className="text-[10px] px-2 py-1 rounded border border-slate-200 text-slate-500 hover:bg-slate-100"
              >
                {showRawPrompt ? 'Messages' : 'Raw JSON'}
              </button>
            </div>
            <div className="p-4 max-h-[600px] overflow-y-auto">
              {showRawPrompt ? (
                <pre className="text-xs font-mono text-slate-700 whitespace-pre-wrap break-all bg-slate-50 rounded-lg p-3 max-h-[500px] overflow-auto">
                  {call.prompt || '(empty)'}
                </pre>
              ) : (
                <div className="space-y-3">
                  {messages.map((msg, i) => (
                    <div key={i} className="rounded-lg border border-slate-100 overflow-hidden">
                      <div className="px-3 py-1.5 bg-slate-50 border-b border-slate-50">
                        <span className={'text-[10px] font-semibold uppercase px-1.5 py-0.5 rounded ' + roleClass(msg.role)}>
                          {msg.role}
                        </span>
                      </div>
                      <pre className="p-3 text-xs text-slate-700 whitespace-pre-wrap break-all">
                        {typeof msg.content === 'string' ? msg.content : JSON.stringify(msg.content, null, 2)}
                      </pre>
                    </div>
                  ))}
                  {messages.length === 0 && (
                    <div className="text-xs text-slate-400 py-8 text-center">无 Prompt 内容</div>
                  )}
                </div>
              )}
            </div>
          </div>

          {/* Response */}
          <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
            <div className="px-4 py-3 border-b border-slate-100 bg-slate-50/50">
              <h2 className="text-xs font-semibold text-slate-700">Response</h2>
            </div>
            <div className="p-4">
              {call.response ? (
                <pre className="text-xs font-mono text-slate-700 whitespace-pre-wrap break-all bg-slate-50 rounded-lg p-3 max-h-[600px] overflow-y-auto">
                  {call.response}
                </pre>
              ) : (
                <div className="text-xs text-slate-400 py-8 text-center">
                  {call.status === 'error' ? '调用失败，无响应内容' : '无 Response 内容'}
                </div>
              )}
            </div>
          </div>

          {/* Response Preview (if long) */}
          {call.response_preview && call.response && call.response.length > 500 && (
            <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
              <div className="px-4 py-3 border-b border-slate-100 bg-slate-50/50">
                <h2 className="text-xs font-semibold text-slate-700">Response Preview (前 500 字符)</h2>
              </div>
              <div className="p-4">
                <pre className="text-xs font-mono text-slate-500 whitespace-pre-wrap break-all bg-slate-50 rounded-lg p-3">
                  {call.response_preview}
                </pre>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Field({
  label,
  value,
  mono,
  badge,
}: {
  label: string;
  value: string;
  mono?: boolean;
  badge?: boolean;
}) {
  return (
    <div className="flex justify-between items-start gap-2">
      <span className="text-[10px] text-slate-400 flex-shrink-0">{label}</span>
      {badge ? (
        <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-50 text-blue-700">{value}</span>
      ) : (
        <span className={'text-xs text-slate-700 text-right break-all ' + (mono ? 'font-mono text-[11px]' : '')}>
          {value}
        </span>
      )}
    </div>
  );
}

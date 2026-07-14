'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import PrototypeViewer from './PrototypeViewer';
import AnnotationPanel from './AnnotationPanel';
import VersionHistory from './VersionHistory';
import { streamPrototype, type PrototypeSSEHandlers } from '@/services/prototype-sse';

export interface Annotation {
  annotation_id: string;
  element_id: string;
  type: string;
  comment: string;
  position?: { x: number; y: number };
}

interface PrototypeContext {
  req_id: string;
  design_status: string;
  requirement_summary: {
    title: string;
    domain: string;
    acceptance_criteria: string[];
  };
  prototype: {
    has_existing: boolean;
    current_version: number;
    status: string;
    prototype_url: string | null;
    screens: any[];
    annotations: Annotation[];
  };
  revision_context: {
    is_revision: boolean;
    gate1_rejection: any;
  };
}

export default function PrototypeWorkspace({ reqId }: { reqId: string }) {
  const [context, setContext] = useState<PrototypeContext | null>(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [streamMessage, setStreamMessage] = useState('');
  const [streamProgress, setStreamProgress] = useState(0);
  const [prototypeUrl, setPrototypeUrl] = useState<string | null>(null);
  const [currentVersion, setCurrentVersion] = useState(0);
  const [annotations, setAnnotations] = useState<Annotation[]>([]);
  const [htmlAccumulator, setHtmlAccumulator] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [tab, setTab] = useState<'annotate' | 'history'>('annotate');
  const abortRef = useRef<AbortController | null>(null);

  // Load context
  useEffect(() => {
    setLoading(true);
    fetch(`/api/prototype/context/${reqId}`)
      .then((r) => r.json())
      .then((data: PrototypeContext) => {
        setContext(data);
        if (data.prototype.has_existing) {
          setPrototypeUrl(data.prototype.prototype_url);
          setCurrentVersion(data.prototype.current_version);
          setAnnotations(data.prototype.annotations || []);
          if (data.prototype.status === 'confirmed') {
            setConfirmed(true);
          }
        }
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [reqId]);

  // Generate prototype
  const handleGenerate = useCallback(async () => {
    setGenerating(true);
    setError(null);
    setStreamMessage('');
    setStreamProgress(0);
    setHtmlAccumulator('');
    abortRef.current = new AbortController();

    try {
      await streamPrototype(
        '/api/prototype/generate',
        { req_id: reqId, session_id: '' },
        {
          thinking: (data) => setStreamMessage(data.message),
          prototype_update: (data) => {
            setHtmlAccumulator((prev) => prev + data.html_chunk);
            setStreamProgress(data.progress);
          },
          screens: (data) => {
            setStreamMessage(`已生成 ${data.screens?.length || 0} 张截图`);
          },
          done: (data) => {
            setPrototypeUrl(data.prototype_url);
            setCurrentVersion(data.version);
            setStreamMessage('原型生成完成');
            setStreamProgress(1);
          },
          error: (data) => setError(data.message),
        },
        abortRef.current.signal,
      );
    } catch (e: any) {
      if (e.name !== 'AbortError') {
        setError(e.message);
      }
    } finally {
      setGenerating(false);
      // Reload context to get fresh data
      try {
        const res = await fetch(`/api/prototype/context/${reqId}`);
        const data: PrototypeContext = await res.json();
        setContext(data);
        setAnnotations(data.prototype.annotations || []);
      } catch {}
    }
  }, [reqId]);

  // Submit annotations
  const handleAnnotate = useCallback(
    async (newAnnotations: Annotation[]) => {
      setGenerating(true);
      setError(null);
      setStreamMessage('正在处理标注...');
      abortRef.current = new AbortController();

      try {
        await streamPrototype(
          '/api/prototype/annotate',
          { req_id: reqId, session_id: '', annotations: newAnnotations },
          {
            thinking: (data) => setStreamMessage(data.message),
            annotation_parsed: (data) => {
              setStreamMessage(`已解析 ${data.parsed?.length || 0} 条标注`);
            },
            prototype_update: (data) => {
              setHtmlAccumulator((prev) => prev + data.html_chunk);
              setStreamProgress(data.progress);
            },
            done: (data) => {
              setPrototypeUrl(data.prototype_url);
              setCurrentVersion(data.version);
              setAnnotations((prev) => [...prev, ...newAnnotations]);
              setStreamMessage('标注已应用');
            },
            error: (data) => setError(data.message),
          },
          abortRef.current.signal,
        );
      } catch (e: any) {
        if (e.name !== 'AbortError') {
          setError(e.message);
        }
      } finally {
        setGenerating(false);
      }
    },
    [reqId],
  );

  // Confirm prototype
  const handleConfirm = useCallback(async () => {
    setConfirming(true);
    setError(null);
    try {
      const res = await fetch('/api/prototype/confirm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ req_id: reqId, session_id: '' }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || '确认失败');
      }
      setConfirmed(true);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setConfirming(false);
    }
  }, [reqId]);

  // Cancel current operation
  const handleCancel = () => {
    abortRef.current?.abort();
    setGenerating(false);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-400">
        <div className="text-center">
          <div className="animate-spin w-8 h-8 border-2 border-blue-400 border-t-transparent rounded-full mx-auto mb-3" />
          <p className="text-sm">加载原型工作区...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 bg-white border-b">
        <div>
          <h2 className="text-sm font-semibold">
            阶段二：UI原型设计
          </h2>
          <p className="text-xs text-gray-500 mt-0.5">
            {context?.requirement_summary.title || '未命名需求'}
            {' · '}
            v{currentVersion || '?'}
          </p>
        </div>

        <div className="flex items-center gap-2">
          {error && (
            <span className="text-xs text-red-500 max-w-48 truncate" title={error}>
              {error}
            </span>
          )}

          {generating && (
            <>
              <span className="text-xs text-blue-500">
                {streamMessage || '生成中...'}
                {streamProgress > 0 && ` (${Math.round(streamProgress * 100)}%)`}
              </span>
              <button
                onClick={handleCancel}
                className="px-3 py-1 text-xs border rounded hover:bg-gray-100"
              >
                取消
              </button>
            </>
          )}

          {!confirmed && currentVersion > 0 && !generating && (
            <button
              onClick={handleGenerate}
              className="px-3 py-1 text-xs bg-blue-500 text-white rounded hover:bg-blue-600 transition-colors"
            >
              重新生成
            </button>
          )}

          {confirmed ? (
            <span className="px-3 py-1 text-xs bg-green-100 text-green-700 rounded-full">
              已确认定稿
            </span>
          ) : currentVersion > 0 ? (
            <button
              onClick={handleConfirm}
              disabled={confirming}
              className="px-3 py-1 text-xs bg-green-500 text-white rounded hover:bg-green-600 disabled:opacity-50 transition-colors"
            >
              {confirming ? '确认中...' : '确认定稿 →'}
            </button>
          ) : null}

          {context?.revision_context.is_revision && (
            <span className="px-2 py-1 text-xs bg-orange-100 text-orange-700 rounded">
              Gate1 修订
            </span>
          )}
        </div>
      </div>

      {/* Revision guidance */}
      {context?.revision_context.is_revision &&
       context.revision_context.gate1_rejection && (
        <div className="px-4 py-2 bg-orange-50 border-b border-orange-200 text-xs text-orange-700">
          <strong>Gate1 打回意见:</strong>{' '}
          {context.revision_context.gate1_rejection.revision_guidance ||
            '请根据审批意见修改后重新提交'}
        </div>
      )}

      {/* Main content area */}
      <div className="flex-1 flex">
        {/* Empty state / Generate first */}
        {!currentVersion && !generating ? (
          <div className="flex-1 flex items-center justify-center">
            <div className="text-center">
              <div className="text-5xl mb-4">📐</div>
              <h3 className="text-lg font-medium mb-2">开始原型设计</h3>
              <p className="text-sm text-gray-500 mb-4 max-w-md">
                基于 A1 需求草案和 A2 可行性分析，AI 将生成一个可直接预览的高保真 HTML 原型
              </p>
              <button
                onClick={handleGenerate}
                disabled={generating}
                className="px-6 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 disabled:opacity-50 transition-colors"
              >
                开始生成原型
              </button>
            </div>
          </div>
        ) : (
          <>
            {/* Left: Prototype viewer */}
            <div className="flex-1">
              <PrototypeViewer
                reqId={reqId}
                prototypeUrl={prototypeUrl}
                onAnnotate={(elementId, type, comment) => {
                  handleAnnotate([
                    {
                      annotation_id: crypto.randomUUID(),
                      element_id: elementId,
                      type,
                      comment,
                    },
                  ]);
                }}
              />
            </div>

            {/* Right: Tool panel */}
            <div className="w-80 border-l flex flex-col">
              {/* Tabs */}
              <div className="flex border-b">
                <button
                  onClick={() => setTab('annotate')}
                  className={`flex-1 py-2 text-xs font-medium transition-colors ${
                    tab === 'annotate'
                      ? 'text-blue-600 border-b-2 border-blue-500'
                      : 'text-gray-500 hover:text-gray-700'
                  }`}
                >
                  标注工具
                </button>
                <button
                  onClick={() => setTab('history')}
                  className={`flex-1 py-2 text-xs font-medium transition-colors ${
                    tab === 'history'
                      ? 'text-blue-600 border-b-2 border-blue-500'
                      : 'text-gray-500 hover:text-gray-700'
                  }`}
                >
                  版本历史
                </button>
              </div>

              {tab === 'annotate' ? (
                <AnnotationPanel
                  currentVersion={currentVersion}
                  annotations={annotations}
                  onSubmit={handleAnnotate}
                  disabled={generating || confirmed}
                />
              ) : (
                <VersionHistory
                  reqId={reqId}
                  currentVersion={currentVersion}
                  onSelectVersion={(version, url) => {
                    if (url) setPrototypeUrl(url);
                  }}
                />
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

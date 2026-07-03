'use client';

import { useState, useEffect, useRef } from 'react';
import { api } from '@/lib/api';
import type { Requirement } from '@/lib/types';
import { useParams } from 'next/navigation';
import MarkdownRenderer from '@/components/MarkdownRenderer';
import { wsClient } from '@/lib/ws';

// ============================================================
// 对话状态机定义
// ============================================================
type ChatState = 'idle' | 'understanding' | 'asking' | 'generating' | 'waiting';

interface ChatMessage {
  id: string;
  role: 'user' | 'agent' | 'system';
  content: string;
  timestamp: string;
  state?: ChatState;
  options?: string[];
  thinkingProcess?: string[];
}

interface SpecSectionState {
  id: string;
  title: string;
  status: 'pending' | 'generating' | 'done' | 'editing' | 'conflict';
  content: string;
  history: { time: string; action: string }[];
}

// ============================================================
// 主页面组件
// ============================================================
export default function RequirementWorkspacePage() {
  const params = useParams();
  const reqId = params?.id as string || '';

  const [requirement, setRequirement] = useState<(Requirement & { approvals?: any[]; activities?: any[] }) | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Panel widths (30/40/30 split)
  const [leftWidth, setLeftWidth] = useState(30);
  const [rightWidth, setRightWidth] = useState(30);
  const isDragging = useRef<'left' | 'right' | null>(null);

  // Chat state — starts empty, loaded from API
  const [chatInput, setChatInput] = useState('');
  const [chatState, setChatState] = useState<ChatState>('idle');
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatLoading, setChatLoading] = useState(false);

  // Spec state — starts empty, loaded from API
  const [specSections, setSpecSections] = useState<SpecSectionState[]>([]);
  const [activeSection, setActiveSection] = useState<string>('');
  const [specLoading, setSpecLoading] = useState(false);

  // Approval state
  const [showApproval, setShowApproval] = useState(false);
  const [selectedGate, setSelectedGate] = useState(1);
  const [approvalList, setApprovalList] = useState<any[]>([]);
  const [slaTimers, setSlaTimers] = useState<Record<string, number>>({});

  // Live activity log from WebSocket
  const [liveActivity, setLiveActivity] = useState<{agent_id: string; action: string; time: string}[]>([]);

  // Connect WebSocket for real-time agent status updates
  useEffect(() => {
    if (!reqId) return;
    wsClient.connect('dev-token', reqId);
    wsClient.on('agent.status.changed', (data: any) => {
      const agentId = data.agent_id || data.payload?.agent_id || 'agent';
      const msg = data.message || data.payload?.message || 'processing';
      setLiveActivity(prev => [{
        agent_id: agentId,
        action: msg,
        time: new Date().toLocaleTimeString(),
      }, ...prev].slice(0, 10));
      // Refresh requirement periodically for status changes
      api.getRequirement(reqId).then(setRequirement).catch(() => {});
    });
    return () => { wsClient.disconnect(); };
  }, [reqId]);

  // Load approvals when modal is open + SLA countdown
  useEffect(() => {
    if (!reqId || !showApproval) return;
    const loadApprovals = () => {
      api.getApprovals()
        .then((data: any) => {
          const reqApprovals = (data.items || []).filter((a: any) => a.req_id === reqId);
          setApprovalList(reqApprovals);
          const timers: Record<string, number> = {};
          reqApprovals.forEach((a: any) => {
            if (a.status === 'pending' && a.sla_remaining_seconds != null) {
              timers[a.id] = a.sla_remaining_seconds;
            }
          });
          setSlaTimers(timers);
        })
        .catch(() => {});
    };
    loadApprovals();
    const interval = setInterval(loadApprovals, 10000);
    return () => clearInterval(interval);
  }, [reqId, showApproval]);

  // SLA countdown tick every second
  useEffect(() => {
    const interval = setInterval(() => {
      setSlaTimers(prev => {
        const updated: Record<string, number> = {};
        let changed = false;
        for (const [id, secs] of Object.entries(prev)) {
          if (secs <= 0) { updated[id] = 0; changed = true; continue; }
          updated[id] = secs - 1;
          changed = true;
        }
        return changed ? updated : prev;
      });
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  // Load requirement, chat history and spec on mount
  useEffect(() => {
    if (!reqId) return;
    api.getRequirement(reqId)
      .then((data) => setRequirement(data))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));

    // Load chat history
    api.getChatMessages(reqId)
      .then((data) => {
        if (data.messages && data.messages.length > 0) {
          setChatMessages(data.messages.map((m: any) => ({
            ...m,
            role: m.role === 'assistant' ? 'agent' : m.role,
            state: (m.role === 'assistant' || m.role === 'agent') ? 'waiting' as ChatState : undefined,
          })));
          setChatState('waiting');
        } else {
          // No messages yet — show welcome
          setChatState('idle');
          setChatMessages([{
            id: 'welcome',
            role: 'agent',
            content: '你好！我是 AI 需求分析助手。我可以帮你完善需求、生成 Spec 文档、编写验收条件。请告诉我你想做什么？',
            timestamp: new Date().toLocaleTimeString(),
            state: 'waiting',
          }]);
        }
      })
      .catch(() => {
        setChatState('idle');
      });

    // Load spec
    loadSpec();
  }, [reqId]);

  const loadSpec = async () => {
    setSpecLoading(true);
    try {
      const data = await api.getSpecSections(reqId);
      if (data.sections && data.sections.length > 0) {
        setSpecSections(data.sections);
        setActiveSection(data.sections[0]?.id || '');
      }
    } catch (e) {
      // No spec yet — that's ok
    } finally {
      setSpecLoading(false);
    }
  };

  // Resize handlers
  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!isDragging.current) return;
      const totalWidth = window.innerWidth - 224;
      const x = e.clientX - 224;
      const pct = (x / totalWidth) * 100;
      if (isDragging.current === 'left') {
        if (pct > 15 && pct < 45) setLeftWidth(pct);
      } else {
        if (pct > 55 && pct < 85) setRightWidth(100 - pct);
      }
    };
    const handleMouseUp = () => { isDragging.current = null; };
    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, []);

  // Send chat message — streaming API
  const streamRef = useRef('');  // useRef to avoid closure staleness

  const sendMessage = async () => {
    if (!chatInput.trim() || chatLoading) return;
    streamRef.current = '';
    const userMsg: ChatMessage = {
      id: `msg-${Date.now()}`,
      role: 'user',
      content: chatInput,
      timestamp: new Date().toLocaleTimeString(),
    };
    const agentMsgId = `msg-${Date.now() + 1}`;
    setChatMessages((prev) => [...prev, userMsg]);
    setChatInput('');
    setChatState('generating');
    setChatLoading(true);

    // Add empty agent bubble that will be filled by streaming
    const streamingMsg: ChatMessage = {
      id: agentMsgId,
      role: 'agent',
      content: '',
      timestamp: new Date().toLocaleTimeString(),
      state: 'generating',
      thinkingProcess: ['连接 AI 模型...'],
    };
    setChatMessages((prev) => [...prev, streamingMsg]);

    try {
      await api.sendChatMessage(
        reqId,
        userMsg.content,
        'open',
        // onChunk — use ref for real-time update, force re-render via msg counter
        (chunk: string) => {
          streamRef.current += chunk;
          // Use a counter-based approach to force React re-render
          const newContent = streamRef.current;
          setChatMessages((prev) =>
            prev.map((m) =>
              m.id === agentMsgId
                ? {
                    ...m,
                    content: newContent,
                    thinkingProcess: [
                      '实时接收中...',
                      `已接收 ${newContent.length} 字符`,
                    ],
                  }
                : m
            )
          );
        },
        // onDone
        (apiOptions: any[], specUpdates: any[]) => {
          const finalContent = streamRef.current;
          const hasSpec = specUpdates && specUpdates.length > 0;
          const mappedOptions: string[] = Array.isArray(apiOptions)
            ? apiOptions.map((o: any) =>
                typeof o === 'string' ? o : (o.label || o.text || o.value || String(o))
              )
            : [];
          setChatMessages((prev) =>
            prev.map((m) =>
              m.id === agentMsgId
                ? {
                    ...m,
                    content: finalContent,
                    state: mappedOptions.length > 0 ? 'asking' : 'waiting',
                    options: mappedOptions,
                    thinkingProcess: [],
                  }
                : m
            )
          );
          setChatState(mappedOptions.length > 0 ? 'asking' : 'waiting');
          if (hasSpec) loadSpec();

          // Add a system message about spec updates or completion
          if (hasSpec) {
            setTimeout(() => {
              setChatMessages(prev => [...prev, {
                id: `msg-${Date.now()}`,
                role: 'system',
                content: `Spec 文档已更新 (${specUpdates.length} 个章节)`,
                timestamp: new Date().toLocaleTimeString(),
              }]);
            }, 500);
          }
        }
      );
    } catch (e: any) {
      setChatMessages((prev) =>
        prev.map((m) =>
          m.id === agentMsgId
            ? { ...m, content: m.content || 'AI 回复出错', state: 'waiting', thinkingProcess: ['请求失败'] }
            : m
        )
      );
    } finally {
      setChatLoading(false);
    }
  };

  // Quick command buttons
  const handleQuickCommand = (cmd: string) => {
    setChatInput(cmd);
  };

  const middleWidth = 100 - leftWidth - rightWidth;

  if (loading) {
    return (
      <div className="h-[calc(100vh-5rem)] flex items-center justify-center">
        <div className="text-center">
          <div className="w-8 h-8 border-2 border-slate-300 border-t-slate-600 rounded-full animate-spin mx-auto mb-3" />
          <p className="text-xs text-slate-400">加载需求中...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="h-[calc(100vh-5rem)] flex items-center justify-center">
        <div className="text-center">
          <p className="text-sm text-red-500 mb-3">加载失败: {error}</p>
          <button
            onClick={() => {
              setError(null); setLoading(true);
              api.getRequirement(reqId).then(setRequirement).catch((e) => setError(e.message)).finally(() => setLoading(false));
            }}
            className="px-4 py-2 bg-slate-900 text-white text-xs rounded-lg hover:bg-slate-800"
          >重试</button>
        </div>
      </div>
    );
  }

  if (!requirement) {
    return (
      <div className="h-[calc(100vh-5rem)] flex items-center justify-center">
        <p className="text-sm text-slate-400">需求不存在</p>
      </div>
    );
  }

  return (
    <div className="h-[calc(100vh-5rem)] flex overflow-hidden">
      {/* Panel 1: 对话面板 */}
      <div className="flex flex-col border-r border-slate-200 bg-white" style={{ width: `${leftWidth}%` }}>
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100 flex-shrink-0">
          <div className="flex items-center gap-2">
            <h2 className="text-xs font-semibold text-slate-800">对话</h2>
            <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${
              chatState === 'idle' ? 'bg-slate-100 text-slate-500' :
              chatState === 'understanding' ? 'bg-blue-100 text-blue-600' :
              chatState === 'asking' ? 'bg-amber-100 text-amber-600' :
              chatState === 'generating' ? 'bg-purple-100 text-purple-600' :
              'bg-emerald-100 text-emerald-600'
            }`}>
              {{ idle: '就绪', understanding: '思考中...', asking: '等待回答', generating: '生成中...', waiting: '就绪' }[chatState]}
            </span>
            {chatLoading && <span className="text-[10px] text-blue-500 animate-pulse">AI 回复中...</span>}
          </div>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-4 py-3 space-y-4">
          {chatMessages.map((msg) => (
            <div key={msg.id} className={`${msg.role === 'user' ? 'flex justify-end' : 'flex gap-2'}`}>
              {msg.role !== 'user' && (
                <div className={`w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0 ${
                  msg.role === 'agent' ? 'bg-slate-800 text-white' : 'bg-slate-200 text-slate-500'
                }`}>
                  <span className="text-[10px] font-medium">{msg.role === 'agent' ? 'AI' : 'S'}</span>
                </div>
              )}
              <div className={`max-w-[85%]`}>
                {msg.role === 'user' && (
                  <div className="bg-slate-900 text-white text-xs px-4 py-2.5 rounded-2xl rounded-br-md">{msg.content}</div>
                )}
                {msg.role === 'agent' && (
                  <div className="bg-slate-50 border border-slate-100 text-xs px-4 py-2.5 rounded-2xl rounded-bl-md">
                    {msg.thinkingProcess && (
                      <div className="mb-2 pb-2 border-b border-slate-200">
                        <div className="text-[10px] text-slate-400 font-medium mb-1">思考过程</div>
                        {msg.thinkingProcess.map((t, i) => (
                          <div key={i} className="text-[10px] text-slate-400 flex items-center gap-1">
                            <span className="w-1 h-1 rounded-full bg-slate-300" />{t}
                          </div>
                        ))}
                      </div>
                    )}
                    <MarkdownRenderer content={msg.content} />
                    {msg.options && msg.options.length > 0 && (
                      <div className="mt-2 space-y-1">
                        {msg.options.map((opt, i) => (
                          <button key={i} onClick={() => setChatInput(opt)}
                            className="w-full text-left text-[10px] px-3 py-2 rounded-lg border border-slate-200 hover:border-slate-400 hover:bg-white transition-colors">
                            {opt}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                )}
                {msg.role === 'system' && (
                  <div className="text-[10px] text-slate-400 px-3 py-1.5 bg-slate-50 rounded-lg italic">{msg.content}</div>
                )}
                <p className="text-[9px] text-slate-300 mt-1 px-2">{msg.timestamp}</p>
              </div>
            </div>
          ))}
          <div ref={(el) => el?.scrollIntoView({ behavior: 'smooth' })} />
        </div>

        {/* Chat Input */}
        <div className="border-t border-slate-100 p-3 flex-shrink-0">
          <div className="flex gap-2 mb-2">
            {['帮我生成Spec', '补充验收条件', '分析技术方案', '有哪些风险点'].map((cmd) => (
              <button key={cmd} onClick={() => handleQuickCommand(cmd)}
                className="text-[10px] px-2 py-1 bg-slate-50 border border-slate-100 rounded-lg text-slate-500 hover:bg-slate-100 hover:text-slate-700 transition-colors whitespace-nowrap">
                {cmd}
              </button>
            ))}
          </div>
          <div className="flex gap-2">
            <input
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && sendMessage()}
              placeholder="输入你的反馈或问题..."
              className="flex-1 text-xs border border-slate-200 rounded-xl px-4 py-2.5 outline-none focus:border-slate-400 transition-colors"
              disabled={chatLoading}
            />
            <button onClick={sendMessage} disabled={chatLoading || !chatInput.trim()}
              className="p-2.5 bg-slate-900 text-white rounded-xl hover:bg-slate-800 transition-colors disabled:opacity-50">
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
              </svg>
            </button>
          </div>
        </div>
      </div>

      {/* Left Resize Handle */}
      <div className="w-1 cursor-col-resize hover:bg-slate-300 transition-colors flex-shrink-0 bg-transparent z-10"
        onMouseDown={() => { isDragging.current = 'left'; }} />

      {/* Panel 2: Spec 面板 */}
      <div className="flex flex-col bg-white" style={{ width: `${middleWidth}%` }}>
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100 flex-shrink-0">
          <div className="flex items-center gap-2">
            <h2 className="text-xs font-semibold text-slate-800">Spec 文档</h2>
            <span className="text-[10px] bg-emerald-50 text-emerald-600 px-1.5 py-0.5 rounded-full">
              {specSections.filter(s => s.status === 'done').length}/{specSections.length} 完成
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={loadSpec} disabled={specLoading}
              className="px-2 py-1 text-[10px] text-slate-500 hover:bg-slate-100 rounded-lg transition-colors">
              {specLoading ? '刷新中...' : '刷新'}
            </button>
            <button
              onClick={async () => {
                try {
                  await fetch('/api/requirements/' + reqId + '/trigger', { method: 'POST' });
                  alert('AI 处理流程已启动！\n\nA1 正在分析需求 → A4 生成 Spec → A6 拆解任务\n\n请稍后在页面查看 Spec 和对话更新。');
                  loadSpec();
                } catch (e: any) {
                  alert('启动失败: ' + (e.message || '未知错误'));
                }
              }}
              className="px-3 py-1.5 bg-blue-600 text-white text-[10px] font-medium rounded-lg hover:bg-blue-700 transition-colors"
            >
              AI 生成 Spec
            </button>
            <button onClick={() => setShowApproval(!showApproval)}
              className="px-3 py-1.5 bg-slate-900 text-white text-[10px] font-medium rounded-lg hover:bg-slate-800 transition-colors">
              提交审批
            </button>
          </div>
        </div>

        <div className="flex-1 flex overflow-hidden">
          {/* Section Tabs */}
          <div className="w-40 border-r border-slate-100 overflow-y-auto py-2 flex-shrink-0">
            {specSections.length === 0 ? (
              <div className="px-3 py-4 text-[10px] text-slate-400 text-center">
                {specLoading ? '加载中...' : '暂无 Spec\n在对话中让 AI 生成'}
              </div>
            ) : (
              specSections.map((section) => (
                <button key={section.id} onClick={() => setActiveSection(section.id)}
                  className={`w-full text-left px-3 py-2.5 text-xs transition-colors flex items-center gap-2 ${
                    activeSection === section.id ? 'bg-slate-50 text-slate-900 font-medium border-r-2 border-slate-900' : 'text-slate-500 hover:text-slate-700 hover:bg-slate-50'
                  }`}>
                  <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
                    section.status === 'done' ? 'bg-emerald-500' :
                    section.status === 'generating' ? 'bg-blue-500 animate-pulse' :
                    section.status === 'editing' ? 'bg-amber-400' :
                    section.status === 'conflict' ? 'bg-red-500' : 'bg-slate-300'
                  }`} />
                  <span className="truncate">{section.title}</span>
                </button>
              ))
            )}
          </div>

          {/* Active Section Content */}
          <div className="flex-1 overflow-y-auto p-4">
            {(() => {
              const section = specSections.find((s) => s.id === activeSection);
              if (!section) return <div className="text-xs text-slate-400 py-8 text-center">选择一个章节查看</div>;
              return (
                <div>
                  <h3 className="text-sm font-semibold text-slate-900 mb-1">{section.title}</h3>
                  <div className="flex items-center gap-2 mb-4">
                    <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${
                      section.status === 'done' ? 'bg-emerald-50 text-emerald-600' :
                      section.status === 'generating' ? 'bg-blue-50 text-blue-600' :
                      section.status === 'editing' ? 'bg-amber-50 text-amber-600' :
                      section.status === 'conflict' ? 'bg-red-50 text-red-600' :
                      'bg-slate-100 text-slate-500'
                    }`}>
                      {{ pending: '待生成', generating: '生成中', done: '已完成', editing: '编辑中', conflict: '冲突' }[section.status]}
                    </span>
                  </div>
                  <div className="text-xs text-slate-700 leading-relaxed bg-slate-50 rounded-xl p-4 border border-slate-100">
                    <MarkdownRenderer content={section.content} />
                  </div>
                  {section.history && section.history.length > 0 && (
                    <div className="mt-6">
                      <h4 className="text-[10px] font-medium text-slate-400 uppercase tracking-wider mb-2">变更历史</h4>
                      <div className="space-y-2">
                        {section.history.map((h: any, i: number) => (
                          <div key={i} className="flex items-start gap-2 text-xs">
                            <span className="w-1.5 h-1.5 rounded-full bg-slate-400 mt-1" />
                            <span className="text-[10px] text-slate-400 flex-shrink-0 w-12">{h.time}</span>
                            <span className="text-xs text-slate-600">{h.action}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              );
            })()}
          </div>
        </div>
      </div>

      {/* Right Resize Handle */}
      <div className="w-1 cursor-col-resize hover:bg-slate-300 transition-colors flex-shrink-0 bg-transparent z-10"
        onMouseDown={() => { isDragging.current = 'right'; }} />

      {/* Panel 3: 原型 + 信息面板 */}
      <div className="flex flex-col bg-white" style={{ width: `${rightWidth}%` }}>
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100 flex-shrink-0">
          <h2 className="text-xs font-semibold text-slate-800">需求信息</h2>
        </div>
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {/* Requirement Info */}
          <div className="bg-slate-50 rounded-xl p-4">
            <h3 className="text-xs font-semibold text-slate-800 mb-2">{requirement.title}</h3>
            <p className="text-xs text-slate-500 mb-3">{requirement.description || '暂无描述'}</p>
            <div className="grid grid-cols-2 gap-2 text-[10px]">
              <div className="bg-white rounded-lg p-2">
                <span className="text-slate-400">状态</span>
                <div className="text-slate-700 font-medium mt-0.5">{requirement.status}</div>
              </div>
              <div className="bg-white rounded-lg p-2">
                <span className="text-slate-400">优先级</span>
                <div className="text-slate-700 font-medium mt-0.5">{requirement.priority}</div>
              </div>
              <div className="bg-white rounded-lg p-2">
                <span className="text-slate-400">AI完成度</span>
                <div className="mt-1 flex items-center gap-2">
                  <div className="flex-1 h-1 bg-slate-100 rounded-full overflow-hidden">
                    <div className="h-full bg-emerald-500 rounded-full" style={{ width: `${requirement.aiCompletion || 0}%` }} />
                  </div>
                  <span className="text-slate-600">{requirement.aiCompletion || 0}%</span>
                </div>
              </div>
              <div className="bg-white rounded-lg p-2">
                <span className="text-slate-400">人工介入</span>
                <div className="text-slate-700 font-medium mt-0.5">{requirement.humanInterventions || 0} 次</div>
              </div>
            </div>
            {/* AI Workflow Controls */}
            <div className="mt-3 pt-3 border-t border-slate-200 space-y-2">
              <button onClick={async () => {
                try {
                  const res = await fetch('/api/requirements/' + reqId + '/trigger', { method: 'POST' });
                  const data = await res.json();
                  alert('AI 工作流已启动!\n\n状态: ' + (data.current_state || data.status));
                  // Refresh to get updated status
                  window.location.reload();
                } catch (e: any) {
                  alert('启动失败: ' + e.message);
                }
              }} className="w-full py-2 bg-blue-600 text-white text-[10px] font-medium rounded-lg hover:bg-blue-700 transition-colors">
                启动 AI 工作流
              </button>
              <button
                onClick={() => setShowApproval(true)}
                className="w-full py-2 bg-slate-900 text-white text-[10px] font-medium rounded-lg hover:bg-slate-800 transition-colors"
              >
                提交审批
              </button>
            </div>
          </div>

          {/* Multi-Gate Approval Section */}
          <div className="bg-white border border-slate-200 rounded-xl p-4">
            <h3 className="text-xs font-semibold text-slate-800 mb-2">审批门禁</h3>
            <div className="space-y-2">
              {[0, 1, 2, 3].map(gate => {
                const gateLabels: Record<number, string> = {0: 'Gate 0 - 业务确认', 1: 'Gate 1 - Spec 确认', 2: 'Gate 2 - 架构确认', 3: 'Gate 3 - 发布确认'};
                const existing = requirement.approvals?.find((a: any) => a.gate === gate);
                const statusIcon = !existing ? '○' : existing.status === 'approved' ? '✓' : existing.status === 'rejected' ? '✗' : '○';
                const statusColor = !existing ? 'text-slate-300' : existing.status === 'approved' ? 'text-emerald-500' : existing.status === 'rejected' ? 'text-red-500' : 'text-amber-500';
                return (
                  <div key={gate} className="flex items-center gap-2 text-[10px] py-1">
                    <span className={`${statusColor} font-bold`}>{statusIcon}</span>
                    <span className="text-slate-600 flex-1">{gateLabels[gate]}</span>
                    {existing?.status === 'pending' && (
                      <span className="text-amber-500 text-[9px]">待审批</span>
                    )}
                    {!existing && (
                      <button onClick={() => {
                        api.submitApproval(reqId, gate)
                          .then(() => {
                            api.getRequirement(reqId).then(setRequirement);
                          })
                          .catch((e: any) => alert('创建审批失败: ' + e.message));
                      }} className="text-[9px] text-blue-500 hover:text-blue-700 underline">创建审批</button>
                    )}
                  </div>
                );
              })}
            </div>
            {requirement.approvals && requirement.approvals.length > 0 && (
              <button onClick={() => setShowApproval(true)}
                className="mt-2 w-full py-1.5 text-[10px] text-slate-500 border border-slate-200 rounded-lg hover:bg-slate-50">
                打开审批台
              </button>
            )}
          </div>

          {/* Activity log - combines DB history + live WebSocket updates */}
          <div className="bg-white border border-slate-200 rounded-xl p-4">
            <h3 className="text-xs font-semibold text-slate-800 mb-2">活动记录</h3>
            <div className="space-y-1.5 max-h-40 overflow-y-auto">
              {liveActivity.length > 0 && liveActivity.map((a, i) => (
                <div key={`live-${i}`} className="flex items-center gap-2 text-[10px]">
                  <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse flex-shrink-0" />
                  <span className="text-blue-600 font-medium">{a.agent_id}</span>
                  <span className="text-slate-500 truncate">{a.action}</span>
                  <span className="text-slate-300 ml-auto flex-shrink-0">{a.time}</span>
                </div>
              ))}
              {requirement.activities && requirement.activities.slice(0, 10).map((a: any) => (
                <div key={a.id} className="flex items-center gap-2 text-[10px]">
                  <span className="w-1 h-1 rounded-full bg-slate-300 flex-shrink-0" />
                  <span className="text-slate-500">{a.agent_id || '系统'}</span>
                  <span className="text-slate-400 truncate">{a.action}</span>
                  <span className="text-slate-300 ml-auto flex-shrink-0">{a.created_at ? new Date(a.created_at).toLocaleTimeString() : ''}</span>
                </div>
              ))}
              {(!liveActivity.length && !requirement.activities?.length) && (
                <div className="text-[10px] text-slate-400 text-center py-4">暂无活动记录</div>
              )}
            </div>
          </div>

          {/* Pipeline Stage */}
          <div className="bg-white border border-slate-200 rounded-xl p-4">
            <h3 className="text-xs font-semibold text-slate-800 mb-2">AI 流水线阶段</h3>
            <div className="space-y-1.5">
              {(() => {
                const stages = ['draft','clarifying','analyzing','designing','reviewing','decomposing','developing','testing','reviewing_code','releasing','done'];
                const stageLabels: Record<string,string> = { draft:'需求草稿', clarifying:'需求澄清', analyzing:'需求分析', designing:'方案设计', reviewing:'设计评审', decomposing:'任务拆解', developing:'编码开发', testing:'测试验证', reviewing_code:'代码审查', releasing:'发布上线', done:'已完成' };
                const currentIdx = stages.indexOf(requirement.status || '');
                return stages.map((s, i) => {
                  const isActive = s === (requirement.status || 'draft');
                  const isDone = currentIdx >= 0 && i <= currentIdx;
                  return (
                    <div key={s} className={`flex items-center gap-2 text-[10px] py-1 ${isActive ? 'font-semibold' : ''} ${isDone ? 'text-slate-700' : 'text-slate-300'}`}>
                      <span className={`w-2 h-2 rounded-full flex-shrink-0 ${
                        isActive ? 'bg-blue-500 animate-pulse' : isDone ? 'bg-emerald-400' : 'bg-slate-200'
                      }`} />
                      <span className="w-20">{stageLabels[s] || s}</span>
                      {isActive && <span className="text-blue-500 text-[8px] ml-auto">进行中</span>}
                      {isDone && !isActive && <span className="text-emerald-500 text-[8px] ml-auto">✓</span>}
                    </div>
                  );
                });
              })()}
            </div>
          </div>
        </div>
      </div>

      {/* Multi-Gate 审批台 Modal */}
      {showApproval && (
        <>
          <div className="fixed inset-0 bg-black/30 z-50" onClick={() => setShowApproval(false)} />
          <div className="fixed inset-x-0 top-16 bottom-12 mx-auto max-w-5xl bg-white rounded-2xl shadow-2xl z-50 flex flex-col overflow-hidden">
            {/* Header with Gate tabs */}
            <div className="flex items-center justify-between px-6 py-3 border-b border-slate-200 flex-shrink-0">
              <div className="flex items-center gap-3">
                <h2 className="text-sm font-semibold text-slate-900">审批台</h2>
                <div className="flex gap-1">
                  {[0, 1, 2, 3].map(gate => {
                    const existing = requirement.approvals?.find((a: any) => a.gate === gate);
                    const isActive = selectedGate === gate;
                    const gateNames: Record<number, string> = {0: 'Gate 0 业务', 1: 'Gate 1 Spec', 2: 'Gate 2 架构', 3: 'Gate 3 发布'};
                    return (
                      <button key={gate} onClick={() => setSelectedGate(gate)}
                        className={`text-[10px] px-2.5 py-1 rounded-full transition-colors ${
                          isActive ? 'bg-slate-900 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                        }`}>
                        {gateNames[gate]}
                        {existing && <span className="ml-1">{existing.status === 'approved' ? '✓' : existing.status === 'rejected' ? '✗' : '○'}</span>}
                      </button>
                    );
                  })}
                </div>
              </div>
              <button onClick={() => setShowApproval(false)} className="p-1.5 hover:bg-slate-100 rounded-lg">
                <svg className="w-4 h-4 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            <div className="flex-1 flex overflow-hidden">
              {/* Left: Gate-specific review content */}
              <div className="w-[55%] overflow-y-auto p-4 border-r border-slate-100">
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-[10px] font-medium text-slate-400 uppercase tracking-wider">
                    {selectedGate === 0 && '需求分析与知识检索结果'}
                    {selectedGate === 1 && 'Spec 文档 & 技术设计'}
                    {selectedGate === 2 && '架构评审报告'}
                    {selectedGate === 3 && 'Code Review 结果'}
                  </h3>
                  {(() => {
                    const ga = approvalList.find((a: any) => a.gate === selectedGate);
                    if (ga?.sla_remaining_seconds != null && ga.status === 'pending') {
                      const secs = slaTimers[ga.id] ?? ga.sla_remaining_seconds;
                      const h = Math.floor(secs / 3600), m = Math.floor((secs % 3600) / 60), s = secs % 60;
                      const isUrgent = secs < 3600;
                      return (
                        <span className={`text-[10px] px-2 py-0.5 rounded-full ${isUrgent ? 'bg-red-50 text-red-600 animate-pulse' : 'bg-amber-50 text-amber-600'}`}>
                          SLA: {h > 0 ? `${h}h` : ''}{m}m{s}s {isUrgent ? '超时预警' : ''}
                        </span>
                      );
                    }
                    return null;
                  })()}
                </div>

                {/* Gate 1: Show Spec sections */}
                {selectedGate === 1 && (
                  <div className="space-y-3">
                    {specSections.map((s) => (
                      <div key={s.id} className="text-xs">
                        <h4 className="font-medium text-slate-800">{s.title}</h4>
                        <div className="text-slate-500 mt-1 bg-slate-50 rounded-lg p-3 max-h-48 overflow-y-auto">
                          <MarkdownRenderer content={s.content?.slice(0, 500) || ''} />
                        </div>
                      </div>
                    ))}
                    {specSections.length === 0 && <p className="text-xs text-slate-400">暂无 Spec 内容，请先在对话中让 AI 生成</p>}
                  </div>
                )}

                {/* Gate 0/2/3: Show agent reviews */}
                {selectedGate !== 1 && (
                  <div className="space-y-3">
                    {(() => {
                      const ga = approvalList.find((a: any) => a.gate === selectedGate);
                      const reviews = ga?.agent_reviews || {};
                      if (Object.keys(reviews).length === 0) {
                        return <p className="text-xs text-slate-400">
                          {selectedGate === 0 && '尚无 A1/A2 分析结果，请先等待 Agent 完成分析'}
                          {selectedGate === 2 && '尚无 A8 架构评审结果，请先等待架构评审 Agent 完成'}
                          {selectedGate === 3 && '尚无 A12 代码审查结果，请先等待 Code Review Agent 完成'}
                        </p>;
                      }
                      return Object.entries(reviews).map(([agentId, review]: [string, any]) => (
                        <div key={agentId} className="bg-slate-50 rounded-lg p-3 text-xs">
                          <div className="flex items-center gap-2 mb-2">
                            <span className="font-medium text-slate-700">{agentId}</span>
                            <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${
                              review.verdict === 'pass' || review.score >= 70 ? 'bg-emerald-50 text-emerald-600' : 'bg-red-50 text-red-600'
                            }`}>
                              {review.verdict || review.status || 'pending'}
                            </span>
                            {review.score != null && <span className="text-slate-400">Score: {review.score}</span>}
                          </div>
                          {review.summary && <p className="text-slate-600">{review.summary}</p>}
                          {review.issues && review.issues.length > 0 && (
                            <div className="mt-2 space-y-1">
                              {review.issues.slice(0, 5).map((issue: any, i: number) => (
                                <div key={i} className="text-[10px] text-slate-500 flex gap-1">
                                  <span className={`w-4 flex-shrink-0 ${
                                    issue.severity === 'critical' || issue.severity === 'error' ? 'text-red-500' : 'text-amber-500'
                                  }`}>
                                    {issue.severity === 'critical' || issue.severity === 'error' ? '✕' : '!'}
                                  </span>
                                  <span>{issue.title || issue.description}</span>
                                </div>
                              ))}
                            </div>
                          )}
                          {review.violations && review.violations.length > 0 && (
                            <div className="mt-2 space-y-1">
                              {review.violations.map((v: any, i: number) => (
                                <div key={i} className="text-[10px] text-slate-500">[{v.rule}] {v.title}: {v.suggestion}</div>
                              ))}
                            </div>
                          )}
                        </div>
                      ));
                    })()}
                  </div>
                )}
              </div>

              {/* Right: Approval actions */}
              <div className="w-[45%] overflow-y-auto p-4">
                <h3 className="text-[10px] font-medium text-slate-400 uppercase tracking-wider mb-3">
                  {(() => {
                    const ga = approvalList.find((a: any) => a.gate === selectedGate);
                    if (!ga) return '创建审批';
                    if (ga.status === 'approved') return '已通过';
                    if (ga.status === 'rejected') return '已拒绝';
                    return '审批操作';
                  })()}
                </h3>

                <div className="space-y-2">
                  {(() => {
                    const ga = approvalList.find((a: any) => a.gate === selectedGate);
                    if (!ga) {
                      return (
                        <button onClick={() => {
                          api.submitApproval(reqId, selectedGate)
                            .then((res: any) => {
                              const newId = res.id;
                              api.approve(newId)
                                .then(() => { setShowApproval(false); api.getRequirement(reqId).then(setRequirement); })
                                .catch((e: any) => alert('审批失败: ' + e.message));
                            })
                            .catch((e: any) => alert('创建审批失败: ' + e.message));
                        }} className="w-full py-2.5 bg-emerald-600 text-white text-xs font-medium rounded-xl hover:bg-emerald-700 transition-colors">
                          创建并审批通过
                        </button>
                      );
                    }
                    if (ga.status === 'approved') {
                      return <p className="text-xs text-emerald-600">该 Gate 已在 {ga.resolved_at ? new Date(ga.resolved_at).toLocaleString() : '--'} 通过</p>;
                    }
                    if (ga.status === 'rejected') {
                      return (
                        <div>
                          <p className="text-xs text-red-500 mb-2">该 Gate 已被拒绝</p>
                          {ga.reject_reasons?.map((r: any, i: number) => (
                            <p key={i} className="text-[10px] text-slate-500">{r.reason} ({r.at ? new Date(r.at).toLocaleTimeString() : ''})</p>
                          ))}
                        </div>
                      );
                    }
                    // Pending
                    return (
                      <>
                        <button onClick={() => {
                          api.approve(ga.id)
                            .then(() => { setShowApproval(false); api.getRequirement(reqId).then(setRequirement); })
                            .catch((e: any) => alert('审批失败: ' + e.message));
                        }} className="w-full py-2.5 bg-emerald-600 text-white text-xs font-medium rounded-xl hover:bg-emerald-700 transition-colors">
                          通过审批
                        </button>
                        <button onClick={() => {
                          const reason = prompt('请输入拒绝原因（可选）:');
                          api.reject(ga.id, reason || undefined)
                            .then(() => { api.getRequirement(reqId).then(setRequirement); })
                            .catch((e: any) => alert('操作失败: ' + e.message));
                        }} className="w-full py-2.5 bg-white border border-red-200 text-red-600 text-xs font-medium rounded-xl hover:bg-red-50 transition-colors">
                          打回修订
                        </button>
                      </>
                    );
                  })()}
                </div>

                {/* Gate description */}
                <div className="mt-4 pt-4 border-t border-slate-100">
                  <p className="text-[10px] text-slate-400">
                    {selectedGate === 0 && 'A1 需求分析 + A2 知识检索完成后，需要业务方确认需求理解是否正确'}
                    {selectedGate === 1 && 'A4 生成 Spec/OpenAPI/ERD 后，需要确认技术设计方案是否满足需求'}
                    {selectedGate === 2 && 'A8 架构评审通过后，需要架构师确认 DAG 拆分和技术方案'}
                    {selectedGate === 3 && 'A12 Code Review 通过后，需要 Tech Lead 确认代码质量并批准发布'}
                  </p>
                </div>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

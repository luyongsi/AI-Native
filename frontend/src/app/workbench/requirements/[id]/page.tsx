'use client';

import { useState, useRef, useEffect } from 'react';
import { useParams } from 'next/navigation';
import { api } from '@/lib/api';
import type { SpecSection, ChatResponse } from '@/lib/types';
import MarkdownRenderer from '@/components/MarkdownRenderer';

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
  options?: string[];       // 选择题选项
  thinkingProcess?: string[]; // Agent 透明化思考
}

interface PrototypeAnnotation {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  type: 'comment' | 'issue' | 'suggestion' | 'question';
  content: string;
  resolved: boolean;
}

// ============================================================
// 主页面组件
// ============================================================
export default function RequirementWorkspacePage() {
  const params = useParams();
  const reqId = params?.id as string || 'REQ-789';

  // ---- Data state -----------------------------------------------------------
  const [requirement, setRequirement] = useState<Record<string, any> | null>(null);
  const [reqLoading, setReqLoading] = useState(true);
  const [reqError, setReqError] = useState<string | null>(null);

  // Chat state
  const [chatInput, setChatInput] = useState('');
  const [chatState, setChatState] = useState<ChatState>('idle');
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatLoading, setChatLoading] = useState(true);
  const [chatError, setChatError] = useState<string | null>(null);

  // Spec state
  const [specSections, setSpecSections] = useState<SpecSection[]>([]);
  const [activeSection, setActiveSection] = useState<string>('');
  const [specLoading, setSpecLoading] = useState(true);
  const [specError, setSpecError] = useState<string | null>(null);

  // Panel widths (30/40/30 split)
  const [leftWidth, setLeftWidth] = useState(30);
  const [rightWidth, setRightWidth] = useState(30);
  const isDragging = useRef<'left' | 'right' | null>(null);

  // Prototype annotations
  const [annotations, setAnnotations] = useState<PrototypeAnnotation[]>([]);
  const [annotationMode, setAnnotationMode] = useState(false);
  const [protoView, setProtoView] = useState<'preview' | 'compare'>('preview');

  // Approval state
  const [showApproval, setShowApproval] = useState(false);

  // ---- Data fetching --------------------------------------------------------

  // Fetch requirement detail
  useEffect(() => {
    let cancelled = false;
    setReqLoading(true);
    setReqError(null);
    api
      .getRequirement(reqId)
      .then((data) => {
        if (!cancelled) {
          setRequirement(data as unknown as Record<string, any>);
          setReqLoading(false);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setReqError(err?.message || '加载需求失败');
          setReqLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [reqId]);

  // Fetch chat messages
  useEffect(() => {
    let cancelled = false;
    setChatLoading(true);
    setChatError(null);
    api
      .getChatMessages(reqId)
      .then((data) => {
        if (!cancelled) {
          const msgs: ChatMessage[] = (data.messages || []).map(
            (m, i) => ({
              id: `msg-api-${i}-${Date.now()}`,
              role: (m.role === 'assistant' ? 'agent' : m.role) as ChatMessage['role'],
              content: m.content || '',
              timestamp: m.time || '',
              state: undefined,
              options: undefined,
              thinkingProcess: undefined,
            }),
          );
          setChatMessages(msgs);
          setChatLoading(false);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setChatError(err?.message || '加载对话记录失败');
          setChatLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [reqId]);

  // Fetch spec sections
  useEffect(() => {
    let cancelled = false;
    setSpecLoading(true);
    setSpecError(null);
    api
      .getSpecSections(reqId)
      .then((data) => {
        if (!cancelled) {
          const sections = data.sections || [];
          setSpecSections(sections);
          if (sections.length > 0) {
            setActiveSection(sections[0].id);
          }
          setSpecLoading(false);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setSpecError(err?.message || '加载 Spec 失败');
          setSpecLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [reqId]);

  // ---- Resize handlers -------------------------------------------------------
  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!isDragging.current) return;
      const totalWidth = window.innerWidth - 224; // minus sidebar
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

  // ---- Chat actions ----------------------------------------------------------

  // Send chat message
  const sendMessage = () => {
    if (!chatInput.trim()) return;
    const userMsg: ChatMessage = {
      id: `msg-${Date.now()}`,
      role: 'user',
      content: chatInput,
      timestamp: new Date().toLocaleTimeString(),
    };
    setChatMessages((prev) => [...prev, userMsg]);
    const sentText = chatInput;
    setChatInput('');
    setChatState('understanding');

    // Call real API, but keep the simulated / staged UI reveal
    api
      .sendChatMessage(reqId, sentText)
      .then((res: ChatResponse) => {
        // First stage: "generating" bubble
        setChatState('generating');
        const thinkingMsg: ChatMessage = {
          id: `msg-${Date.now() + 1}`,
          role: 'agent',
          content: res.reply || '收到，我正在根据你的反馈更新 Spec 和原型...',
          timestamp: new Date().toLocaleTimeString(),
          state: 'generating',
          thinkingProcess: res.spec_updates
            ? ['解析用户输入', '更新相关 Spec 章节', '触发 UI Agent 更新原型']
            : ['解析用户输入', '处理中...'],
          options: res.options,
        };
        setChatMessages((prev) => [...prev, thinkingMsg]);

        // Second stage: system note after a brief delay (simulated)
        setTimeout(() => {
          setChatState('waiting');
          const doneMsg: ChatMessage = {
            id: `msg-${Date.now() + 2}`,
            role: 'system',
            content: res.spec_updates?.length
              ? `✅ Spec 已更新 ${res.spec_updates.length} 个章节`
              : '✅ 已处理',
            timestamp: new Date().toLocaleTimeString(),
          };
          setChatMessages((prev) => [...prev, doneMsg]);

          // Refresh spec sections in case the backend updated them
          api
            .getSpecSections(reqId)
            .then((data) => {
              const sections = data.sections || [];
              setSpecSections(sections);
              if (sections.length > 0 && !sections.find((s) => s.id === 's1')) {
                setActiveSection(sections[0].id);
              }
            })
            .catch(() => {
              // silent fail — spec refresh is best-effort
            });
        }, 1500);
      })
      .catch((err) => {
        setChatState('waiting');
        const errMsg: ChatMessage = {
          id: `msg-${Date.now() + 1}`,
          role: 'system',
          content: `❌ 发送失败: ${err?.message || '未知错误'}`,
          timestamp: new Date().toLocaleTimeString(),
        };
        setChatMessages((prev) => [...prev, errMsg]);
      });
  };

  // Retry helpers
  const retryChat = () => {
    setChatError(null);
    setChatLoading(true);
    api
      .getChatMessages(reqId)
      .then((data) => {
        const msgs: ChatMessage[] = (data.messages || []).map(
          (m, i) => ({
            id: `msg-api-${i}-${Date.now()}`,
            role: (m.role as ChatMessage['role']) || 'agent',
            content: m.content || '',
            timestamp: m.time || '',
            state: undefined,
            options: undefined,
            thinkingProcess: undefined,
          }),
        );
        setChatMessages(msgs);
        setChatLoading(false);
      })
      .catch((err) => {
        setChatError(err?.message || '加载对话记录失败');
        setChatLoading(false);
      });
  };

  const retrySpec = () => {
    setSpecError(null);
    setSpecLoading(true);
    api
      .getSpecSections(reqId)
      .then((data) => {
        const sections = data.sections || [];
        setSpecSections(sections);
        if (sections.length > 0 && !activeSection) {
          setActiveSection(sections[0].id);
        }
        setSpecLoading(false);
      })
      .catch((err) => {
        setSpecError(err?.message || '加载 Spec 失败');
        setSpecLoading(false);
      });
  };

  const middleWidth = 100 - leftWidth - rightWidth;

  return (
    <div className="h-[calc(100vh-5rem)] flex overflow-hidden">
      {/* ================================================================
          Panel 1: 对话面板 (30%)
          ================================================================ */}
      <div className="flex flex-col border-r border-slate-200 bg-white" style={{ width: `${leftWidth}%` }}>
        {/* Chat Header */}
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
              {{ idle: '就绪', understanding: '理解中...', asking: '等待回答', generating: '生成中...', waiting: '等待审批' }[chatState]}
            </span>
          </div>
          <div className="flex items-center gap-1">
            <button className="p-1.5 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors" title="快捷指令">
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
            </button>
          </div>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-4 py-3 space-y-4">
          {/* Loading state */}
          {chatLoading && (
            <div className="flex items-center justify-center h-full">
              <div className="flex flex-col items-center gap-3">
                <div className="w-6 h-6 border-2 border-slate-300 border-t-slate-600 rounded-full animate-spin" />
                <span className="text-[10px] text-slate-400">加载对话中...</span>
              </div>
            </div>
          )}

          {/* Error state */}
          {!chatLoading && chatError && (
            <div className="flex items-center justify-center h-full">
              <div className="flex flex-col items-center gap-3 text-center px-4">
                <svg className="w-8 h-8 text-red-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
                </svg>
                <p className="text-xs text-slate-500">{chatError}</p>
                <button
                  onClick={retryChat}
                  className="text-[10px] px-3 py-1.5 bg-slate-900 text-white rounded-lg hover:bg-slate-800 transition-colors"
                >
                  重试
                </button>
              </div>
            </div>
          )}

          {/* Empty state */}
          {!chatLoading && !chatError && chatMessages.length === 0 && (
            <div className="flex items-center justify-center h-full">
              <div className="flex flex-col items-center gap-2 text-center px-4">
                <svg className="w-8 h-8 text-slate-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M8.625 9.75a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H8.25m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H12m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0h-.375m-13.5 3.01c0 1.6 1.123 2.994 2.707 3.227 1.087.16 2.185.283 3.293.369V21l4.184-4.183a1.14 1.14 0 01.778-.332 48.294 48.294 0 005.83-.498c1.585-.233 2.708-1.626 2.708-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0012 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v6.018z" />
                </svg>
                <p className="text-xs text-slate-400">暂无对话记录</p>
                <p className="text-[10px] text-slate-300">在下方输入框开始与 Agent 对话</p>
              </div>
            </div>
          )}

          {/* Message list */}
          {!chatLoading && !chatError && chatMessages.map((msg) => (
            <div key={msg.id} className={`${msg.role === 'user' ? 'flex justify-end' : 'flex gap-2'}`}>
              {msg.role !== 'user' && (
                <div className={`w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0 ${
                  msg.role === 'agent' ? 'bg-slate-800 text-white' : 'bg-slate-200 text-slate-500'
                }`}>
                  <span className="text-[10px] font-medium">{msg.role === 'agent' ? 'A' : 'S'}</span>
                </div>
              )}
              <div className={`max-w-[85%] ${msg.role === 'agent' || msg.role === 'system' ? '' : ''}`}>
                {/* User bubble */}
                {msg.role === 'user' && (
                  <div className="bg-slate-900 text-white text-xs px-4 py-2.5 rounded-2xl rounded-br-md">
                    {msg.content}
                  </div>
                )}

                {/* Agent bubble */}
                {msg.role === 'agent' && (
                  <div className="bg-slate-50 border border-slate-100 text-xs px-4 py-2.5 rounded-2xl rounded-bl-md">
                    {msg.thinkingProcess && (
                      <div className="mb-2 pb-2 border-b border-slate-200">
                        <div className="text-[10px] text-slate-400 font-medium mb-1">思考过程</div>
                        {msg.thinkingProcess.map((t, i) => (
                          <div key={i} className="text-[10px] text-slate-400 flex items-center gap-1">
                            <span className="w-1 h-1 rounded-full bg-slate-300" />
                            {t}
                          </div>
                        ))}
                      </div>
                    )}
                    <MarkdownRenderer content={msg.content} />
                    {/* Multiple choice options */}
                    {msg.options && (
                      <div className="mt-2 space-y-1">
                        {msg.options.map((opt, i) => (
                          <button
                            key={i}
                            onClick={() => {
                              setChatInput(opt);
                            }}
                            className="w-full text-left text-[10px] px-3 py-2 rounded-lg border border-slate-200 hover:border-slate-400 hover:bg-white transition-colors"
                          >
                            {opt}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {/* System message */}
                {msg.role === 'system' && (
                  <div className="text-[10px] text-slate-400 px-3 py-1.5 bg-slate-50 rounded-lg italic">
                    {msg.content}
                  </div>
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
            {['补充细节', '确认验收标准', '生成测试用例', '查看接口文档'].map((cmd) => (
              <button
                key={cmd}
                onClick={() => setChatInput(cmd)}
                className="text-[10px] px-2 py-1 bg-slate-50 border border-slate-100 rounded-lg text-slate-500 hover:bg-slate-100 hover:text-slate-700 transition-colors whitespace-nowrap"
              >
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
            />
            <button
              onClick={sendMessage}
              className="p-2.5 bg-slate-900 text-white rounded-xl hover:bg-slate-800 transition-colors"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
              </svg>
            </button>
          </div>
        </div>
      </div>

      {/* Left Resize Handle */}
      <div
        className="w-1 cursor-col-resize hover:bg-slate-300 transition-colors flex-shrink-0 bg-transparent z-10"
        onMouseDown={() => { isDragging.current = 'left'; }}
      />

      {/* ================================================================
          Panel 2: Spec 面板 (40%)
          ================================================================ */}
      <div className="flex flex-col bg-white" style={{ width: `${middleWidth}%` }}>
        {/* Spec Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100 flex-shrink-0">
          <div className="flex items-center gap-2">
            <h2 className="text-xs font-semibold text-slate-800">Spec 文档</h2>
            <span className="text-[10px] bg-emerald-50 text-emerald-600 px-1.5 py-0.5 rounded-full">
              完成度 {specSections.filter((s) => s.status === 'done').length}/{specSections.length || 0}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowApproval(!showApproval)}
              className="px-3 py-1.5 bg-slate-900 text-white text-[10px] font-medium rounded-lg hover:bg-slate-800 transition-colors"
            >
              提交审批
            </button>
          </div>
        </div>

        {/* Spec Content */}
        <div className="flex-1 flex overflow-hidden">
          {/* Loading state */}
          {specLoading && (
            <div className="flex-1 flex items-center justify-center">
              <div className="flex flex-col items-center gap-3">
                <div className="w-6 h-6 border-2 border-slate-300 border-t-slate-600 rounded-full animate-spin" />
                <span className="text-[10px] text-slate-400">加载 Spec 中...</span>
              </div>
            </div>
          )}

          {/* Error state */}
          {!specLoading && specError && (
            <div className="flex-1 flex items-center justify-center">
              <div className="flex flex-col items-center gap-3 text-center px-4">
                <svg className="w-8 h-8 text-red-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
                </svg>
                <p className="text-xs text-slate-500">{specError}</p>
                <button
                  onClick={retrySpec}
                  className="text-[10px] px-3 py-1.5 bg-slate-900 text-white rounded-lg hover:bg-slate-800 transition-colors"
                >
                  重试
                </button>
              </div>
            </div>
          )}

          {/* Empty state */}
          {!specLoading && !specError && specSections.length === 0 && (
            <div className="flex-1 flex items-center justify-center">
              <div className="flex flex-col items-center gap-2 text-center px-4">
                <svg className="w-8 h-8 text-slate-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
                </svg>
                <p className="text-xs text-slate-400">暂无 Spec 章节</p>
                <p className="text-[10px] text-slate-300">通过对话面板与 Agent 交互以生成 Spec</p>
              </div>
            </div>
          )}

          {/* Spec content (loaded) */}
          {!specLoading && !specError && specSections.length > 0 && (
            <>
              {/* Section Tabs */}
              <div className="w-40 border-r border-slate-100 overflow-y-auto py-2 flex-shrink-0">
                {specSections.map((section) => (
                  <button
                    key={section.id}
                    onClick={() => setActiveSection(section.id)}
                    className={`w-full text-left px-3 py-2.5 text-xs transition-colors flex items-center gap-2 ${
                      activeSection === section.id ? 'bg-slate-50 text-slate-900 font-medium border-r-2 border-slate-900' : 'text-slate-500 hover:text-slate-700 hover:bg-slate-50'
                    }`}
                  >
                    <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
                      section.status === 'done' ? 'bg-emerald-500' :
                      section.status === 'generating' ? 'bg-blue-500 animate-pulse' :
                      section.status === 'editing' ? 'bg-amber-400' :
                      section.status === 'conflict' ? 'bg-red-500' :
                      'bg-slate-300'
                    }`} />
                    <span className="truncate">{section.title}</span>
                  </button>
                ))}
              </div>

              {/* Active Section Content */}
              <div className="flex-1 overflow-y-auto p-4">
                {(() => {
                  const section = specSections.find((s) => s.id === activeSection);
                  if (!section) return null;

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
                          {{ pending: '⏳ 待生成', generating: '🟡 生成中', done: '✅ 已完成', editing: '🔵 编辑中', conflict: '🔴 冲突' }[section.status]}
                        </span>
                      </div>

                      <div className="text-xs text-slate-700 leading-relaxed bg-slate-50 rounded-xl p-4 border border-slate-100">
                        <MarkdownRenderer content={section.content} />
                      </div>

                      {/* History Timeline */}
                      <div className="mt-6">
                        <h4 className="text-[10px] font-medium text-slate-400 uppercase tracking-wider mb-2">段落生长历史</h4>
                        <div className="space-y-2">
                          {section.history.map((h, i) => (
                            <div key={i} className="flex items-start gap-2 text-xs">
                              <div className="flex flex-col items-center">
                                <span className="w-1.5 h-1.5 rounded-full bg-slate-400" />
                                {i < section.history.length - 1 && <div className="w-px h-4 bg-slate-200" />}
                              </div>
                              <span className="text-[10px] text-slate-400 flex-shrink-0 w-12">{h.time}</span>
                              <span className="text-xs text-slate-600">{h.action}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    </div>
                  );
                })()}
              </div>
            </>
          )}
        </div>
      </div>

      {/* Right Resize Handle */}
      <div
        className="w-1 cursor-col-resize hover:bg-slate-300 transition-colors flex-shrink-0 bg-transparent z-10"
        onMouseDown={() => { isDragging.current = 'right'; }}
      />

      {/* ================================================================
          Panel 3: 原型面板 (30%)
          ================================================================ */}
      <div className="flex flex-col bg-white" style={{ width: `${rightWidth}%` }}>
        {/* Prototype Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100 flex-shrink-0">
          <h2 className="text-xs font-semibold text-slate-800">原型预览</h2>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setProtoView('preview')}
              className={`text-[10px] px-2 py-1 rounded-lg transition-colors ${protoView === 'preview' ? 'bg-slate-900 text-white' : 'text-slate-500 hover:bg-slate-100'}`}
            >
              预览
            </button>
            <button
              onClick={() => setProtoView('compare')}
              className={`text-[10px] px-2 py-1 rounded-lg transition-colors ${protoView === 'compare' ? 'bg-slate-900 text-white' : 'text-slate-500 hover:bg-slate-100'}`}
            >
              设计稿对比
            </button>
            <button
              onClick={() => setAnnotationMode(!annotationMode)}
              className={`text-[10px] px-2 py-1 rounded-lg transition-colors ${annotationMode ? 'bg-amber-100 text-amber-700' : 'text-slate-500 hover:bg-slate-100'}`}
            >
              标注 ({annotations.filter((a) => !a.resolved).length})
            </button>
          </div>
        </div>

        {/* Prototype Preview */}
        <div className="flex-1 overflow-y-auto bg-slate-50 p-4">
          {/* Mock prototype: Order list page */}
          <div className="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
            {/* Mock browser bar */}
            <div className="bg-slate-100 px-3 py-2 flex items-center gap-1.5 border-b border-slate-200">
              <span className="w-2 h-2 rounded-full bg-red-400" />
              <span className="w-2 h-2 rounded-full bg-amber-400" />
              <span className="w-2 h-2 rounded-full bg-emerald-400" />
              <span className="ml-2 text-[10px] text-slate-400 bg-white rounded px-2 py-0.5 flex-1 truncate">app.example.com/orders</span>
            </div>

            {/* Mock page content */}
            <div className="p-4">
              {/* Header */}
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-semibold text-slate-800">订单管理</h3>
                <div className="flex items-center gap-2">
                  <button className="text-[10px] px-3 py-1.5 border border-slate-200 rounded-lg text-slate-600 hover:bg-slate-50">筛选</button>
                  <button className="text-[10px] px-3 py-1.5 border border-slate-200 rounded-lg text-slate-600 hover:bg-slate-50">刷新</button>
                  {/* Export button (highlighted - new feature) */}
                  <button className="text-[10px] px-3 py-1.5 bg-blue-600 text-white rounded-lg font-medium ring-2 ring-blue-200">
                    批量导出
                  </button>
                </div>
              </div>

              {/* Mock table */}
              <table className="w-full text-[10px]">
                <thead>
                  <tr className="border-b border-slate-200 text-left text-slate-400">
                    <th className="py-2 font-medium"><input type="checkbox" className="w-3 h-3" /></th>
                    <th className="py-2 font-medium">订单号</th>
                    <th className="py-2 font-medium">客户</th>
                    <th className="py-2 font-medium">金额</th>
                    <th className="py-2 font-medium">状态</th>
                    <th className="py-2 font-medium">时间</th>
                  </tr>
                </thead>
                <tbody className="text-slate-600">
                  {[1, 2, 3, 4].map((i) => (
                    <tr key={i} className="border-b border-slate-50 hover:bg-slate-50/50">
                      <td className="py-2"><input type="checkbox" className="w-3 h-3" /></td>
                      <td className="py-2 font-mono text-slate-500">ORD-2026-{String(i).padStart(4, '0')}</td>
                      <td className="py-2">用户{['张三', '李四', '王五', '赵六'][i-1]}</td>
                      <td className="py-2">¥{['1,299', '2,580', '399', '6,880'][i-1]}</td>
                      <td className="py-2">
                        <span className={`px-1.5 py-0.5 rounded-full text-[9px] ${
                          ['bg-emerald-50 text-emerald-600', 'bg-blue-50 text-blue-600', 'bg-amber-50 text-amber-600', 'bg-slate-100 text-slate-500'][i-1]
                        }`}>{['已完成', '配送中', '待付款', '已取消'][i-1]}</span>
                      </td>
                      <td className="py-2 text-slate-400">06-2{i}</td>
                    </tr>
                  ))}
                </tbody>
              </table>

              {/* Pagination */}
              <div className="flex items-center justify-between mt-3 pt-3 border-t border-slate-100">
                <span className="text-[10px] text-slate-400">共 1,286 条</span>
                <div className="flex gap-1">
                  <button className="text-[10px] px-2 py-1 border border-slate-200 rounded text-slate-500">上一页</button>
                  <button className="text-[10px] px-2 py-1 bg-blue-600 text-white rounded">1</button>
                  <button className="text-[10px] px-2 py-1 border border-slate-200 rounded text-slate-500">2</button>
                  <button className="text-[10px] px-2 py-1 border border-slate-200 rounded text-slate-500">3</button>
                  <button className="text-[10px] px-2 py-1 border border-slate-200 rounded text-slate-500">下一页</button>
                </div>
              </div>
            </div>

            {/* Annotations overlay */}
            {annotationMode && annotations.map((ann) => (
              <div
                key={ann.id}
                className="absolute border-2 border-amber-400 bg-amber-50/80 rounded-lg p-2 cursor-pointer group"
                style={{ left: ann.x, top: ann.y, width: ann.width, height: ann.height }}
              >
                <div className="text-[9px] text-amber-700 font-medium truncate">{ann.type}</div>
                <div className="text-[8px] text-amber-600 truncate">{ann.content}</div>
                <button className="absolute -top-1.5 -right-1.5 w-4 h-4 bg-white border border-amber-300 rounded-full text-[8px] text-amber-500 hidden group-hover:flex items-center justify-center">
                  x
                </button>
              </div>
            ))}

            {annotationMode && (
              <div
                className="absolute inset-0 cursor-crosshair"
                onClick={(e) => {
                  const rect = (e.target as HTMLElement).closest('.relative')?.getBoundingClientRect();
                  if (!rect) return;
                  const newAnnotation: PrototypeAnnotation = {
                    id: `ann-${Date.now()}`,
                    x: e.clientX - rect.left - 50,
                    y: e.clientY - rect.top - 15,
                    width: 160,
                    height: 50,
                    type: 'comment',
                    content: '点击编辑标注内容...',
                    resolved: false,
                  };
                  setAnnotations((prev) => [...prev, newAnnotation]);
                }}
              />
            )}

            {annotationMode && (
              <div className="absolute bottom-2 left-2 text-[10px] text-amber-600 bg-white/90 px-2 py-1 rounded border border-amber-200">
                点击原型任意位置添加标注
              </div>
            )}
          </div>

          {/* Version history */}
          <div className="mt-4">
            <h4 className="text-[10px] font-medium text-slate-400 uppercase tracking-wider mb-2">版本历史</h4>
            <div className="space-y-1">
              {[
                { v: 'v3', time: '17:20', desc: '增加导出按钮位置标注' },
                { v: 'v2', time: '17:15', desc: '修正表格列对齐' },
                { v: 'v1', time: '17:00', desc: '初始原型' },
              ].map((ver) => (
                <div key={ver.v} className="flex items-center gap-2 text-xs py-1.5 px-2 rounded hover:bg-slate-50 cursor-pointer">
                  <span className={`w-1.5 h-1.5 rounded-full ${ver.v === 'v3' ? 'bg-blue-500' : 'bg-slate-300'}`} />
                  <span className="text-slate-500 font-mono text-[10px]">{ver.v}</span>
                  <span className="text-slate-400 text-[10px]">{ver.time}</span>
                  <span className="text-slate-600 truncate">{ver.desc}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* ================================================================
          Gate 1 审批台 (Modal)
          ================================================================ */}
      {showApproval && (
        <>
          <div className="fixed inset-0 bg-black/30 z-50" onClick={() => setShowApproval(false)} />
          <div className="fixed inset-x-0 top-16 bottom-12 mx-auto max-w-5xl bg-white rounded-2xl shadow-2xl z-50 flex flex-col overflow-hidden">
            {/* Approval Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 flex-shrink-0">
              <div>
                <h2 className="text-sm font-semibold text-slate-900">Gate 1: Spec 确认</h2>
                <p className="text-xs text-slate-500 mt-0.5">{reqId}: {requirement?.title || '加载中...'}</p>
              </div>
              <button onClick={() => setShowApproval(false)} className="p-1.5 hover:bg-slate-100 rounded-lg">
                <svg className="w-4 h-4 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            {/* Approval Content - 3 columns */}
            <div className="flex-1 flex overflow-hidden">
              {/* Spec */}
              <div className="w-[40%] overflow-y-auto p-4 border-r border-slate-100">
                <h3 className="text-[10px] font-medium text-slate-400 uppercase tracking-wider mb-3">Spec 文档</h3>
                {specSections.length === 0 ? (
                  <p className="text-xs text-slate-400">暂无 Spec 章节</p>
                ) : (
                  <div className="space-y-3">
                    {specSections.map((s) => (
                      <div key={s.id} className="text-xs">
                        <h4 className="font-medium text-slate-800">{s.title}</h4>
                        <p className="text-slate-500 mt-1 line-clamp-3">{s.content}</p>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Prototype */}
              <div className="w-[35%] overflow-y-auto p-4 border-r border-slate-100 bg-slate-50">
                <h3 className="text-[10px] font-medium text-slate-400 uppercase tracking-wider mb-3">UI 原型</h3>
                <div className="bg-white rounded-xl border border-slate-200 p-3">
                  <div className="bg-slate-100 rounded-lg h-40 flex items-center justify-center text-xs text-slate-400">
                    原型预览区域
                  </div>
                  <div className="mt-2 flex items-center justify-between text-[10px]">
                    <span className="text-slate-400">v3</span>
                    <button className="text-blue-600 hover:text-blue-700">在新窗口打开</button>
                  </div>
                </div>
              </div>

              {/* Agent Reviews */}
              <div className="w-[25%] overflow-y-auto p-4">
                <h3 className="text-[10px] font-medium text-slate-400 uppercase tracking-wider mb-3">Agent 自评</h3>
                <div className="space-y-2">
                  {[
                    { agent: 'TechReviewer', verdict: 'pass', comment: '技术方案可行，接口设计合理' },
                    { agent: 'UXReviewer', verdict: 'warn', comment: '建议导出按钮放到右上角，与筛选按钮同组' },
                    { agent: 'BusinessReviewer', verdict: 'pass', comment: '业务逻辑完整，覆盖核心场景' },
                  ].map((r, i) => (
                    <div key={i} className={`p-3 rounded-xl text-xs ${
                      r.verdict === 'pass' ? 'bg-emerald-50 border border-emerald-100' : 'bg-amber-50 border border-amber-100'
                    }`}>
                      <div className="flex items-center gap-1.5 mb-1">
                        <span className={`w-1.5 h-1.5 rounded-full ${r.verdict === 'pass' ? 'bg-emerald-500' : 'bg-amber-400'}`} />
                        <span className="font-medium text-slate-700">{r.agent}</span>
                        <span className={`text-[10px] px-1 py-0.5 rounded ${r.verdict === 'pass' ? 'bg-emerald-100 text-emerald-600' : 'bg-amber-100 text-amber-600'}`}>
                          {r.verdict === 'pass' ? '通过' : '建议改进'}
                        </span>
                      </div>
                      <p className="text-[10px] text-slate-500">{r.comment}</p>
                    </div>
                  ))}
                </div>

                {/* Action Buttons */}
                <div className="mt-6 space-y-2">
                  <button className="w-full py-2.5 bg-emerald-600 text-white text-xs font-medium rounded-xl hover:bg-emerald-700 transition-colors">
                    通过审批
                  </button>
                  <button className="w-full py-2.5 bg-white border border-red-200 text-red-600 text-xs font-medium rounded-xl hover:bg-red-50 transition-colors">
                    打回修订
                  </button>
                  <button className="w-full py-2.5 bg-white border border-slate-200 text-slate-500 text-xs font-medium rounded-xl hover:bg-slate-50 transition-colors">
                    带批注通过
                  </button>
                  <div className="pt-2">
                    <textarea
                      placeholder="输入审批意见（可选）..."
                      className="w-full text-xs border border-slate-200 rounded-xl p-3 outline-none focus:border-slate-400 resize-none h-20"
                    />
                  </div>
                </div>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

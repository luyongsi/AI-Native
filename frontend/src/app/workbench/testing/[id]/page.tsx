'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { api } from '@/lib/api';
import type { Requirement, TestCase as ApiTestCase } from '@/lib/types';

// ============================================================
// Local testing-specific types (not in @/lib/types)
// ============================================================
type TestCaseType = 'api' | 'ui' | 'manual';
type TestCasePriority = 'P0' | 'P1' | 'P2' | 'P3';
type TestCaseStatus = 'draft' | 'ready' | 'running' | 'passed' | 'failed' | 'blocked';
type TestReadinessStatus = 'not_started' | 'in_review' | 'approved' | 'rejected';
type UITestActionType = 'navigate' | 'click' | 'fill' | 'assert' | 'screenshot' | 'wait';

interface TestStep {
  order: number;
  action: string;
  expectedResult: string;
  data?: Record<string, unknown>;
}

interface TestCase {
  id: string;
  requirementId: string;
  title: string;
  description: string;
  type: TestCaseType;
  priority: TestCasePriority;
  status: TestCaseStatus;
  preconditions: string;
  steps: TestStep[];
  tags: string[];
  createdBy: string;
  createdAt: string;
  updatedAt: string;
  lastRunAt?: string;
  lastRunStatus?: 'passed' | 'failed';
}

interface ApiMockConfig {
  id: string;
  requirementId: string;
  endpoint: string;
  method: 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH';
  requestBody: string;
  expectedResponseStatus: number;
  expectedResponseBody: string;
  mockLatencyMs: number;
}

interface ApiTestResult {
  id: string;
  testCaseId: string;
  endpoint: string;
  method: string;
  responseStatus: number;
  responseBody: string;
  latencyMs: number;
  passed: boolean;
  assertionResults: { field: string; expected: string; actual: string; passed: boolean }[];
  executedAt: string;
}

interface UITestStepResult {
  order: number;
  actionType: UITestActionType;
  description: string;
  playwrightCode: string;
  status: 'pending' | 'active' | 'passed' | 'failed' | 'skipped';
  screenshotB64?: string;
  errorMessage?: string;
  durationMs?: number;
  coordinates?: { x: number; y: number };
}

interface UITestExecution {
  id: string;
  testCaseId: string;
  status: 'idle' | 'generating_script' | 'running' | 'completed' | 'failed';
  startedAt?: string;
  completedAt?: string;
  totalSteps: number;
  completedSteps: number;
  steps: UITestStepResult[];
}

interface TestReadinessReview {
  requirementId: string;
  status: TestReadinessStatus;
  reviewedBy: string;
  reviewedAt: string;
  comment: string;
  acceptanceCriteriaMet: boolean;
  interfaceContractReady: boolean;
  prototypeReady: boolean;
}

interface TestChatMessage {
  id: string;
  role: 'user' | 'agent' | 'system';
  content: string;
  timestamp: string;
  thinking?: string[];
  suggestions?: TestCaseSuggestion[];
}

interface TestCaseSuggestion {
  title: string;
  type: TestCaseType;
  priority: TestCasePriority;
  steps: TestStep[];
  accepted: boolean;
  rejected: boolean;
}

// ============================================================
// Helper: map API test case to local TestCase shape
// ============================================================
function mapApiTestCase(tc: ApiTestCase, reqId: string): TestCase {
  return {
    id: tc.id,
    requirementId: tc.requirementId || tc.req_id || reqId,
    title: tc.title,
    description: tc.description || '',
    type: (tc.type as TestCaseType) || 'api',
    priority: (tc.priority as TestCasePriority) || 'P2',
    status: (tc.status as TestCaseStatus) || 'draft',
    preconditions: tc.preconditions || '',
    steps: (tc.steps as TestStep[]) || [],
    tags: tc.tags || [],
    createdBy: tc.createdBy || '系统',
    createdAt: tc.createdAt || tc.created_at || '',
    updatedAt: tc.updatedAt || tc.updated_at || '',
    lastRunAt: tc.lastRunAt || tc.last_run_at,
    lastRunStatus: tc.lastRunStatus as 'passed' | 'failed' | undefined,
  };
}

// ============================================================
// Helper: Status Badge
// ============================================================
const statusBadgeColors: Record<string, string> = {
  draft: 'bg-slate-100 text-slate-500',
  ready: 'bg-blue-100 text-blue-600',
  running: 'bg-purple-100 text-purple-600',
  passed: 'bg-emerald-100 text-emerald-600',
  failed: 'bg-red-100 text-red-600',
  blocked: 'bg-amber-100 text-amber-600',
};

const statusLabels: Record<string, string> = {
  draft: '草稿',
  ready: '就绪',
  running: '执行中',
  passed: '通过',
  failed: '失败',
  blocked: '阻塞',
};

function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${statusBadgeColors[status] || 'bg-slate-100 text-slate-500'}`}>
      {statusLabels[status] || status}
    </span>
  );
}

// ============================================================
// Helper: Priority Badge
// ============================================================
const priorityColors: Record<string, string> = {
  P0: 'bg-red-50 text-red-600',
  P1: 'bg-amber-50 text-amber-600',
  P2: 'bg-blue-50 text-blue-600',
  P3: 'bg-slate-100 text-slate-500',
};

function PriorityBadge({ priority }: { priority: string }) {
  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${priorityColors[priority] || ''}`}>
      {priority}
    </span>
  );
}

// ============================================================
// Helper: Type Icon
// ============================================================
const typeConfig: Record<string, { icon: string; label: string; color: string }> = {
  api: { icon: '🔌', label: 'API', color: 'bg-blue-50 text-blue-600 border-blue-100' },
  ui: { icon: '🖥️', label: 'UI', color: 'bg-purple-50 text-purple-600 border-purple-100' },
  manual: { icon: '✋', label: '手动', color: 'bg-amber-50 text-amber-600 border-amber-100' },
};

function TypeBadge({ type }: { type: TestCaseType }) {
  const cfg = typeConfig[type];
  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded-full border ${cfg.color}`}>
      {cfg.icon} {cfg.label}
    </span>
  );
}

// ============================================================
// Main Page Component
// ============================================================
export default function TestingWorkbenchPage() {
  const params = useParams();
  const router = useRouter();
  const reqId = (params?.id as string) || 'REQ-789';

  // ---- Data loading states ----
  const [requirementLoading, setRequirementLoading] = useState(true);
  const [requirementError, setRequirementError] = useState<string | null>(null);
  const [testCasesLoading, setTestCasesLoading] = useState(true);
  const [testCasesError, setTestCasesError] = useState<string | null>(null);
  const [chatLoading, setChatLoading] = useState(true);

  const [requirement, setRequirement] = useState<Requirement | null>(null);

  const fetchRequirement = useCallback(() => {
    setRequirementLoading(true);
    setRequirementError(null);
    api
      .getRequirement(reqId)
      .then((data) => setRequirement(data))
      .catch((err) =>
        setRequirementError(err instanceof Error ? err.message : '加载需求失败')
      )
      .finally(() => setRequirementLoading(false));
  }, [reqId]);

  const fetchTestCases = useCallback(() => {
    setTestCasesLoading(true);
    setTestCasesError(null);
    api
      .getTestCases(reqId)
      .then((res) => {
        const items = (res.items || []).map((tc) => mapApiTestCase(tc, reqId));
        setTestCases(items);
      })
      .catch((err) =>
        setTestCasesError(err instanceof Error ? err.message : '加载测试用例失败')
      )
      .finally(() => setTestCasesLoading(false));
  }, [reqId]);

  useEffect(() => {
    fetchRequirement();
    fetchTestCases();
    // Load chat messages
    setChatLoading(true);
    api
      .getChatMessages(reqId)
      .then((res) => {
        const msgs: TestChatMessage[] = (res.messages || []).map((m, i) => ({
          id: `chat-${i}`,
          role: (m.role as 'user' | 'agent' | 'system') || 'agent',
          content: m.content,
          timestamp: m.time || '',
          thinking: undefined,
          suggestions: undefined,
        }));
        setChatMessages(msgs);
      })
      .catch(() => {
        // Keep empty chat on failure
      })
      .finally(() => setChatLoading(false));
  }, [fetchRequirement, fetchTestCases, reqId]);

  // ---- Panel widths (28/44/28 split) ----
  const [leftWidth, setLeftWidth] = useState(28);
  const [rightWidth, setRightWidth] = useState(28);
  const isDragging = useRef<'left' | 'right' | null>(null);

  // ---- Left Pane: Context tabs ----
  const [activeContextTab, setActiveContextTab] = useState<'acceptance' | 'contract' | 'prototype'>('acceptance');

  // ---- Readiness state ----
  const [readinessStatus, setReadinessStatus] = useState<TestReadinessStatus>('not_started');
  const [showReadinessModal, setShowReadinessModal] = useState(false);
  const [readinessComment, setReadinessComment] = useState('');

  // ---- Center Pane: Test Cases + AI Chat ----
  const [testCases, setTestCases] = useState<TestCase[]>([]);
  const [selectedTestCase, setSelectedTestCase] = useState<TestCase | null>(null);
  const [editingTestCase, setEditingTestCase] = useState<TestCase | null>(null);
  const [showNewForm, setShowNewForm] = useState(false);
  const [activeCenterTab, setActiveCenterTab] = useState<'list' | 'ai_chat'>('list');

  // New/Edit form state
  const [formTitle, setFormTitle] = useState('');
  const [formType, setFormType] = useState<TestCaseType>('api');
  const [formPriority, setFormPriority] = useState<TestCasePriority>('P1');
  const [formPreconditions, setFormPreconditions] = useState('');
  const [formSteps, setFormSteps] = useState<TestStep[]>([
    { order: 1, action: '', expectedResult: '' },
  ]);

  // ---- Chat Messages ----
  const [chatMessages, setChatMessages] = useState<TestChatMessage[]>([]);
  const [chatInput, setChatInput] = useState('');
  const [aiGenerating, setAiGenerating] = useState(false);

  // ---- Right Pane: Execution ----
  const [activeExecTab, setActiveExecTab] = useState<'api_mock' | 'ui_auto'>('api_mock');

  // API Mock state (live tools, not persisted — local state only)
  const [apiMockConfigs] = useState<ApiMockConfig[]>([]);
  const [selectedMockConfig, setSelectedMockConfig] = useState<ApiMockConfig | null>(null);
  const [mockRequestBody, setMockRequestBody] = useState('');
  const [mockLoading, setMockLoading] = useState(false);
  const [mockResult, setMockResult] = useState<ApiTestResult | null>(null);

  // UI Automation state (live tools, not persisted — local state only)
  const [uiExecution, setUiExecution] = useState<UITestExecution | null>(null);
  const [uiRunning, setUiRunning] = useState(false);
  const [uiCurrentStepIdx, setUiCurrentStepIdx] = useState(-1);
  const [showScriptPreview, setShowScriptPreview] = useState(false);

  // ---- Toast ----
  const [toast, setToast] = useState<string | null>(null);
  const showToast = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(null), 2500);
  };

  // ============================================================
  // Resize Handlers
  // ============================================================
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

  const middleWidth = 100 - leftWidth - rightWidth;

  // ============================================================
  // Center Pane: Test Case CRUD
  // ============================================================
  const openNewForm = () => {
    setFormTitle('');
    setFormType('api');
    setFormPriority('P1');
    setFormPreconditions('');
    setFormSteps([{ order: 1, action: '', expectedResult: '' }]);
    setShowNewForm(true);
    setEditingTestCase(null);
  };

  const openEditForm = (tc: TestCase) => {
    setFormTitle(tc.title);
    setFormType(tc.type);
    setFormPriority(tc.priority);
    setFormPreconditions(tc.preconditions);
    setFormSteps([...tc.steps]);
    setEditingTestCase(tc);
    setShowNewForm(true);
  };

  const addStep = () => {
    setFormSteps((prev) => [...prev, { order: prev.length + 1, action: '', expectedResult: '' }]);
  };

  const removeStep = (idx: number) => {
    setFormSteps((prev) => prev.filter((_, i) => i !== idx).map((s, i) => ({ ...s, order: i + 1 })));
  };

  const updateStep = (idx: number, field: 'action' | 'expectedResult', value: string) => {
    setFormSteps((prev) => prev.map((s, i) => (i === idx ? { ...s, [field]: value } : s)));
  };

  const saveTestCase = () => {
    const now = new Date().toLocaleString('zh-CN', { hour: '2-digit', minute: '2-digit', month: '2-digit', day: '2-digit' });
    if (editingTestCase) {
      // Update locally; optionally call api.updateTestCase(reqId, editingTestCase.id, data)
      setTestCases((prev) =>
        prev.map((tc) =>
          tc.id === editingTestCase.id
            ? { ...tc, title: formTitle, type: formType, priority: formPriority, preconditions: formPreconditions, steps: formSteps, updatedAt: now }
            : tc
        )
      );
      showToast('测试用例已更新');
    } else {
      const newTC: TestCase = {
        id: `TC-${String(testCases.length + 1).padStart(3, '0')}`,
        requirementId: reqId,
        title: formTitle,
        description: '',
        type: formType,
        priority: formPriority,
        status: 'draft',
        preconditions: formPreconditions,
        steps: formSteps,
        tags: [],
        createdBy: '当前用户',
        createdAt: now,
        updatedAt: now,
      };
      setTestCases((prev) => [...prev, newTC]);
      // Attempt to persist to API
      api.createTestCase(reqId, {
        title: formTitle,
        type: formType,
        priority: formPriority,
        preconditions: formPreconditions,
        steps: formSteps,
        status: 'draft',
      }).catch(() => { /* non-blocking */ });
      showToast('测试用例已创建');
    }
    setShowNewForm(false);
    setEditingTestCase(null);
  };

  // ============================================================
  // Center Pane: AI Chat
  // ============================================================
  const sendChat = async () => {
    if (!chatInput.trim()) return;
    const userMsg: TestChatMessage = {
      id: `tmsg-${Date.now()}`,
      role: 'user',
      content: chatInput,
      timestamp: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
    };
    setChatMessages((prev) => [...prev, userMsg]);
    const currentInput = chatInput;
    setChatInput('');
    setAiGenerating(true);

    try {
      const response = await api.sendChatMessage(reqId, currentInput);
      const aiMsg: TestChatMessage = {
        id: `tmsg-${Date.now() + 1}`,
        role: 'agent',
        content: response.reply || '收到，我已分析你的测试需求。',
        timestamp: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
        thinking: undefined,
        suggestions: undefined,
      };
      setChatMessages((prev) => [...prev, aiMsg]);
    } catch {
      // Fallback to simulated response
      setTimeout(() => {
        const aiMsg: TestChatMessage = {
          id: `tmsg-${Date.now() + 1}`,
          role: 'agent',
          content: '收到，我根据你的补充生成了 2 条建议用例：',
          timestamp: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
          thinking: ['解析新增需求描述', '对比现有用例覆盖情况', '识别需要补充的测试场景', '生成用例建议'],
          suggestions: [
            {
              title: '导出接口-并发请求处理',
              type: 'api',
              priority: 'P2',
              steps: [
                { order: 1, action: '同时发起 10 个 POST /api/orders/export 请求', expectedResult: '所有请求均正常返回，无数据库锁超时' },
                { order: 2, action: '验证各请求返回的 downloadUrl 互不相同', expectedResult: '每个 downloadUrl 对应独立的导出文件' },
              ],
              accepted: false,
              rejected: false,
            },
            {
              title: '导出按钮-加载状态验证',
              type: 'ui',
              priority: 'P2',
              steps: [
                { order: 1, action: '点击导出按钮后观察按钮状态', expectedResult: '按钮变为"导出中..."并禁用' },
                { order: 2, action: '检查是否有加载进度提示', expectedResult: '显示进度条或加载动画' },
              ],
              accepted: false,
              rejected: false,
            },
          ],
        };
        setChatMessages((prev) => [...prev, aiMsg]);
      }, 2000);
    } finally {
      setAiGenerating(false);
    }
  };

  const acceptSuggestion = (msgId: string, suggIdx: number) => {
    const msg = chatMessages.find((m) => m.id === msgId);
    if (!msg?.suggestions) return;
    const sugg = msg.suggestions[suggIdx];
    msg.suggestions[suggIdx] = { ...sugg, accepted: true };
    setChatMessages([...chatMessages]);

    const now = new Date().toLocaleString('zh-CN', { hour: '2-digit', minute: '2-digit', month: '2-digit', day: '2-digit' });
    const newTC: TestCase = {
      id: `TC-${String(testCases.length + 1).padStart(3, '0')}`,
      requirementId: reqId,
      title: sugg.title,
      description: '',
      type: sugg.type,
      priority: sugg.priority,
      status: 'ready',
      preconditions: '',
      steps: sugg.steps,
      tags: ['AI生成'],
      createdBy: 'AI',
      createdAt: now,
      updatedAt: now,
    };
    setTestCases((prev) => [...prev, newTC]);
    showToast(`已添加用例: ${sugg.title}`);
  };

  const rejectSuggestion = (msgId: string, suggIdx: number) => {
    const msg = chatMessages.find((m) => m.id === msgId);
    if (!msg?.suggestions) return;
    msg.suggestions[suggIdx] = { ...msg.suggestions[suggIdx], rejected: true };
    setChatMessages([...chatMessages]);
  };

  // ============================================================
  // Right Pane: API Mock
  // ============================================================
  const sendMockRequest = () => {
    if (!selectedMockConfig) return;
    setMockLoading(true);
    setMockResult(null);

    const latency = selectedMockConfig.mockLatencyMs;
    setTimeout(() => {
      let passed = true;
      const assertions: ApiTestResult['assertionResults'] = [];

      try {
        JSON.parse(selectedMockConfig.expectedResponseBody);
        assertions.push(
          { field: 'status', expected: String(selectedMockConfig.expectedResponseStatus), actual: String(selectedMockConfig.expectedResponseStatus), passed: true },
          { field: 'body', expected: 'valid JSON', actual: 'valid JSON', passed: true }
        );
      } catch {
        passed = false;
        assertions.push({ field: 'body', expected: 'valid JSON', actual: 'parse error', passed: false });
      }

      const result: ApiTestResult = {
        id: `api-result-${Date.now()}`,
        testCaseId: 'mock-live',
        endpoint: selectedMockConfig.endpoint,
        method: selectedMockConfig.method,
        responseStatus: selectedMockConfig.expectedResponseStatus,
        responseBody: selectedMockConfig.expectedResponseBody,
        latencyMs: latency,
        passed,
        assertionResults: assertions,
        executedAt: new Date().toLocaleString('zh-CN'),
      };
      setMockResult(result);
      setMockLoading(false);
      showToast(passed ? 'Mock 请求成功' : 'Mock 请求失败');
    }, latency + 100);
  };

  // ============================================================
  // Right Pane: UI Automation
  // ============================================================
  const runUITest = () => {
    // Hardcoded fallback steps - avoids depending on mockUITestExecutions module order
    const fallbackSteps = [
      { order: 1, actionType: 'navigate' as const, description: '打开订单列表页 /orders', playwrightCode: "await page.goto('/orders');", status: 'passed' as const, durationMs: 1230 },
      { order: 2, actionType: 'assert' as const, description: '验证右上角存在"批量导出"按钮', playwrightCode: "await expect(exportBtn).toBeVisible();", status: 'passed' as const, durationMs: 450, coordinates: { x: 680, y: 358 } },
      { order: 3, actionType: 'click' as const, description: '点击"批量导出"按钮', playwrightCode: "await page.click('button:has-text(\"批量导出\")');", status: 'passed' as const, durationMs: 820, coordinates: { x: 680, y: 358 } },
      { order: 4, actionType: 'assert' as const, description: '验证弹出导出配置对话框', playwrightCode: "await expect(dialog).toBeVisible();", status: 'passed' as const, durationMs: 380 },
    ];

    setUiRunning(true);
    setUiCurrentStepIdx(-1);
    const steps = fallbackSteps.map((s) => ({
      ...s,
      status: 'pending' as const,
      screenshotB64: '',
    }));
    const execution: UITestExecution = {
      id: `ui-live-${Date.now()}`,
      testCaseId: 'TC-002',
      status: 'running',
      startedAt: new Date().toISOString(),
      completedAt: undefined,
      steps,
      totalSteps: steps.length,
      completedSteps: 0,
    };
    setUiExecution(execution);

    // Animate through steps
    let stepIdx = 0;
    const advance = () => {
      if (stepIdx >= steps.length) {
        // Complete
        setUiExecution((prev) => {
          if (!prev) return null;
          return {
            ...prev,
            status: 'completed',
            completedAt: new Date().toISOString(),
            completedSteps: prev.totalSteps,
          };
        });
        setUiRunning(false);
        setUiCurrentStepIdx(steps.length - 1);
        return;
      }

      setUiCurrentStepIdx(stepIdx);
      setUiExecution((prev) => {
        if (!prev) return null;
        const newSteps = [...prev.steps];
        newSteps[stepIdx] = { ...newSteps[stepIdx], status: 'active' };
        return { ...prev, steps: newSteps, completedSteps: stepIdx };
      });

      // After a delay, mark as passed/failed
      setTimeout(() => {
        const resolvedIdx = stepIdx; // capture locally to avoid closure issues
        if (resolvedIdx >= steps.length) return;
        setUiExecution((prev) => {
          if (!prev) return null;
          const newSteps = [...prev.steps];
          if (resolvedIdx >= newSteps.length) return prev;
          newSteps[resolvedIdx] = { ...newSteps[resolvedIdx], status: steps[resolvedIdx].status };
          return { ...prev, steps: newSteps };
        });
        stepIdx = resolvedIdx + 1;
        setTimeout(advance, 600);
      }, steps[stepIdx].durationMs || 800);
    };
    advance();
  };

  // ============================================================
  // Labels & color maps
  // ============================================================
  const readinessLabelMap: Record<TestReadinessStatus, string> = {
    not_started: '未开始',
    in_review: '待审批',
    approved: '已通过',
    rejected: '已打回',
  };

  const readinessColorMap: Record<TestReadinessStatus, string> = {
    not_started: 'bg-slate-100 text-slate-500',
    in_review: 'bg-amber-100 text-amber-600',
    approved: 'bg-emerald-100 text-emerald-600',
    rejected: 'bg-red-100 text-red-600',
  };

  // ============================================================
  // Loading / Error states for requirement data
  // ============================================================
  if (requirementLoading) {
    return (
      <div className="h-[calc(100vh-5rem)] flex items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <div className="w-8 h-8 border-2 border-slate-200 border-t-slate-600 rounded-full animate-spin" />
          <p className="text-sm text-slate-400">加载需求数据...</p>
        </div>
      </div>
    );
  }

  if (requirementError) {
    return (
      <div className="h-[calc(100vh-5rem)] flex items-center justify-center">
        <div className="bg-red-50 border border-red-200 rounded-xl p-6 text-center max-w-md">
          <p className="text-sm font-medium text-red-700 mb-2">加载需求失败</p>
          <p className="text-xs text-red-500">{requirementError}</p>
          <button
            onClick={fetchRequirement}
            className="mt-3 text-xs px-4 py-1.5 bg-white border border-red-200 rounded-lg text-red-600 hover:bg-red-50"
          >
            重试
          </button>
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

  // ============================================================
  // Render
  // ============================================================
  return (
    <div className="h-[calc(100vh-5rem)] flex flex-col overflow-hidden">
      {/* ================================================================
          Top Status Bar
          ================================================================ */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-slate-200 bg-white flex-shrink-0">
        <div className="flex items-center gap-3">
          <button
            onClick={() => router.push('/workbench/testing')}
            className="text-xs text-slate-400 hover:text-slate-600 transition-colors flex items-center gap-1"
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
            </svg>
            返回
          </button>
          <span className="text-[10px] font-mono text-slate-400 bg-slate-50 px-1.5 py-0.5 rounded">{reqId}</span>
          <span className="text-sm font-semibold text-slate-800">{requirement.title}</span>
        </div>

        <div className="flex items-center gap-3">
          <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${readinessColorMap[readinessStatus]}`}>
            测试就绪: {readinessLabelMap[readinessStatus]}
          </span>

          <button
            onClick={() => setShowReadinessModal(true)}
            className="px-3 py-1.5 bg-emerald-600 text-white text-[10px] font-medium rounded-lg hover:bg-emerald-700 transition-colors"
          >
            通过测试就绪
          </button>
          <button
            onClick={() => {
              setReadinessStatus('rejected');
              showToast('已打回测试就绪审批');
            }}
            className="px-3 py-1.5 bg-white border border-red-200 text-red-600 text-[10px] font-medium rounded-lg hover:bg-red-50 transition-colors"
          >
            打回
          </button>
        </div>
      </div>

      {/* ================================================================
          3-Pane Layout
          ================================================================ */}
      <div className="flex-1 flex overflow-hidden">
        {/* ============================================================
            Left Pane: Context Panel (28%)
            ============================================================ */}
        <div className="flex flex-col bg-white border-r border-slate-200" style={{ width: `${leftWidth}%` }}>
          <div className="flex items-center px-3 py-2 border-b border-slate-100 flex-shrink-0">
            <h2 className="text-xs font-semibold text-slate-800">需求上下文</h2>
          </div>

          {/* Context Tabs */}
          <div className="flex border-b border-slate-100 flex-shrink-0">
            {[
              { key: 'acceptance' as const, label: '验收标准' },
              { key: 'contract' as const, label: '接口契约' },
              { key: 'prototype' as const, label: '原型预览' },
            ].map((tab) => (
              <button
                key={tab.key}
                onClick={() => setActiveContextTab(tab.key)}
                className={`flex-1 text-[10px] py-2 font-medium transition-colors ${
                  activeContextTab === tab.key
                    ? 'text-slate-800 border-b-2 border-slate-800'
                    : 'text-slate-400 hover:text-slate-600'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {/* Context Content */}
          <div className="flex-1 overflow-y-auto p-3">
            {activeContextTab === 'acceptance' && (
              <div className="text-xs text-slate-700 space-y-2">
                <h3 className="font-semibold text-slate-800 mb-2">验收标准</h3>
                <div className="whitespace-pre-wrap leading-relaxed bg-slate-50 rounded-lg p-3 border border-slate-100">
                  {requirement.specSections?.find(s => s.id === 's4')?.content || '暂无验收标准'}
                </div>

                {/* Checklist */}
                {requirement.specSections?.find(s => s.id === 's4')?.content && (
                  <div className="mt-3 space-y-1.5">
                    <h4 className="text-[10px] font-medium text-slate-400 uppercase tracking-wider">检查清单</h4>
                    {[
                      '支持 Excel 和 CSV 两种导出格式',
                      '支持按日期范围和订单状态筛选',
                      '单次导出上限 10 万条',
                      '大文件异步导出 + 飞书通知',
                      '按钮权限：仅运营、管理员可见',
                    ].map((item, i) => (
                      <div key={i} className="flex items-center gap-2 text-[10px] text-slate-600">
                        <svg className="w-3 h-3 text-emerald-500 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                        </svg>
                        {item}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {activeContextTab === 'contract' && (
              <div className="text-xs text-slate-700 space-y-2">
                <h3 className="font-semibold text-slate-800 mb-2">接口契约</h3>
                <div className="whitespace-pre-wrap leading-relaxed bg-slate-50 rounded-lg p-3 border border-slate-100 text-[11px] font-mono">
                  {requirement.specSections?.find(s => s.id === 's3')?.content || '暂无接口契约'}
                </div>
                <div className="mt-3 text-[10px] text-slate-400">
                  关联 API Mock 配置: {apiMockConfigs.filter(c => c.requirementId === reqId).length} 个端点
                </div>
              </div>
            )}

            {activeContextTab === 'prototype' && (
              <div className="text-xs">
                <h3 className="font-semibold text-slate-800 mb-2">原型预览</h3>
                <div className="bg-white rounded-lg border border-slate-200 overflow-hidden">
                  <div className="bg-slate-100 px-2 py-1.5 flex items-center gap-1 border-b border-slate-200">
                    <span className="w-1.5 h-1.5 rounded-full bg-red-400" />
                    <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                    <span className="ml-1 text-[9px] text-slate-400 bg-white rounded px-1.5 py-0.5">app.example.com/orders</span>
                  </div>
                  <div className="p-3 space-y-2">
                    <div className="flex justify-between items-center">
                      <span className="text-[11px] font-medium text-slate-700">订单管理</span>
                      <div className="flex gap-1">
                        <div className="text-[9px] px-1.5 py-1 border border-slate-200 rounded text-slate-400">筛选</div>
                        <div className="text-[9px] px-1.5 py-1 border border-slate-200 rounded text-slate-400">刷新</div>
                        <div className="text-[9px] px-1.5 py-1 bg-blue-600 text-white rounded font-medium">批量导出</div>
                      </div>
                    </div>
                    <div className="border border-slate-100 rounded p-2 text-[9px] text-slate-400">
                      表格区域 (4条订单记录)
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Left Resize Handle */}
        <div
          className="w-1 cursor-col-resize hover:bg-slate-300 transition-colors flex-shrink-0 bg-transparent z-10"
          onMouseDown={() => { isDragging.current = 'left'; }}
        />

        {/* ============================================================
            Center Pane: Test Editor (middle%)
            ============================================================ */}
        <div className="flex flex-col bg-white" style={{ width: `${middleWidth}%` }}>
          <div className="flex items-center justify-between px-3 py-2 border-b border-slate-100 flex-shrink-0">
            <div className="flex items-center gap-2">
              <h2 className="text-xs font-semibold text-slate-800">测试用例</h2>
              <span className="text-[10px] bg-slate-100 text-slate-500 px-1.5 py-0.5 rounded-full">{testCases.length}</span>
            </div>
            <div className="flex items-center gap-1">
              <button
                onClick={() => setActiveCenterTab('list')}
                className={`text-[10px] px-2 py-1 rounded-lg ${activeCenterTab === 'list' ? 'bg-slate-900 text-white' : 'text-slate-500 hover:bg-slate-100'}`}
              >
                用例列表
              </button>
              <button
                onClick={() => setActiveCenterTab('ai_chat')}
                className={`text-[10px] px-2 py-1 rounded-lg ${activeCenterTab === 'ai_chat' ? 'bg-slate-900 text-white' : 'text-slate-500 hover:bg-slate-100'}`}
              >
                AI 对话生成
              </button>
            </div>
          </div>

          <div className="flex-1 overflow-hidden">
            {/* === Test Case List === */}
            {activeCenterTab === 'list' && (
              <div className="h-full flex flex-col">
                {/* Test Cases Loading/Error */}
                {testCasesLoading && (
                  <div className="flex-1 flex items-center justify-center">
                    <div className="flex flex-col items-center gap-2">
                      <div className="w-5 h-5 border-2 border-slate-200 border-t-slate-500 rounded-full animate-spin" />
                      <p className="text-[10px] text-slate-400">加载测试用例...</p>
                    </div>
                  </div>
                )}
                {testCasesError && !testCasesLoading && (
                  <div className="flex-1 flex items-center justify-center p-4">
                    <div className="text-center">
                      <p className="text-[10px] text-red-500 mb-2">{testCasesError}</p>
                      <button
                        onClick={fetchTestCases}
                        className="text-[10px] px-3 py-1 bg-white border border-red-200 rounded-lg text-red-600 hover:bg-red-50"
                      >
                        重试
                      </button>
                    </div>
                  </div>
                )}
                {!testCasesLoading && !testCasesError && (
                  <>
                    {/* Toolbar */}
                    <div className="flex items-center gap-2 px-3 py-2 border-b border-slate-50 flex-shrink-0">
                      <input
                        placeholder="搜索用例..."
                        className="text-[10px] border border-slate-200 rounded-lg px-2 py-1 outline-none focus:border-slate-400 w-36"
                      />
                      <select className="text-[10px] border border-slate-200 rounded-lg px-2 py-1 outline-none text-slate-500">
                        <option>全部类型</option>
                        <option>API</option>
                        <option>UI</option>
                        <option>手动</option>
                      </select>
                      <select className="text-[10px] border border-slate-200 rounded-lg px-2 py-1 outline-none text-slate-500">
                        <option>全部状态</option>
                        <option>就绪</option>
                        <option>通过</option>
                        <option>失败</option>
                        <option>草稿</option>
                      </select>
                      <div className="flex-1" />
                      <button
                        onClick={openNewForm}
                        className="flex items-center gap-1 px-2 py-1 bg-slate-900 text-white text-[10px] font-medium rounded-lg hover:bg-slate-800 transition-colors"
                      >
                        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
                        </svg>
                        新建
                      </button>
                    </div>

                    {/* Test Case Cards */}
                    <div className="flex-1 overflow-y-auto p-2 space-y-1.5">
                      {testCases.length === 0 ? (
                        <div className="flex flex-col items-center justify-center h-full text-center text-slate-400 gap-2">
                          <svg className="w-8 h-8" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                          </svg>
                          <p className="text-[10px]">暂无测试用例，点击"新建"或使用 AI 生成</p>
                        </div>
                      ) : (
                        testCases.map((tc) => (
                          <div
                            key={tc.id}
                            onClick={() => {
                              setSelectedTestCase(tc);
                              setShowNewForm(false);
                            }}
                            className={`w-full text-left p-2.5 rounded-lg border transition-colors cursor-pointer ${
                              selectedTestCase?.id === tc.id ? 'border-slate-400 bg-slate-50' : 'border-slate-100 hover:border-slate-200 hover:bg-slate-50/50'
                            }`}
                          >
                            <div className="flex items-start justify-between gap-2">
                              <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-1.5 mb-1">
                                  <span className="text-[10px] font-mono text-slate-400">{tc.id}</span>
                                  <TypeBadge type={tc.type} />
                                  <PriorityBadge priority={tc.priority} />
                                  <StatusBadge status={tc.status} />
                                </div>
                                <h3 className="text-xs font-medium text-slate-800 truncate">{tc.title}</h3>
                                <div className="flex items-center gap-2 mt-1 text-[9px] text-slate-400">
                                  <span>{tc.steps.length} 个步骤</span>
                                  <span>·</span>
                                  <span>{tc.createdBy}</span>
                                  <span>·</span>
                                  <span>{tc.updatedAt}</span>
                                  {tc.lastRunStatus && (
                                    <>
                                      <span>·</span>
                                      <span className={tc.lastRunStatus === 'passed' ? 'text-emerald-500' : 'text-red-500'}>
                                        {tc.lastRunStatus === 'passed' ? '最后通过' : '最后失败'}
                                      </span>
                                    </>
                                  )}
                                </div>
                              </div>
                              <button
                                onClick={(e) => { e.stopPropagation(); openEditForm(tc); }}
                                className="p-1 hover:bg-slate-100 rounded text-slate-400 hover:text-slate-600 flex-shrink-0"
                              >
                                <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                                  <path strokeLinecap="round" strokeLinejoin="round" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                                </svg>
                              </button>
                            </div>
                          </div>
                        ))
                      )}
                    </div>

                    {/* Selected Test Case Detail */}
                    {selectedTestCase && !showNewForm && (
                      <div className="border-t border-slate-200 flex-shrink-0 max-h-[40%] overflow-y-auto p-3 bg-slate-50">
                        <div className="flex items-center justify-between mb-2">
                          <h3 className="text-xs font-semibold text-slate-800">{selectedTestCase.title}</h3>
                          <div className="flex items-center gap-1">
                            <button
                              onClick={() => openEditForm(selectedTestCase)}
                              className="text-[9px] px-2 py-1 bg-white border border-slate-200 rounded text-slate-500 hover:bg-slate-100"
                            >
                              编辑
                            </button>
                            <button
                              onClick={() => {
                                if (selectedTestCase.type === 'api') {
                                  setActiveExecTab('api_mock');
                                } else if (selectedTestCase.type === 'ui') {
                                  setActiveExecTab('ui_auto');
                                }
                              }}
                              className="text-[9px] px-2 py-1 bg-slate-900 text-white rounded hover:bg-slate-800"
                            >
                              执行
                            </button>
                          </div>
                        </div>

                        <div className="grid grid-cols-3 gap-2 text-[10px] mb-2">
                          <div>
                            <span className="text-slate-400">类型</span>
                            <p className="text-slate-700 font-medium">{typeConfig[selectedTestCase.type].label}</p>
                          </div>
                          <div>
                            <span className="text-slate-400">优先级</span>
                            <p className="text-slate-700 font-medium">{selectedTestCase.priority}</p>
                          </div>
                          <div>
                            <span className="text-slate-400">状态</span>
                            <StatusBadge status={selectedTestCase.status} />
                          </div>
                        </div>

                        {selectedTestCase.preconditions && (
                          <div className="mb-2">
                            <span className="text-[9px] text-slate-400">前置条件</span>
                            <p className="text-[10px] text-slate-600 mt-0.5">{selectedTestCase.preconditions}</p>
                          </div>
                        )}

                        <div>
                          <span className="text-[9px] text-slate-400">测试步骤</span>
                          <div className="space-y-1 mt-1">
                            {selectedTestCase.steps.map((step, i) => (
                              <div key={i} className="flex gap-2 text-[10px] bg-white rounded-lg p-2 border border-slate-100">
                                <span className="text-slate-400 font-mono flex-shrink-0">{step.order}.</span>
                                <div className="flex-1 min-w-0">
                                  <p className="text-slate-700">{step.action}</p>
                                  <p className="text-slate-400 mt-0.5">→ {step.expectedResult}</p>
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      </div>
                    )}

                    {/* New/Edit Test Case Form */}
                    {showNewForm && (
                      <div className="border-t border-slate-200 flex-shrink-0 max-h-[55%] overflow-y-auto p-3 bg-slate-50">
                        <h3 className="text-xs font-semibold text-slate-800 mb-2">
                          {editingTestCase ? '编辑测试用例' : '新建测试用例'}
                        </h3>

                        <div className="space-y-2">
                          <div>
                            <label className="text-[9px] text-slate-400 block mb-0.5">标题</label>
                            <input
                              value={formTitle}
                              onChange={(e) => setFormTitle(e.target.value)}
                              className="text-[10px] border border-slate-200 rounded-lg px-2 py-1.5 outline-none focus:border-slate-400 w-full"
                              placeholder="用例标题"
                            />
                          </div>

                          <div className="flex gap-2">
                            <div className="flex-1">
                              <label className="text-[9px] text-slate-400 block mb-0.5">类型</label>
                              <select
                                value={formType}
                                onChange={(e) => setFormType(e.target.value as TestCaseType)}
                                className="text-[10px] border border-slate-200 rounded-lg px-2 py-1.5 outline-none w-full"
                              >
                                <option value="api">API 接口</option>
                                <option value="ui">UI 交互</option>
                                <option value="manual">手动测试</option>
                              </select>
                            </div>
                            <div className="flex-1">
                              <label className="text-[9px] text-slate-400 block mb-0.5">优先级</label>
                              <select
                                value={formPriority}
                                onChange={(e) => setFormPriority(e.target.value as TestCasePriority)}
                                className="text-[10px] border border-slate-200 rounded-lg px-2 py-1.5 outline-none w-full"
                              >
                                <option value="P0">P0 - 阻塞</option>
                                <option value="P1">P1 - 高</option>
                                <option value="P2">P2 - 中</option>
                                <option value="P3">P3 - 低</option>
                              </select>
                            </div>
                          </div>

                          <div>
                            <label className="text-[9px] text-slate-400 block mb-0.5">前置条件</label>
                            <input
                              value={formPreconditions}
                              onChange={(e) => setFormPreconditions(e.target.value)}
                              className="text-[10px] border border-slate-200 rounded-lg px-2 py-1.5 outline-none focus:border-slate-400 w-full"
                              placeholder="描述测试前置条件..."
                            />
                          </div>

                          <div>
                            <div className="flex items-center justify-between mb-1">
                              <label className="text-[9px] text-slate-400">测试步骤</label>
                              <button
                                onClick={addStep}
                                className="text-[9px] text-blue-600 hover:text-blue-700 font-medium"
                              >
                                + 添加步骤
                              </button>
                            </div>
                            <div className="space-y-1">
                              {formSteps.map((step, i) => (
                                <div key={i} className="flex gap-1.5 items-start">
                                  <span className="text-[10px] text-slate-400 font-mono pt-1.5">{step.order}.</span>
                                  <div className="flex-1 space-y-1">
                                    <input
                                      value={step.action}
                                      onChange={(e) => updateStep(i, 'action', e.target.value)}
                                      className="text-[10px] border border-slate-200 rounded px-2 py-1 outline-none focus:border-slate-400 w-full"
                                      placeholder="操作描述..."
                                    />
                                    <input
                                      value={step.expectedResult}
                                      onChange={(e) => updateStep(i, 'expectedResult', e.target.value)}
                                      className="text-[10px] border border-slate-200 rounded px-2 py-1 outline-none focus:border-slate-400 w-full"
                                      placeholder="预期结果..."
                                    />
                                  </div>
                                  {formSteps.length > 1 && (
                                    <button
                                      onClick={() => removeStep(i)}
                                      className="text-slate-300 hover:text-red-400 p-0.5"
                                    >
                                      <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                                        <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                                      </svg>
                                    </button>
                                  )}
                                </div>
                              ))}
                            </div>
                          </div>

                          <div className="flex gap-2 pt-1">
                            <button
                              onClick={saveTestCase}
                              disabled={!formTitle.trim()}
                              className="flex-1 py-1.5 bg-slate-900 text-white text-[10px] font-medium rounded-lg hover:bg-slate-800 disabled:opacity-50 transition-colors"
                            >
                              {editingTestCase ? '保存修改' : '创建用例'}
                            </button>
                            <button
                              onClick={() => { setShowNewForm(false); setEditingTestCase(null); }}
                              className="flex-1 py-1.5 bg-white border border-slate-200 text-slate-500 text-[10px] font-medium rounded-lg hover:bg-slate-50"
                            >
                              取消
                            </button>
                          </div>
                        </div>
                      </div>
                    )}
                  </>
                )}
              </div>
            )}

            {/* === AI Chat Tab === */}
            {activeCenterTab === 'ai_chat' && (
              <div className="h-full flex flex-col">
                <div className="flex-1 overflow-y-auto p-3 space-y-3">
                  {chatMessages.map((msg) => (
                    <div key={msg.id} className={`${msg.role === 'user' ? 'flex justify-end' : 'flex gap-1.5'}`}>
                      {msg.role !== 'user' && (
                        <div className={`w-5 h-5 rounded-full flex items-center justify-center flex-shrink-0 ${
                          msg.role === 'agent' ? 'bg-slate-800 text-white' : 'bg-slate-200 text-slate-500'
                        }`}>
                          <span className="text-[9px] font-medium">{msg.role === 'agent' ? 'A' : 'S'}</span>
                        </div>
                      )}
                      <div className={`max-w-[90%] ${msg.role === 'agent' || msg.role === 'system' ? '' : ''}`}>
                        {msg.role === 'user' && (
                          <div className="bg-slate-900 text-white text-[10px] px-3 py-2 rounded-2xl rounded-br-md">
                            {msg.content}
                          </div>
                        )}

                        {msg.role === 'agent' && (
                          <div className="bg-slate-50 border border-slate-100 text-[10px] px-3 py-2 rounded-2xl rounded-bl-md">
                            {msg.thinking && (
                              <div className="mb-1.5 pb-1.5 border-b border-slate-200">
                                <div className="text-[9px] text-slate-400 font-medium mb-0.5">思考过程</div>
                                {msg.thinking.map((t, i) => (
                                  <div key={i} className="text-[9px] text-slate-400 flex items-center gap-1">
                                    <span className="w-1 h-1 rounded-full bg-slate-300" />
                                    {t}
                                  </div>
                                ))}
                              </div>
                            )}
                            <p className="whitespace-pre-wrap">{msg.content}</p>

                            {msg.suggestions && (
                              <div className="mt-2 space-y-1.5">
                                {msg.suggestions.map((sugg, i) => (
                                  <div
                                    key={i}
                                    className={`p-2 rounded-lg border text-[9px] ${
                                      sugg.accepted ? 'bg-emerald-50 border-emerald-200' :
                                      sugg.rejected ? 'bg-red-50 border-red-100 opacity-50' :
                                      'bg-white border-slate-200'
                                    }`}
                                  >
                                    <div className="flex items-center gap-1.5 mb-1">
                                      <TypeBadge type={sugg.type} />
                                      <PriorityBadge priority={sugg.priority} />
                                      <span className="font-medium text-slate-700">{sugg.title}</span>
                                    </div>
                                    <div className="space-y-0.5 text-slate-500">
                                      {sugg.steps.map((s, j) => (
                                        <div key={j} className="flex gap-1">
                                          <span className="text-slate-300">{s.order}.</span>
                                          <span>{s.action} → {s.expectedResult}</span>
                                        </div>
                                      ))}
                                    </div>
                                    {!sugg.accepted && !sugg.rejected && (
                                      <div className="flex gap-1 mt-1.5">
                                        <button
                                          onClick={() => acceptSuggestion(msg.id, i)}
                                          className="text-[8px] px-1.5 py-0.5 bg-emerald-600 text-white rounded hover:bg-emerald-700"
                                        >
                                          接受
                                        </button>
                                        <button
                                          onClick={() => rejectSuggestion(msg.id, i)}
                                          className="text-[8px] px-1.5 py-0.5 bg-white border border-slate-200 text-slate-500 rounded hover:bg-slate-50"
                                        >
                                          拒绝
                                        </button>
                                      </div>
                                    )}
                                    {sugg.accepted && <p className="text-[8px] text-emerald-600 mt-1">已添加到用例列表</p>}
                                    {sugg.rejected && <p className="text-[8px] text-red-400 mt-1">已拒绝</p>}
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>
                        )}

                        {msg.role === 'system' && (
                          <div className="text-[9px] text-slate-400 px-2 py-1 bg-slate-50 rounded-lg italic">
                            {msg.content}
                          </div>
                        )}

                        <p className="text-[8px] text-slate-300 mt-0.5 px-1">{msg.timestamp}</p>
                      </div>
                    </div>
                  ))}

                  {aiGenerating && (
                    <div className="flex gap-1.5">
                      <div className="w-5 h-5 rounded-full bg-slate-800 text-white flex items-center justify-center flex-shrink-0">
                        <span className="text-[9px] font-medium">A</span>
                      </div>
                      <div className="bg-slate-50 border border-slate-100 rounded-2xl rounded-bl-md px-3 py-2">
                        <div className="flex gap-1">
                          <span className="w-1.5 h-1.5 rounded-full bg-slate-300 animate-bounce" style={{ animationDelay: '0ms' }} />
                          <span className="w-1.5 h-1.5 rounded-full bg-slate-300 animate-bounce" style={{ animationDelay: '150ms' }} />
                          <span className="w-1.5 h-1.5 rounded-full bg-slate-300 animate-bounce" style={{ animationDelay: '300ms' }} />
                        </div>
                      </div>
                    </div>
                  )}

                  <div ref={(el) => el?.scrollIntoView({ behavior: 'smooth' })} />
                </div>

                <div className="border-t border-slate-100 p-2 flex-shrink-0">
                  <div className="flex gap-1 mb-1.5">
                    {['生成接口测试用例', '生成UI测试用例', '分析覆盖率缺口', '补充边界条件'].map((cmd) => (
                      <button
                        key={cmd}
                        onClick={() => setChatInput(cmd)}
                        className="text-[9px] px-2 py-0.5 bg-slate-50 border border-slate-100 rounded-lg text-slate-500 hover:bg-slate-100 transition-colors whitespace-nowrap"
                      >
                        {cmd}
                      </button>
                    ))}
                  </div>
                  <div className="flex gap-1.5">
                    <input
                      value={chatInput}
                      onChange={(e) => setChatInput(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && sendChat()}
                      placeholder="输入您的测试需求..."
                      className="flex-1 text-[10px] border border-slate-200 rounded-lg px-3 py-1.5 outline-none focus:border-slate-400"
                    />
                    <button
                      onClick={sendChat}
                      disabled={aiGenerating}
                      className="p-1.5 bg-slate-900 text-white rounded-lg hover:bg-slate-800 disabled:opacity-50 transition-colors"
                    >
                      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
                      </svg>
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Right Resize Handle */}
        <div
          className="w-1 cursor-col-resize hover:bg-slate-300 transition-colors flex-shrink-0 bg-transparent z-10"
          onMouseDown={() => { isDragging.current = 'right'; }}
        />

        {/* ============================================================
            Right Pane: Execution Panel (28%)
            ============================================================ */}
        <div className="flex flex-col bg-white border-l border-slate-200" style={{ width: `${rightWidth}%` }}>
          <div className="flex items-center justify-between px-3 py-2 border-b border-slate-100 flex-shrink-0">
            <h2 className="text-xs font-semibold text-slate-800">测试执行</h2>
            <div className="flex items-center gap-1">
              <button
                onClick={() => setActiveExecTab('api_mock')}
                className={`text-[10px] px-2 py-1 rounded-lg ${activeExecTab === 'api_mock' ? 'bg-slate-900 text-white' : 'text-slate-500 hover:bg-slate-100'}`}
              >
                API Mock
              </button>
              <button
                onClick={() => setActiveExecTab('ui_auto')}
                className={`text-[10px] px-2 py-1 rounded-lg ${activeExecTab === 'ui_auto' ? 'bg-slate-900 text-white' : 'text-slate-500 hover:bg-slate-100'}`}
              >
                UI 自动化
              </button>
            </div>
          </div>

          <div className="flex-1 overflow-y-auto">
            {/* === API Mock Tab === */}
            {activeExecTab === 'api_mock' && (
              <div className="p-3 space-y-3">
                {/* Endpoint Selector */}
                <div>
                  <label className="text-[9px] text-slate-400 block mb-1">接口端点</label>
                  <select
                    value={selectedMockConfig?.id || ''}
                    onChange={(e) => {
                      const cfg = apiMockConfigs.find((c) => c.id === e.target.value);
                      if (cfg) {
                        setSelectedMockConfig(cfg);
                        setMockRequestBody(cfg.requestBody);
                        setMockResult(null);
                      }
                    }}
                    className="text-[10px] border border-slate-200 rounded-lg px-2 py-1.5 outline-none w-full font-mono"
                  >
                    <option value="" disabled>-- 暂无 Mock 配置 --</option>
                    {apiMockConfigs.filter(c => c.requirementId === reqId).map((cfg) => (
                      <option key={cfg.id} value={cfg.id}>{cfg.endpoint}</option>
                    ))}
                  </select>
                </div>

                {/* Method + Latency */}
                {selectedMockConfig && (
                  <div className="flex gap-2">
                    <div className="flex-1">
                      <label className="text-[9px] text-slate-400 block mb-1">Method</label>
                      <span className={`text-[10px] px-2 py-1 rounded font-mono font-medium ${
                        selectedMockConfig.method === 'GET' ? 'bg-emerald-50 text-emerald-600' :
                        selectedMockConfig.method === 'POST' ? 'bg-blue-50 text-blue-600' :
                        selectedMockConfig.method === 'PUT' ? 'bg-amber-50 text-amber-600' :
                        'bg-red-50 text-red-600'
                      }`}>
                        {selectedMockConfig.method}
                      </span>
                    </div>
                    <div className="flex-1">
                      <label className="text-[9px] text-slate-400 block mb-1">模拟延迟</label>
                      <span className="text-[10px] text-slate-500">{selectedMockConfig.mockLatencyMs}ms</span>
                    </div>
                  </div>
                )}

                {/* Request Body */}
                <div>
                  <label className="text-[9px] text-slate-400 block mb-1">请求体 (JSON)</label>
                  <textarea
                    value={mockRequestBody}
                    onChange={(e) => setMockRequestBody(e.target.value)}
                    rows={5}
                    className="text-[10px] border border-slate-200 rounded-lg p-2 outline-none focus:border-slate-400 w-full font-mono resize-none"
                  />
                </div>

                {/* Send Button */}
                <button
                  onClick={sendMockRequest}
                  disabled={mockLoading || !selectedMockConfig}
                  className="w-full py-2 bg-blue-600 text-white text-[10px] font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors flex items-center justify-center gap-1.5"
                >
                  {mockLoading ? (
                    <>
                      <svg className="w-3 h-3 animate-spin" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                      </svg>
                      发送中...
                    </>
                  ) : (
                    <>
                      <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
                      </svg>
                      发送请求
                    </>
                  )}
                </button>

                {/* Response */}
                {mockResult && (
                  <div className={`rounded-lg border p-2.5 ${
                    mockResult.passed ? 'border-emerald-200 bg-emerald-50/30' : 'border-red-200 bg-red-50/30'
                  }`}>
                    <div className="flex items-center justify-between mb-1.5">
                      <span className={`text-[10px] font-semibold ${mockResult.passed ? 'text-emerald-600' : 'text-red-600'}`}>
                        {mockResult.passed ? 'PASS' : 'FAIL'}
                      </span>
                      <span className="text-[9px] text-slate-400">{mockResult.latencyMs}ms</span>
                    </div>
                    <div className="flex items-center gap-2 mb-1.5 text-[9px]">
                      <span className={`px-1.5 py-0.5 rounded font-mono ${
                        mockResult.responseStatus < 300 ? 'bg-emerald-100 text-emerald-600' : 'bg-red-100 text-red-600'
                      }`}>
                        {mockResult.responseStatus}
                      </span>
                    </div>
                    <div>
                      <label className="text-[8px] text-slate-400 block mb-0.5">响应体</label>
                      <pre className="text-[9px] text-slate-600 bg-white rounded p-1.5 border border-slate-100 overflow-x-auto font-mono leading-relaxed max-h-32 overflow-y-auto">
                        {mockResult.responseBody}
                      </pre>
                    </div>

                    {/* Assertion Results */}
                    <div className="mt-1.5 pt-1.5 border-t border-slate-200">
                      <label className="text-[8px] text-slate-400 block mb-0.5">断言结果</label>
                      <div className="space-y-0.5">
                        {mockResult.assertionResults.map((a, i) => (
                          <div key={i} className="flex items-center gap-1 text-[9px]">
                            <span className={a.passed ? 'text-emerald-500' : 'text-red-500'}>
                              {a.passed ? '✓' : '✗'}
                            </span>
                            <span className="text-slate-500">{a.field}:</span>
                            <span className="text-slate-400 font-mono">期望 {a.expected}</span>
                            <span className="text-slate-400">→</span>
                            <span className={`font-mono ${a.passed ? 'text-slate-600' : 'text-red-500'}`}>{a.actual}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* === UI Automation Tab === */}
            {activeExecTab === 'ui_auto' && (
              <div className="p-3 space-y-3">
                {/* Script Preview Toggle */}
                <div className="flex items-center justify-between">
                  <span className="text-[10px] text-slate-500">Playwright 脚本</span>
                  <button
                    onClick={() => setShowScriptPreview(!showScriptPreview)}
                    className="text-[9px] text-blue-600 hover:text-blue-700"
                  >
                    {showScriptPreview ? '收起脚本' : '查看脚本'}
                  </button>
                </div>

                {showScriptPreview && (
                  <div className="bg-slate-900 text-emerald-400 rounded-lg p-2.5 text-[9px] font-mono leading-relaxed max-h-40 overflow-y-auto">
                    <pre>{`import { test, expect } from '@playwright/test';

test('${selectedTestCase?.title || 'UI Test'}', async ({ page }) => {
  await page.goto('https://app.example.com/orders');
  await page.waitForLoadState('networkidle');

  const exportBtn = page.locator('button:has-text("批量导出")');
  await expect(exportBtn).toBeVisible();

  await exportBtn.click();
  await page.waitForSelector('.export-dialog');

  const dialog = page.locator('.export-dialog');
  await expect(dialog).toBeVisible();
  await expect(dialog.locator('.date-range-picker')).toBeVisible();
});`}</pre>
                  </div>
                )}

                {/* Execute Button */}
                <button
                  onClick={runUITest}
                  disabled={uiRunning}
                  className="w-full py-2 bg-purple-600 text-white text-[10px] font-medium rounded-lg hover:bg-purple-700 disabled:opacity-50 transition-colors flex items-center justify-center gap-1.5"
                >
                  {uiRunning ? (
                    <>
                      <svg className="w-3 h-3 animate-spin" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                      </svg>
                      执行中 ({uiExecution?.completedSteps || 0}/{uiExecution?.totalSteps || 0})
                    </>
                  ) : (
                    <>
                      <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                        <path strokeLinecap="round" strokeLinejoin="round" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                      </svg>
                      执行 UI 测试
                    </>
                  )}
                </button>

                {/* Screencast Browser Frame */}
                {uiExecution && (
                  <div className="border border-slate-200 rounded-lg overflow-hidden">
                    {/* Browser bar */}
                    <div className="bg-slate-100 px-2 py-1.5 flex items-center gap-1 border-b border-slate-200">
                      <span className="w-1.5 h-1.5 rounded-full bg-red-400" />
                      <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                      <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                      <span className="ml-1 text-[8px] text-slate-400 bg-white rounded px-1.5 py-0.5 flex-1 truncate">
                        app.example.com/orders
                      </span>
                      {uiRunning && (
                        <span className="text-[8px] text-purple-500 animate-pulse">录制中...</span>
                      )}
                    </div>

                    {/* Screenshot Area */}
                    <div className="bg-slate-50 relative" style={{ minHeight: '200px' }}>
                      {uiExecution.status === 'idle' ? (
                        <div className="flex items-center justify-center h-48 text-[10px] text-slate-400">
                          点击"执行 UI 测试"开始
                        </div>
                      ) : (
                        <div className="relative">
                          {(() => {
                            const activeStep = uiExecution.steps.find(s => s.status === 'active');
                            const displayStep = activeStep || uiExecution.steps[uiCurrentStepIdx];
                            const screenshot = displayStep?.screenshotB64;

                            return (
                              <>
                                {screenshot ? (
                                  <img src={screenshot} alt="Browser screenshot" className="w-full" />
                                ) : (
                                  <div className="h-48 flex items-center justify-center text-[10px] text-slate-400 bg-slate-100">
                                    <svg className="w-6 h-6 mr-1.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1}>
                                      <path strokeLinecap="round" strokeLinejoin="round" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
                                    </svg>
                                    等待截图...
                                  </div>
                                )}

                                {/* Red dot click overlay */}
                                {displayStep?.coordinates && (displayStep.status === 'active' || displayStep.actionType === 'click') && (
                                  <div
                                    className="absolute pointer-events-none"
                                    style={{
                                      left: `${(displayStep.coordinates.x / 800) * 100}%`,
                                      top: `${(displayStep.coordinates.y / 500) * 100}%`,
                                      transform: 'translate(-50%, -50%)',
                                    }}
                                  >
                                    <div className="relative">
                                      <span className="absolute w-3 h-3 bg-red-500 rounded-full animate-ping opacity-75" />
                                      <span className="relative w-3 h-3 bg-red-500 rounded-full block ring-2 ring-red-200" />
                                    </div>
                                  </div>
                                )}
                              </>
                            );
                          })()}
                        </div>
                      )}

                      {/* Action overlay */}
                      {uiExecution.steps.find(s => s.status === 'active') && (
                        <div className="absolute bottom-0 left-0 right-0 bg-black/60 text-white text-[9px] px-2 py-1.5 flex items-center gap-2">
                          <span className={`px-1 py-0.5 rounded text-[8px] font-medium ${
                            (() => {
                              const s = uiExecution.steps.find(st => st.status === 'active');
                              if (!s) return 'bg-slate-500';
                              const colors: Record<string, string> = {
                                navigate: 'bg-emerald-500', click: 'bg-amber-500', fill: 'bg-blue-500',
                                assert: 'bg-purple-500', screenshot: 'bg-slate-500', wait: 'bg-slate-500',
                              };
                              return colors[s.actionType] || 'bg-slate-500';
                            })()
                          }`}>
                            {(() => {
                              const s = uiExecution.steps.find(st => st.status === 'active');
                              const labels: Record<string, string> = { navigate: '导航', click: '点击', fill: '输入', assert: '断言', screenshot: '截图', wait: '等待' };
                              return s ? labels[s.actionType] || s.actionType : '';
                            })()}
                          </span>
                          <span className="truncate">
                            {uiExecution.steps.find(s => s.status === 'active')?.description}
                          </span>
                        </div>
                      )}
                    </div>
                  </div>
                )}

                {/* Step Timeline */}
                {uiExecution && uiExecution.steps.length > 0 && (
                  <div className="space-y-1">
                    <h4 className="text-[9px] font-medium text-slate-400 uppercase tracking-wider">步骤时间轴</h4>
                    {uiExecution.steps.map((step, i) => (
                      <div
                        key={i}
                        className={`flex items-center gap-2 text-[10px] py-1.5 px-2 rounded-lg border ${
                          step.status === 'active'
                            ? 'border-blue-200 bg-blue-50'
                            : step.status === 'passed'
                            ? 'border-emerald-100 bg-white'
                            : step.status === 'failed'
                            ? 'border-red-100 bg-red-50'
                            : 'border-transparent bg-white'
                        }`}
                      >
                        {/* Status Icon */}
                        <div className="flex-shrink-0">
                          {step.status === 'pending' && (
                            <span className="w-4 h-4 rounded-full border border-slate-200 flex items-center justify-center text-[8px] text-slate-400">{step.order}</span>
                          )}
                          {step.status === 'active' && (
                            <span className="w-4 h-4 rounded-full bg-blue-500 flex items-center justify-center">
                              <span className="w-1.5 h-1.5 rounded-full bg-white animate-pulse" />
                            </span>
                          )}
                          {step.status === 'passed' && (
                            <span className="w-4 h-4 rounded-full bg-emerald-500 flex items-center justify-center">
                              <svg className="w-2.5 h-2.5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                              </svg>
                            </span>
                          )}
                          {step.status === 'failed' && (
                            <span className="w-4 h-4 rounded-full bg-red-500 flex items-center justify-center">
                              <svg className="w-2.5 h-2.5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                              </svg>
                            </span>
                          )}
                        </div>

                        <div className="flex-1 min-w-0">
                          <p className={`truncate ${step.status === 'pending' ? 'text-slate-400' : 'text-slate-700'}`}>
                            {step.description}
                          </p>
                          {step.errorMessage && (
                            <p className="text-[8px] text-red-500 truncate">{step.errorMessage}</p>
                          )}
                        </div>

                        {step.durationMs && step.status !== 'pending' && (
                          <span className="text-[8px] text-slate-400 flex-shrink-0">{(step.durationMs / 1000).toFixed(1)}s</span>
                        )}
                      </div>
                    ))}
                  </div>
                )}

                {/* Execution Complete Summary */}
                {uiExecution?.status === 'completed' && (
                  <div className={`rounded-lg border p-2.5 ${
                    uiExecution.steps.every(s => s.status === 'passed')
                      ? 'border-emerald-200 bg-emerald-50/30'
                      : 'border-amber-200 bg-amber-50/30'
                  }`}>
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-lg">
                        {uiExecution.steps.every(s => s.status === 'passed') ? '✅' : '⚠️'}
                      </span>
                      <div>
                        <p className="text-[10px] font-semibold text-slate-800">测试执行完成</p>
                        <p className="text-[9px] text-slate-500">
                          {uiExecution.totalSteps} 个步骤 .
                          通过 {uiExecution.steps.filter(s => s.status === 'passed').length} .
                          失败 {uiExecution.steps.filter(s => s.status === 'failed').length}
                        </p>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ============================================================
          Readiness Approval Modal
          ============================================================ */}
      {showReadinessModal && (
        <>
          <div className="fixed inset-0 bg-black/30 z-50" onClick={() => setShowReadinessModal(false)} />
          <div className="fixed inset-0 flex items-center justify-center z-50 pointer-events-none">
            <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md pointer-events-auto">
              <div className="px-5 py-4 border-b border-slate-200">
                <h2 className="text-sm font-semibold text-slate-900">测试就绪审批</h2>
                <p className="text-[10px] text-slate-500 mt-0.5">{reqId}: {requirement.title}</p>
              </div>

              <div className="p-5 space-y-3">
                <div className="space-y-2">
                  {[
                    { key: 'acceptanceCriteriaMet' as const, label: '验收标准是否清晰可测？' },
                    { key: 'interfaceContractReady' as const, label: '接口契约是否已完整定义？' },
                    { key: 'prototypeReady' as const, label: '原型/UI 是否已就绪？' },
                  ].map((item) => (
                    <label key={item.key} className="flex items-center gap-2 text-xs text-slate-700 cursor-pointer">
                      <input
                        type="checkbox"
                        defaultChecked={true}
                        className="w-3.5 h-3.5 rounded border-slate-300 text-emerald-600 focus:ring-emerald-500"
                      />
                      {item.label}
                    </label>
                  ))}
                </div>

                <div>
                  <label className="text-[10px] text-slate-400 block mb-1">审批意见</label>
                  <textarea
                    value={readinessComment}
                    onChange={(e) => setReadinessComment(e.target.value)}
                    placeholder="输入审批意见（可选）..."
                    className="w-full text-xs border border-slate-200 rounded-xl p-3 outline-none focus:border-slate-400 resize-none h-20"
                  />
                </div>

                <div className="flex gap-2 pt-1">
                  <button
                    onClick={() => {
                      setReadinessStatus('approved');
                      setShowReadinessModal(false);
                      showToast('测试就绪审批已通过，可以开始编写和执行测试用例');
                    }}
                    className="flex-1 py-2 bg-emerald-600 text-white text-xs font-medium rounded-xl hover:bg-emerald-700 transition-colors"
                  >
                    通过审批
                  </button>
                  <button
                    onClick={() => {
                      setReadinessStatus('rejected');
                      setShowReadinessModal(false);
                      showToast('已打回测试就绪审批');
                    }}
                    className="flex-1 py-2 bg-white border border-red-200 text-red-600 text-xs font-medium rounded-xl hover:bg-red-50 transition-colors"
                  >
                    打回修改
                  </button>
                </div>
              </div>
            </div>
          </div>
        </>
      )}

      {/* ============================================================
          Toast Notification
          ============================================================ */}
      {toast && (
        <div className="fixed bottom-16 left-1/2 -translate-x-1/2 z-[60] bg-slate-900 text-white text-xs px-4 py-2 rounded-xl shadow-lg animate-bounce">
          {toast}
        </div>
      )}
    </div>
  );
}

'use client';

import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { api } from '@/lib/api';
import type {
  Gate0Approval,
  ApprovalContext,
  RequirementDraft,
  FeasibilityAssessment,
  ConfirmationChecklistItem,
  ConflictItem,
  RejectReason,
} from '@/lib/types';

const REJECT_CATEGORIES: { value: string; label: string }[] = [
  { value: 'requirement_unclear', label: '需求不清晰' },
  { value: 'requirement_incomplete', label: '需求不完整' },
  { value: 'acceptance_criteria_insufficient', label: '验收标准不足' },
  { value: 'business_not_feasible', label: '业务不可行' },
  { value: 'risk_unacceptable', label: '风险过高' },
  { value: 'conflict_unresolved', label: '存在冲突' },
  { value: 'other', label: '其他' },
];

const RISK_COLORS: Record<string, string> = {
  low: 'bg-emerald-100 text-emerald-800',
  medium: 'bg-amber-100 text-amber-800',
  high: 'bg-red-100 text-red-800',
};

const PRIORITY_COLORS: Record<string, string> = {
  high: 'bg-red-50 text-red-700 border-red-200',
  medium: 'bg-amber-50 text-amber-700 border-amber-200',
  low: 'bg-slate-50 text-slate-600 border-slate-200',
};

const SEVERITY_COLORS: Record<string, string> = {
  high: 'text-red-600',
  medium: 'text-amber-600',
  low: 'text-slate-500',
};

const CONFLICT_TYPE_LABELS: Record<string, string> = {
  field_naming: '字段命名',
  business_flow: '业务流程',
  data_model: '数据模型',
  service_boundary: '服务边界',
};

const CHECKLIST_CATEGORY_LABELS: Record<string, string> = {
  requirement_clarity: '需求清晰度',
  technical_risk: '技术风险',
  dependency: '依赖关系',
};

export default function ApprovalDetailPage() {
  const params = useParams();
  const router = useRouter();
  const id = params.id as string;

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [context, setContext] = useState<ApprovalContext | null>(null);
  const [approval, setApproval] = useState<Gate0Approval | null>(null);
  const [decision, setDecision] = useState<'pass' | 'reject' | null>(null);
  const [selectedReasons, setSelectedReasons] = useState<string[]>([]);
  const [revisionGuidance, setRevisionGuidance] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [wireframeOpen, setWireframeOpen] = useState(false);

  useEffect(() => {
    loadContext();
  }, [id]);

  async function loadContext() {
    setLoading(true);
    setError(null);
    try {
      const [ctx, approvalRecord] = await Promise.all([
        api.getApprovalContext(id),
        api.getApproval(id),
      ]);
      setContext(ctx);
      setApproval(approvalRecord);
    } catch (e: any) {
      setError(e.message || 'Failed to load approval context');
    } finally {
      setLoading(false);
    }
  }

  function toggleReason(category: string) {
    setSelectedReasons((prev) =>
      prev.includes(category)
        ? prev.filter((r) => r !== category)
        : [...prev, category]
    );
  }

  async function handleSubmit() {
    if (!decision) return;
    if (decision === 'reject') {
      if (selectedReasons.length === 0) {
        setSubmitError('请至少选择一个拒绝原因');
        return;
      }
      if (!revisionGuidance.trim()) {
        setSubmitError('请输入修订指引');
        return;
      }
    }

    setSubmitting(true);
    setSubmitError(null);
    try {
      const body: any = { decision };
      if (decision === 'reject') {
        body.reject_reasons = selectedReasons.map((cat) => ({
          category: cat,
          description:
            REJECT_CATEGORIES.find((c) => c.value === cat)?.label || cat,
        }));
        body.revision_guidance = revisionGuidance.trim();
      }
      await api.decideApproval(id, body);
      // Reload to show result
      loadContext();
      setDecision(null);
      setSelectedReasons([]);
      setRevisionGuidance('');
    } catch (e: any) {
      setSubmitError(e.message || '提交失败');
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-slate-50">
        <div className="text-slate-500 animate-pulse">加载审批上下文...</div>
      </div>
    );
  }

  if (error || !context) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen bg-slate-50 gap-4">
        <div className="text-red-500">{error || '未找到审批记录'}</div>
        <button
          onClick={() => router.push('/approvals')}
          className="text-blue-600 hover:underline text-sm"
        >
          返回审批列表
        </button>
      </div>
    );
  }

  const isDecided = approval?.status === 'decided';

  const canDecide = approval?.status === 'pending';

  return (
    <div className="min-h-screen bg-slate-50 p-6">
      <div className="max-w-5xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <button
              onClick={() => router.push('/approvals')}
              className="text-sm text-blue-600 hover:underline mb-2 inline-block"
            >
              ← 返回审批列表
            </button>
            <h1 className="text-2xl font-bold text-slate-900">
              Gate0 需求审批
            </h1>
            <div className="flex items-center gap-3 mt-1 text-sm text-slate-500">
              <span>Cycle: {context.cycle}</span>
              {approval?.status && (
                <span
                  className={`px-2 py-0.5 rounded text-xs font-medium ${
                    approval.status === 'pending'
                      ? 'bg-amber-100 text-amber-700'
                      : approval.status === 'decided'
                      ? approval.decision === 'pass'
                        ? 'bg-emerald-100 text-emerald-700'
                        : 'bg-red-100 text-red-700'
                      : 'bg-slate-100 text-slate-600'
                  }`}
                >
                  {approval.status === 'pending'
                    ? '待审批'
                    : approval.decision === 'pass'
                    ? '已通过'
                    : '已拒绝'}
                </span>
              )}
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Main content — A1 + A2 */}
          <div className="lg:col-span-2 space-y-6">
            {/* ── A1 Section: Requirement Draft ── */}
            <section className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-lg font-semibold text-slate-800 flex items-center gap-2">
                  <span className="text-blue-500">📋</span> 需求草案（A1 产出）
                </h2>
                {context.a1_output.confidence_score != null && (
                  <ConfidenceBadge score={context.a1_output.confidence_score} />
                )}
              </div>
              <DraftSection draft={context.a1_output.requirement_draft} />
              {context.a1_output.wireframe_url && (
                <div className="mt-4 pt-4 border-t border-slate-100">
                  <button
                    onClick={() => setWireframeOpen(!wireframeOpen)}
                    className="text-sm text-blue-600 hover:underline"
                  >
                    {wireframeOpen ? '收起线框图' : '查看线框图'}
                  </button>
                  {wireframeOpen && (
                    <div className="mt-2 p-3 bg-slate-50 rounded text-sm text-slate-500">
                      线框图链接: {context.a1_output.wireframe_url}
                    </div>
                  )}
                </div>
              )}
            </section>

            {/* ── A2 Section: Knowledge Analysis ── */}
            <section className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-lg font-semibold text-slate-800 flex items-center gap-2">
                  <span className="text-purple-500">🔍</span> 知识分析（A2 产出）
                </h2>
                {context.a2_output.quality_score != null && (
                  <QualityBadge score={context.a2_output.quality_score} />
                )}
              </div>

              {context.a2_output.a2_missing && (
                <div className="mb-4 p-3 bg-amber-50 border border-amber-200 rounded-lg text-sm text-amber-800 flex items-start gap-2">
                  <span>⚠️</span>
                  <span>A2 知识分析不可用（Agent 超时或未执行）。请基于 A1 草案和自身经验做出判断。</span>
                </div>
              )}

              {context.a2_output.feasibility_assessment && (
                <FeasibilitySection
                  fa={context.a2_output.feasibility_assessment}
                />
              )}

              {context.a2_output.conflicts.length > 0 && (
                <ConflictsSection conflicts={context.a2_output.conflicts} />
              )}

              {context.a2_output.confirmation_checklist.length > 0 && (
                <ChecklistSection
                  items={context.a2_output.confirmation_checklist}
                />
              )}
            </section>
          </div>

          {/* ── Sidebar: Decision Form ── */}
          <div className="lg:col-span-1">
            <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6 sticky top-6">
              <h3 className="text-lg font-semibold text-slate-800 mb-4">
                审批决策
              </h3>

              {approval?.status === 'decided' ? (
                <DecisionResult approval={approval} />
              ) : (
                <>
                  {/* Decision radio */}
                  <div className="space-y-3 mb-4">
                    <label
                      className={`flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition ${
                        decision === 'pass'
                          ? 'border-emerald-400 bg-emerald-50'
                          : 'border-slate-200 hover:border-slate-300'
                      }`}
                    >
                      <input
                        type="radio"
                        name="decision"
                        value="pass"
                        checked={decision === 'pass'}
                        onChange={() => setDecision('pass')}
                        className="w-4 h-4 text-emerald-600"
                      />
                      <span className="font-medium text-slate-700">
                        ✅ 通过
                      </span>
                    </label>

                    <label
                      className={`flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition ${
                        decision === 'reject'
                          ? 'border-red-400 bg-red-50'
                          : 'border-slate-200 hover:border-slate-300'
                      }`}
                    >
                      <input
                        type="radio"
                        name="decision"
                        value="reject"
                        checked={decision === 'reject'}
                        onChange={() => setDecision('reject')}
                        className="w-4 h-4 text-red-600"
                      />
                      <span className="font-medium text-slate-700">
                        ❌ 拒绝
                      </span>
                    </label>
                  </div>

                  {/* Reject reasons */}
                  {decision === 'reject' && (
                    <div className="mb-4">
                      <p className="text-sm font-medium text-slate-600 mb-2">
                        拒绝原因（可多选）
                      </p>
                      <div className="space-y-1.5">
                        {REJECT_CATEGORIES.map((cat) => (
                          <label
                            key={cat.value}
                            className="flex items-center gap-2 text-sm cursor-pointer"
                          >
                            <input
                              type="checkbox"
                              checked={selectedReasons.includes(cat.value)}
                              onChange={() => toggleReason(cat.value)}
                              className="w-3.5 h-3.5 text-red-600 rounded"
                            />
                            {cat.label}
                          </label>
                        ))}
                      </div>

                      <div className="mt-3">
                        <label className="text-sm font-medium text-slate-600 block mb-1">
                          修订指引 <span className="text-red-500">*</span>
                        </label>
                        <textarea
                          value={revisionGuidance}
                          onChange={(e) => setRevisionGuidance(e.target.value)}
                          placeholder="请提供具体的修订建议..."
                          rows={4}
                          className="w-full border border-slate-300 rounded-lg p-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-none"
                        />
                      </div>
                    </div>
                  )}

                  {/* Submit error */}
                  {submitError && (
                    <div className="mb-3 p-2 bg-red-50 border border-red-200 rounded text-sm text-red-600">
                      {submitError}
                    </div>
                  )}

                  {/* Submit button */}
                  <button
                    onClick={handleSubmit}
                    disabled={!decision || submitting}
                    className="w-full py-2.5 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition"
                  >
                    {submitting ? '提交中...' : '提交审批'}
                  </button>
                </>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Sub-components ─────────────────────────────────────────────────────────

function ConfidenceBadge({ score }: { score: number }) {
  const color =
    score >= 0.8
      ? 'bg-emerald-100 text-emerald-800'
      : score >= 0.6
      ? 'bg-amber-100 text-amber-800'
      : 'bg-red-100 text-red-800';
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${color}`}>
      置信度: {(score * 100).toFixed(0)}%
    </span>
  );
}

function QualityBadge({ score }: { score: number }) {
  const color =
    score >= 0.6
      ? 'bg-emerald-100 text-emerald-800'
      : score >= 0.3
      ? 'bg-amber-100 text-amber-800'
      : 'bg-red-100 text-red-800';
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${color}`}>
      质量评分: {(score * 100).toFixed(0)}%
    </span>
  );
}

function DraftSection({ draft }: { draft: RequirementDraft | null }) {
  if (!draft) {
    return <div className="text-sm text-slate-400">暂无需求草案</div>;
  }

  return (
    <div className="space-y-4 text-sm">
      <div>
        <span className="font-medium text-slate-500">标题：</span>
        <span className="text-slate-800">{draft.title || '-'}</span>
      </div>
      <div>
        <span className="font-medium text-slate-500">描述：</span>
        <p className="text-slate-700 mt-1">{draft.description || '-'}</p>
      </div>
      <div>
        <span className="font-medium text-slate-500">领域：</span>
        <span className="text-slate-700">{draft.domain || 'general'}</span>
      </div>
      {draft.entities && draft.entities.length > 0 && (
        <div>
          <span className="font-medium text-slate-500">实体：</span>
          <div className="mt-1.5 flex flex-wrap gap-2">
            {draft.entities.map((ent, i) => (
              <div
                key={i}
                className="bg-blue-50 border border-blue-100 rounded-lg px-3 py-1.5"
              >
                <span className="font-medium text-blue-800">{ent.name}</span>
                {ent.attributes && ent.attributes.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-1">
                    {ent.attributes.map((attr, j) => (
                      <span
                        key={j}
                        className="bg-white text-blue-600 text-xs px-1.5 py-0.5 rounded border border-blue-100"
                      >
                        {attr}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
      {draft.use_cases && draft.use_cases.length > 0 && (
        <div>
          <span className="font-medium text-slate-500">用例：</span>
          <ul className="mt-1 list-disc list-inside text-slate-700 space-y-0.5">
            {draft.use_cases.map((uc, i) => (
              <li key={i}>{uc}</li>
            ))}
          </ul>
        </div>
      )}
      {draft.acceptance_criteria && draft.acceptance_criteria.length > 0 && (
        <div>
          <span className="font-medium text-slate-500">验收标准：</span>
          <ul className="mt-1 space-y-1">
            {draft.acceptance_criteria.map((ac, i) => (
              <li
                key={i}
                className="bg-emerald-50 text-emerald-800 px-3 py-1.5 rounded text-xs"
              >
                {ac}
              </li>
            ))}
          </ul>
        </div>
      )}
      {draft.constraints && draft.constraints.length > 0 && (
        <div>
          <span className="font-medium text-slate-500">约束：</span>
          <ul className="mt-1 list-disc list-inside text-slate-700 space-y-0.5">
            {draft.constraints.map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
        </div>
      )}
      {draft.risks && draft.risks.length > 0 && (
        <div>
          <span className="font-medium text-slate-500">风险：</span>
          <ul className="mt-1 space-y-1">
            {draft.risks.map((r, i) => (
              <li
                key={i}
                className="bg-amber-50 text-amber-800 px-3 py-1.5 rounded text-xs"
              >
                {r}
              </li>
            ))}
          </ul>
        </div>
      )}
      {draft.estimated_cost && (
        <div>
          <span className="font-medium text-slate-500">估算工时：</span>
          <span className="text-slate-700">{draft.estimated_cost}</span>
        </div>
      )}
    </div>
  );
}

function FeasibilitySection({ fa }: { fa: FeasibilityAssessment }) {
  return (
    <div className="mb-4">
      <h3 className="text-sm font-semibold text-slate-700 mb-3">可行性评估</h3>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {/* Technical */}
        <div className="border border-slate-200 rounded-lg p-3">
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-xs font-medium text-slate-500">
              技术可行性
            </span>
            <span
              className={`text-xs font-medium ${
                fa.technical.feasible ? 'text-emerald-600' : 'text-red-600'
              }`}
            >
              {fa.technical.feasible ? '可行' : '不可行'}
            </span>
          </div>
          <p className="text-xs text-slate-600">{fa.technical.assessment}</p>
          {fa.technical.concerns.length > 0 && (
            <ul className="mt-1.5 space-y-0.5">
              {fa.technical.concerns.map((c, i) => (
                <li key={i} className="text-xs text-amber-600 flex gap-1">
                  <span>•</span> {c}
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Business */}
        <div className="border border-slate-200 rounded-lg p-3">
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-xs font-medium text-slate-500">
              业务可行性
            </span>
            <span
              className={`text-xs font-medium ${
                fa.business.feasible ? 'text-emerald-600' : 'text-red-600'
              }`}
            >
              {fa.business.feasible ? '可行' : '不可行'}
            </span>
          </div>
          <p className="text-xs text-slate-600">{fa.business.assessment}</p>
          {fa.business.concerns.length > 0 && (
            <ul className="mt-1.5 space-y-0.5">
              {fa.business.concerns.map((c, i) => (
                <li key={i} className="text-xs text-amber-600 flex gap-1">
                  <span>•</span> {c}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      {/* Risk level + rationale */}
      <div className="mt-3 flex items-start gap-3">
        <span
          className={`px-2 py-0.5 rounded text-xs font-medium ${
            RISK_COLORS[fa.risk_level] || RISK_COLORS.low
          }`}
        >
          风险等级: {fa.risk_level === 'high' ? '高' : fa.risk_level === 'medium' ? '中' : '低'}
        </span>
        {fa.risk_rationale && (
          <p className="text-xs text-slate-500">{fa.risk_rationale}</p>
        )}
      </div>
    </div>
  );
}

function ConflictsSection({ conflicts }: { conflicts: ConflictItem[] }) {
  return (
    <div className="mb-4">
      <h3 className="text-sm font-semibold text-slate-700 mb-2">
        冲突检测 ({conflicts.length})
      </h3>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-slate-200 text-left text-slate-500">
              <th className="pb-2 font-medium">关联系统</th>
              <th className="pb-2 font-medium">类型</th>
              <th className="pb-2 font-medium">描述</th>
              <th className="pb-2 font-medium">严重度</th>
            </tr>
          </thead>
          <tbody>
            {conflicts.map((c) => (
              <tr key={c.id} className="border-b border-slate-100">
                <td className="py-2 text-slate-700">{c.related_system}</td>
                <td className="py-2">
                  <span className="bg-slate-100 text-slate-600 px-1.5 py-0.5 rounded text-xs">
                    {CONFLICT_TYPE_LABELS[c.type] || c.type}
                  </span>
                </td>
                <td className="py-2 text-slate-600 max-w-xs truncate">
                  {c.description}
                </td>
                <td
                  className={`py-2 font-medium ${SEVERITY_COLORS[c.severity] || ''}`}
                >
                  {c.severity === 'high' ? '高' : c.severity === 'medium' ? '中' : '低'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ChecklistSection({
  items,
}: {
  items: ConfirmationChecklistItem[];
}) {
  return (
    <div>
      <h3 className="text-sm font-semibold text-slate-700 mb-2">
        待确认清单 ({items.length})
      </h3>
      <div className="space-y-2">
        {items.map((item) => (
          <div
            key={item.id}
            className={`border rounded-lg p-3 ${PRIORITY_COLORS[item.priority] || PRIORITY_COLORS.medium}`}
          >
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-medium text-slate-500">
                {CHECKLIST_CATEGORY_LABELS[item.category] || item.category}
              </span>
              <span
                className={`text-xs font-medium ${
                  item.priority === 'high'
                    ? 'text-red-600'
                    : item.priority === 'medium'
                    ? 'text-amber-600'
                    : 'text-slate-500'
                }`}
              >
                {item.priority === 'high'
                  ? '高优先'
                  : item.priority === 'medium'
                  ? '中优先'
                  : '低优先'}
              </span>
            </div>
            <p className="text-sm text-slate-700">{item.item}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

function DecisionResult({ approval }: { approval: Gate0Approval }) {
  const isPass = approval.decision === 'pass';
  return (
    <div className="text-center py-4">
      <div
        className={`text-4xl mb-3 ${isPass ? 'text-emerald-500' : 'text-red-500'}`}
      >
        {isPass ? '✅' : '❌'}
      </div>
      <p className="text-lg font-semibold text-slate-800 mb-1">
        {isPass ? '已通过' : '已拒绝'}
      </p>
      {approval.reviewer_name && (
        <p className="text-sm text-slate-500 mb-1">
          审批人: {approval.reviewer_name}
        </p>
      )}
      {approval.reviewed_at && (
        <p className="text-xs text-slate-400">
          {new Date(approval.reviewed_at).toLocaleString('zh-CN')}
        </p>
      )}
      {!isPass && approval.reject_reasons && approval.reject_reasons.length > 0 && (
        <div className="mt-3 text-left">
          <p className="text-xs font-medium text-slate-500 mb-1">拒绝原因：</p>
          <ul className="space-y-1">
            {approval.reject_reasons.map((r, i) => (
              <li
                key={i}
                className="text-xs bg-red-50 text-red-700 px-2 py-1 rounded"
              >
                {REJECT_CATEGORIES.find((c) => c.value === r.category)?.label ||
                  r.category}
                {r.description ? `: ${r.description}` : ''}
              </li>
            ))}
          </ul>
          {approval.revision_guidance && (
            <div className="mt-2">
              <p className="text-xs font-medium text-slate-500 mb-0.5">
                修订指引：
              </p>
              <p className="text-xs text-slate-600 bg-amber-50 p-2 rounded">
                {approval.revision_guidance}
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

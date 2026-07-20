'use client';

/**
 * DraftPanel — renders the structured requirement draft in real-time.
 *
 * Displays all fields of requirement_draft: title, description, domain,
 * entities, use_cases, acceptance_criteria, constraints, risks, estimated_cost.
 * Fields are updated live via SSE draft_update events.
 */
import React from 'react';
import type { RequirementDraft } from '@/lib/types';

interface DraftPanelProps {
  draft: RequirementDraft | null;
  confidenceScore: number | null;
  isStreaming: boolean;
}

const DOMAIN_LABELS: Record<string, string> = {
  user_management: '用户管理',
  order_management: '订单管理',
  payment: '支付结算',
  product_catalog: '商品/内容管理',
  inventory: '库存/物流',
  auth: '认证/授权',
  notification: '消息/通知',
  reporting: '统计/报表',
  approval: '审批/工作流',
  general: '通用',
};

export default function DraftPanel({ draft, confidenceScore, isStreaming }: DraftPanelProps) {
  if (!draft) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-slate-400">
        <div className="text-xs">等待分析完成...</div>
        {isStreaming && (
          <div className="mt-2 flex items-center gap-1">
            <div className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-pulse" />
            <span className="text-[10px]">AI 正在分析需求</span>
          </div>
        )}
      </div>
    );
  }

  const entities = Array.isArray(draft.entities) ? draft.entities : [];
  const useCases = Array.isArray(draft.use_cases) ? draft.use_cases : [];
  const acceptanceCriteria = Array.isArray(draft.acceptance_criteria) ? draft.acceptance_criteria : [];
  const constraints = Array.isArray(draft.constraints) ? draft.constraints : [];
  const risks = Array.isArray(draft.risks) ? draft.risks : [];

  return (
    <div className="space-y-4 text-xs">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h3 className="font-semibold text-slate-200 text-sm">{draft.title || '未命名需求'}</h3>
        {confidenceScore != null && (
          <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${
            confidenceScore >= 0.8 ? 'bg-emerald-50 text-emerald-600' :
            confidenceScore >= 0.6 ? 'bg-amber-50 text-amber-600' :
            'bg-red-50 text-red-600'
          }`}>
            置信度 {(confidenceScore * 100).toFixed(0)}%
          </span>
        )}
      </div>

      {/* Description */}
      {draft.description && (
        <div>
          <h4 className="text-[10px] font-medium text-slate-400 uppercase tracking-wider mb-1">概述</h4>
          <p className="text-slate-400 leading-relaxed">{draft.description}</p>
        </div>
      )}

      {/* Domain */}
      {draft.domain && (
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-slate-400">领域:</span>
          <span className="px-1.5 py-0.5 bg-slate-700 rounded text-slate-400 text-[10px]">
            {DOMAIN_LABELS[draft.domain] || draft.domain}
          </span>
        </div>
      )}

      {/* Entities */}
      {entities.length > 0 && (
        <div>
          <h4 className="text-[10px] font-medium text-slate-400 uppercase tracking-wider mb-2">
            实体 ({entities.length})
          </h4>
          <div className="space-y-2">
            {entities.map((entity, i) => (
              <div key={i} className="bg-slate-800/50 rounded-lg p-2.5 border border-slate-800">
                <span className="font-medium text-slate-600">{entity.name}</span>
                {entity.description && (
                  <p className="text-[10px] text-slate-400 mt-0.5">{entity.description}</p>
                )}
                {entity.attributes && entity.attributes.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-1.5">
                    {entity.attributes.map((attr, j) => (
                      <span key={j} className="px-1.5 py-0.5 bg-slate-800 rounded text-[10px] text-slate-400 border border-slate-800">
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

      {/* Use Cases */}
      {useCases.length > 0 && (
        <div>
          <h4 className="text-[10px] font-medium text-slate-400 uppercase tracking-wider mb-2">
            用例 ({useCases.length})
          </h4>
          <ul className="space-y-1">
            {useCases.map((uc, i) => (
              <li key={i} className="flex items-start gap-2 text-slate-400">
                <span className="text-slate-600 mt-0.5">•</span>
                <span>{uc}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Acceptance Criteria */}
      {acceptanceCriteria.length > 0 && (
        <div>
          <h4 className="text-[10px] font-medium text-slate-400 uppercase tracking-wider mb-2">
            验收标准 ({acceptanceCriteria.length})
          </h4>
          <div className="space-y-2">
            {acceptanceCriteria.map((ac, i) => (
              <div key={i} className="bg-emerald-50 border border-emerald-100 rounded-lg p-2.5">
                <p className="text-[10px] text-emerald-800 leading-relaxed">{ac}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Constraints */}
      {constraints.length > 0 && (
        <div>
          <h4 className="text-[10px] font-medium text-slate-400 uppercase tracking-wider mb-1">约束条件</h4>
          <ul className="space-y-0.5">
            {constraints.map((c, i) => (
              <li key={i} className="flex items-start gap-2 text-slate-400 text-[10px]">
                <span className="text-slate-600">•</span>
                {c}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Risks */}
      {risks.length > 0 && (
        <div>
          <h4 className="text-[10px] font-medium text-slate-400 uppercase tracking-wider mb-1">风险</h4>
          <ul className="space-y-0.5">
            {risks.map((r, i) => (
              <li key={i} className="flex items-start gap-2 text-amber-600 text-[10px]">
                <span className="text-amber-300">⚠</span>
                {r}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Estimated Cost */}
      {draft.estimated_cost && (
        <div className="flex items-center gap-2 pt-2 border-t border-slate-800">
          <span className="text-[10px] text-slate-400">预估工时:</span>
          <span className="text-[10px] font-medium text-slate-600">{draft.estimated_cost}</span>
        </div>
      )}

      {/* Streaming indicator */}
      {isStreaming && (
        <div className="flex items-center gap-1.5 pt-2">
          <div className="flex gap-0.5">
            <div className="w-1 h-1 bg-blue-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
            <div className="w-1 h-1 bg-blue-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
            <div className="w-1 h-1 bg-blue-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
          </div>
          <span className="text-[9px] text-blue-400">更新中...</span>
        </div>
      )}
    </div>
  );
}

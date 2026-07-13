'use client';

/**
 * ClarificationCard — displays clarification questions as interactive cards.
 * Each card has a question, a suggested answer (pre-filled), and the user
 * can click the suggestion to send it as a reply.
 */
import React from 'react';
import type { ClarificationItem } from '@/lib/types';

interface ClarificationCardProps {
  items: ClarificationItem[];
  onSelect: (response: string) => void;
  disabled?: boolean;
}

export default function ClarificationCard({ items, onSelect, disabled }: ClarificationCardProps) {
  if (!items || items.length === 0) return null;

  return (
    <div className="space-y-2">
      <div className="text-[10px] font-medium text-amber-600 uppercase tracking-wider">
        待澄清 ({items.length})
      </div>
      {items.map((item, i) => (
        <div key={i} className="bg-amber-50 border border-amber-100 rounded-xl p-3">
          <p className="text-xs text-slate-700 font-medium mb-1">{item.question}</p>
          {item.suggestion && (
            <div className="mt-2">
              <span className="text-[9px] text-slate-400">推荐方案:</span>
              <button
                onClick={() => onSelect(item.suggestion)}
                disabled={disabled}
                className="mt-1 block w-full text-left text-[10px] px-3 py-2 bg-white border border-amber-200 rounded-lg text-amber-700 hover:border-amber-400 hover:bg-amber-50 transition-colors disabled:opacity-50"
              >
                {item.suggestion}
              </button>
            </div>
          )}
          {item.field && (
            <div className="mt-1.5">
              <span className="text-[9px] text-slate-300">字段: {item.field}</span>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

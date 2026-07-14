'use client';

import { useState } from 'react';
import type { Annotation } from './PrototypeWorkspace';

interface Props {
  currentVersion: number;
  annotations: Annotation[];
  onSubmit: (annotations: Annotation[]) => void;
  disabled: boolean;
}

const ANNOTATION_TYPES: { key: string; label: string; icon: string }[] = [
  { key: 'layout_change', label: '布局调整', icon: '⊞' },
  { key: 'content_change', label: '内容修改', icon: '✎' },
  { key: 'style_change', label: '样式调整', icon: '🎨' },
  { key: 'add_element', label: '新增元素', icon: '+' },
  { key: 'remove_element', label: '删除元素', icon: '−' },
  { key: 'flow_change', label: '交互流程', icon: '↗' },
  { key: 'other', label: '其他', icon: '…' },
];

export default function AnnotationPanel({
  currentVersion,
  annotations,
  onSubmit,
  disabled,
}: Props) {
  const [selectedType, setSelectedType] = useState('other');
  const [comment, setComment] = useState('');
  const [elementId, setElementId] = useState('');

  const handleSubmit = () => {
    if (!comment.trim()) return;
    const newAnnotation: Annotation = {
      annotation_id: crypto.randomUUID(),
      element_id: elementId,
      type: selectedType,
      comment: comment.trim(),
    };
    onSubmit([newAnnotation]);
    setComment('');
    setElementId('');
  };

  return (
    <div className="h-full flex flex-col">
      <div className="p-3 border-b bg-gray-50">
        <h3 className="text-sm font-semibold">标注工具面板</h3>
        <p className="text-xs text-gray-500 mt-1">
          当前版本: v{currentVersion} | 累计标注: {annotations.length}
        </p>
      </div>

      {/* Annotation type selector */}
      <div className="p-3 border-b">
        <label className="text-xs font-medium text-gray-600 block mb-2">
          标注类型
        </label>
        <div className="grid grid-cols-2 gap-1">
          {ANNOTATION_TYPES.map((t) => (
            <button
              key={t.key}
              onClick={() => setSelectedType(t.key)}
              disabled={disabled}
              className={`text-xs px-2 py-1.5 rounded border transition-colors text-left ${
                selectedType === t.key
                  ? 'bg-blue-50 border-blue-300 text-blue-700'
                  : 'bg-white border-gray-200 text-gray-600 hover:bg-gray-50'
              } ${disabled ? 'opacity-50 cursor-not-allowed' : ''}`}
            >
              <span className="mr-1">{t.icon}</span>
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* Element selector */}
      <div className="p-3 border-b">
        <label className="text-xs font-medium text-gray-600 block mb-1">
          目标元素 (CSS 选择器)
        </label>
        <input
          type="text"
          value={elementId}
          onChange={(e) => setElementId(e.target.value)}
          disabled={disabled}
          placeholder="#table-header, .search-bar..."
          className="w-full text-xs px-2 py-1.5 border rounded focus:outline-none focus:ring-1 focus:ring-blue-400"
        />
      </div>

      {/* Comment input */}
      <div className="flex-1 p-3">
        <label className="text-xs font-medium text-gray-600 block mb-1">
          修改意见
        </label>
        <textarea
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          disabled={disabled}
          placeholder="描述你想要的修改..."
          rows={4}
          className="w-full text-xs px-2 py-1.5 border rounded resize-none focus:outline-none focus:ring-1 focus:ring-blue-400"
        />
        <button
          onClick={handleSubmit}
          disabled={disabled || !comment.trim()}
          className="mt-2 w-full py-1.5 text-xs bg-blue-500 text-white rounded hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          提交标注
        </button>
      </div>

      {/* Annotation history */}
      <div className="border-t max-h-48 overflow-y-auto">
        <div className="p-2 bg-gray-50 border-b">
          <h4 className="text-xs font-medium text-gray-500">标注历史</h4>
        </div>
        {annotations.length === 0 ? (
          <div className="p-3 text-xs text-gray-400 text-center">
            暂无标注记录
          </div>
        ) : (
          annotations.map((a, i) => (
            <div
              key={a.annotation_id || i}
              className="p-2 border-b last:border-0 hover:bg-gray-50"
            >
              <div className="flex items-center gap-1">
                <span className="text-xs font-medium px-1.5 py-0.5 rounded bg-gray-100">
                  {ANNOTATION_TYPES.find((t) => t.key === a.type)?.label || a.type}
                </span>
                {a.element_id && (
                  <code className="text-xs text-gray-400">{a.element_id}</code>
                )}
              </div>
              <p className="text-xs text-gray-600 mt-0.5">{a.comment}</p>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

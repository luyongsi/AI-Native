'use client';

import { useState, useRef, useCallback } from 'react';

export interface Annotation {
  id: string;
  type: 'component' | 'interaction' | 'data-binding';
  x: number;
  y: number;
  width: number;
  height: number;
  label: string;
  properties: Record<string, any>;
}

interface PrototypeAnnotatorProps {
  imageUrl: string;
  reqId: string;
  onAnnotationsSubmitted?: () => void;
}

export function PrototypeAnnotator({
  imageUrl,
  reqId,
  onAnnotationsSubmitted,
}: PrototypeAnnotatorProps) {
  const [annotations, setAnnotations] = useState<Annotation[]>([]);
  const [mode, setMode] = useState<'view' | 'annotate'>('view');
  const [selectedType, setSelectedType] = useState<Annotation['type']>('component');
  const [selectedAnnotation, setSelectedAnnotation] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const canvasRef = useRef<HTMLDivElement>(null);

  const handleCanvasClick = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      if (mode !== 'annotate' || !canvasRef.current) return;

      const rect = canvasRef.current.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;

      // Check if clicking on existing annotation
      const clickedAnnotation = annotations.find((ann) => {
        return (
          x >= ann.x &&
          x <= ann.x + ann.width &&
          y >= ann.y &&
          y <= ann.y + ann.height
        );
      });

      if (clickedAnnotation) {
        setSelectedAnnotation(clickedAnnotation.id);
        return;
      }

      // Create new annotation
      const newAnnotation: Annotation = {
        id: `ann-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
        type: selectedType,
        x,
        y,
        width: 100,
        height: 50,
        label: `New ${selectedType}`,
        properties: {},
      };

      setAnnotations([...annotations, newAnnotation]);
      setSelectedAnnotation(newAnnotation.id);
    },
    [mode, annotations, selectedType]
  );

  const updateAnnotation = (id: string, updates: Partial<Annotation>) => {
    setAnnotations(
      annotations.map((ann) =>
        ann.id === id ? { ...ann, ...updates } : ann
      )
    );
  };

  const deleteAnnotation = (id: string) => {
    setAnnotations(annotations.filter((ann) => ann.id !== id));
    if (selectedAnnotation === id) {
      setSelectedAnnotation(null);
    }
  };

  const handleSubmit = async () => {
    if (annotations.length === 0) {
      alert('请至少添加一个标注');
      return;
    }

    setIsSubmitting(true);
    try {
      const response = await fetch('/api/prototypes/annotate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          req_id: reqId,
          image_url: imageUrl,
          annotations: annotations.map((a) => ({
            id: a.id,
            type: a.type,
            x: a.x,
            y: a.y,
            width: a.width,
            height: a.height,
            label: a.label,
            properties: a.properties,
          })),
        }),
      });

      if (response.ok) {
        alert('标注已提交，A3 正在生成代码...');
        setAnnotations([]);
        setSelectedAnnotation(null);
        setMode('view');
        onAnnotationsSubmitted?.();
      } else {
        const error = await response.json();
        alert(`提交失败: ${error.detail || '请重试'}`);
      }
    } catch (error) {
      alert(`提交失败: ${error instanceof Error ? error.message : '网络错误'}`);
    } finally {
      setIsSubmitting(false);
    }
  };

  const selectedAnn = annotations.find((a) => a.id === selectedAnnotation);

  return (
    <div className="prototype-annotator space-y-4">
      {/* Toolbar */}
      <div className="toolbar flex flex-wrap gap-2 p-3 bg-slate-100 rounded-lg">
        <button
          onClick={() => setMode(mode === 'view' ? 'annotate' : 'view')}
          className={`px-3 py-2 rounded text-sm font-medium transition-colors ${
            mode === 'annotate'
              ? 'bg-emerald-500 text-white'
              : 'bg-white text-slate-700 border border-slate-300'
          }`}
        >
          {mode === 'view' ? '开始标注' : '查看模式'}
        </button>

        {mode === 'annotate' && (
          <>
            <select
              value={selectedType}
              onChange={(e) =>
                setSelectedType(e.target.value as Annotation['type'])
              }
              className="px-3 py-2 border border-slate-300 rounded text-sm bg-white"
            >
              <option value="component">组件</option>
              <option value="interaction">交互</option>
              <option value="data-binding">数据绑定</option>
            </select>

            <button
              onClick={handleSubmit}
              disabled={isSubmitting}
              className="ml-auto px-4 py-2 bg-blue-500 text-white rounded text-sm font-medium hover:bg-blue-600 disabled:opacity-50"
            >
              {isSubmitting ? '提交中...' : '提交标注'}
            </button>
          </>
        )}

        <div className="flex-1 text-right text-xs text-slate-600">
          标注数: {annotations.length}
        </div>
      </div>

      {/* Main Canvas */}
      <div className="flex gap-4">
        <div className="flex-1">
          <div
            ref={canvasRef}
            onClick={handleCanvasClick}
            className={`relative bg-gray-50 rounded-lg overflow-hidden border-2 ${
              mode === 'annotate'
                ? 'border-blue-300 cursor-crosshair'
                : 'border-slate-200 cursor-default'
            }`}
            style={{ minHeight: '600px' }}
          >
            {/* Background Image */}
            <img
              src={imageUrl}
              alt="Prototype"
              className="w-full h-full object-cover"
              style={{
                pointerEvents: mode === 'annotate' ? 'none' : 'auto',
              }}
            />

            {/* Annotations */}
            {annotations.map((ann) => (
              <div
                key={ann.id}
                onClick={(e) => {
                  e.stopPropagation();
                  setSelectedAnnotation(ann.id);
                }}
                className={`absolute transition-all ${
                  selectedAnnotation === ann.id
                    ? 'ring-2 ring-blue-500 z-10'
                    : 'ring-1 ring-slate-400 z-5 hover:ring-2 hover:ring-blue-400'
                }`}
                style={{
                  left: `${ann.x}px`,
                  top: `${ann.y}px`,
                  width: `${ann.width}px`,
                  height: `${ann.height}px`,
                  backgroundColor: `rgba(59, 130, 246, 0.1)`,
                  cursor: 'pointer',
                }}
              >
                <div className="text-xs font-medium text-blue-700 p-1 bg-white/90 whitespace-nowrap overflow-hidden text-ellipsis">
                  {ann.label}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Properties Panel */}
        {selectedAnn && mode === 'annotate' && (
          <div className="w-64 bg-white border border-slate-200 rounded-lg p-4 space-y-3">
            <h3 className="font-semibold text-slate-900">标注属性</h3>

            {/* Label */}
            <div>
              <label className="block text-xs font-medium text-slate-700 mb-1">
                标签
              </label>
              <input
                type="text"
                value={selectedAnn.label}
                onChange={(e) =>
                  updateAnnotation(selectedAnn.id, { label: e.target.value })
                }
                className="w-full px-2 py-1 border border-slate-300 rounded text-sm"
              />
            </div>

            {/* Type */}
            <div>
              <label className="block text-xs font-medium text-slate-700 mb-1">
                类型
              </label>
              <select
                value={selectedAnn.type}
                onChange={(e) =>
                  updateAnnotation(selectedAnn.id, {
                    type: e.target.value as Annotation['type'],
                  })
                }
                className="w-full px-2 py-1 border border-slate-300 rounded text-sm"
              >
                <option value="component">组件</option>
                <option value="interaction">交互</option>
                <option value="data-binding">数据绑定</option>
              </select>
            </div>

            {/* Position */}
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1">
                  X
                </label>
                <input
                  type="number"
                  value={Math.round(selectedAnn.x)}
                  onChange={(e) =>
                    updateAnnotation(selectedAnn.id, {
                      x: parseInt(e.target.value) || 0,
                    })
                  }
                  className="w-full px-2 py-1 border border-slate-300 rounded text-sm"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1">
                  Y
                </label>
                <input
                  type="number"
                  value={Math.round(selectedAnn.y)}
                  onChange={(e) =>
                    updateAnnotation(selectedAnn.id, {
                      y: parseInt(e.target.value) || 0,
                    })
                  }
                  className="w-full px-2 py-1 border border-slate-300 rounded text-sm"
                />
              </div>
            </div>

            {/* Size */}
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1">
                  宽
                </label>
                <input
                  type="number"
                  value={Math.round(selectedAnn.width)}
                  onChange={(e) =>
                    updateAnnotation(selectedAnn.id, {
                      width: parseInt(e.target.value) || 1,
                    })
                  }
                  className="w-full px-2 py-1 border border-slate-300 rounded text-sm"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1">
                  高
                </label>
                <input
                  type="number"
                  value={Math.round(selectedAnn.height)}
                  onChange={(e) =>
                    updateAnnotation(selectedAnn.id, {
                      height: parseInt(e.target.value) || 1,
                    })
                  }
                  className="w-full px-2 py-1 border border-slate-300 rounded text-sm"
                />
              </div>
            </div>

            {/* Delete Button */}
            <button
              onClick={() => deleteAnnotation(selectedAnn.id)}
              className="w-full px-3 py-2 bg-red-50 text-red-600 rounded text-sm font-medium hover:bg-red-100"
            >
              删除标注
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

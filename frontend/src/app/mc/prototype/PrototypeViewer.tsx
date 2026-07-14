'use client';

import { useState, useRef, useCallback } from 'react';
import { api } from '@/lib/api';
import { streamPrototype, type PrototypeSSEHandlers } from '@/services/prototype-sse';

interface Props {
  reqId: string;
  prototypeUrl: string | null;
  onAnnotate?: (elementId: string, type: string, comment: string) => void;
}

export default function PrototypeViewer({ reqId, prototypeUrl, onAnnotate }: Props) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [currentState, setCurrentState] = useState('default');
  const [annotating, setAnnotating] = useState(false);
  const [selectedElement, setSelectedElement] = useState<string | null>(null);

  const states = [
    { key: 'default', label: '默认' },
    { key: 'loading', label: '加载中' },
    { key: 'empty', label: '空数据' },
    { key: 'error', label: '错误' },
  ];

  const handleStateSwitch = useCallback((state: string) => {
    setCurrentState(state);
    if (iframeRef.current?.contentWindow) {
      (iframeRef.current.contentWindow as any).showState?.(state);
    }
  }, []);

  return (
    <div className="flex flex-col h-full">
      {/* State switcher */}
      <div className="flex gap-2 p-2 bg-gray-50 border-b">
        {states.map((s) => (
          <button
            key={s.key}
            onClick={() => handleStateSwitch(s.key)}
            className={`px-3 py-1 text-xs rounded-full transition-colors ${
              currentState === s.key
                ? 'bg-blue-500 text-white'
                : 'bg-white text-gray-600 border hover:bg-gray-100'
            }`}
          >
            {s.label}
          </button>
        ))}
        <div className="flex-1" />
        <button
          onClick={() => setAnnotating(!annotating)}
          className={`px-3 py-1 text-xs rounded-full transition-colors ${
            annotating
              ? 'bg-orange-500 text-white'
              : 'bg-white text-gray-600 border hover:bg-gray-100'
          }`}
        >
          {annotating ? '标注中' : '标注模式'}
        </button>
      </div>

      {/* Prototype iframe */}
      <div className="flex-1 relative bg-white">
        {prototypeUrl ? (
          <iframe
            ref={iframeRef}
            src={prototypeUrl}
            className="w-full h-full border-0"
            sandbox="allow-scripts"
            title="Prototype Preview"
          />
        ) : (
          <div className="flex items-center justify-center h-full text-gray-400">
            <div className="text-center">
              <div className="text-4xl mb-2">📐</div>
              <p className="text-sm">暂无原型，请先生成</p>
            </div>
          </div>
        )}
      </div>

      {annotating && (
        <div className="p-2 bg-orange-50 border-t border-orange-200 text-xs text-orange-700">
          标注模式已开启 — 点击原型中的元素选择要标注的内容
        </div>
      )}
    </div>
  );
}

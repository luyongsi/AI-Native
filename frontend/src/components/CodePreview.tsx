'use client';

import { useEffect, useState } from 'react';
import { useActivityStream } from '@/hooks/useActivityStream';

interface CodePreviewProps {
  reqId: string;
}

export function CodePreview({ reqId }: CodePreviewProps) {
  const { activities } = useActivityStream({ reqId });
  const [code, setCode] = useState<string>('');
  const [codeType, setCodeType] = useState<string>('');
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    // Monitor activity stream for code updates
    const codeUpdate = activities.find(
      (a) =>
        a.type === 'artifact' &&
        a.details?.artifact_type === 'ui_code_patch'
    );

    if (codeUpdate && codeUpdate.details?.artifact) {
      const artifact = codeUpdate.details.artifact;
      if (artifact.code) {
        setCode(artifact.code);
        setCodeType(artifact.type || 'tsx');
        setIsLoading(false);
      }
    }

    // Check for progress events related to code generation
    const progressEvent = activities.find(
      (a) =>
        a.type === 'progress' &&
        (a.details?.step?.includes('annotation') ||
          a.details?.step?.includes('code'))
    );

    if (progressEvent) {
      setIsLoading(true);
    }
  }, [activities]);

  const copyToClipboard = async () => {
    try {
      await navigator.clipboard.writeText(code);
      alert('代码已复制到剪贴板');
    } catch {
      alert('复制失败');
    }
  };

  const downloadCode = () => {
    const element = document.createElement('a');
    const file = new Blob([code], { type: 'text/plain' });
    element.href = URL.createObjectURL(file);
    element.download = `generated.${codeType}`;
    document.body.appendChild(element);
    element.click();
    document.body.removeChild(element);
  };

  return (
    <div className="code-preview space-y-3 rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold text-slate-900">生成的代码（实时更新）</h3>
        {isLoading && (
          <span className="inline-flex items-center gap-2 text-xs text-amber-600">
            <span className="animate-pulse">●</span>
            正在生成...
          </span>
        )}
      </div>

      {code ? (
        <>
          <div className="flex gap-2">
            <button
              onClick={copyToClipboard}
              className="px-3 py-1 text-sm bg-blue-50 text-blue-600 rounded hover:bg-blue-100"
            >
              复制
            </button>
            <button
              onClick={downloadCode}
              className="px-3 py-1 text-sm bg-emerald-50 text-emerald-600 rounded hover:bg-emerald-100"
            >
              下载
            </button>
            <span className="ml-auto text-xs text-slate-500">
              {codeType}
            </span>
          </div>

          <div className="relative bg-slate-900 rounded overflow-hidden">
            <pre className="p-4 overflow-auto max-h-96">
              <code className="text-xs text-slate-100 font-mono">
                {code}
              </code>
            </pre>
          </div>
        </>
      ) : (
        <div className="py-12 text-center text-slate-400 text-sm">
          {isLoading ? '正在生成代码...' : '标注后生成的代码将显示在这里'}
        </div>
      )}
    </div>
  );
}

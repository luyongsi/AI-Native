'use client';

import { useState, useEffect } from 'react';
import { api } from '@/lib/api';

interface VersionEntry {
  version: number;
  status: string;
  prototype_url: string | null;
  screens: any[];
  annotations: any[];
  created_at: string | null;
  updated_at: string | null;
}

interface Props {
  reqId: string;
  currentVersion: number;
  onSelectVersion: (version: number, url: string | null) => void;
}

export default function VersionHistory({ reqId, currentVersion, onSelectVersion }: Props) {
  const [versions, setVersions] = useState<VersionEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<number | null>(null);

  useEffect(() => {
    setLoading(true);
    fetch(`/api/prototype/history/${reqId}`)
      .then((r) => r.json())
      .then((data) => setVersions(data.versions || []))
      .catch(() => setVersions([]))
      .finally(() => setLoading(false));
  }, [reqId]);

  const statusBadge = (status: string) => {
    if (status === 'confirmed') {
      return (
        <span className="px-1.5 py-0.5 text-xs rounded bg-green-100 text-green-700">
          已确认
        </span>
      );
    }
    return (
      <span className="px-1.5 py-0.5 text-xs rounded bg-yellow-100 text-yellow-700">
        草稿
      </span>
    );
  };

  if (loading) {
    return (
      <div className="p-3 text-xs text-gray-400 text-center">
        加载版本历史...
      </div>
    );
  }

  if (versions.length === 0) {
    return (
      <div className="p-3 text-xs text-gray-400 text-center">
        暂无版本记录
      </div>
    );
  }

  return (
    <div className="overflow-y-auto max-h-96">
      <div className="p-2 bg-gray-50 border-b sticky top-0">
        <h4 className="text-xs font-medium text-gray-500">版本历史</h4>
      </div>
      {versions.map((v) => (
        <div
          key={v.version}
          className={`border-b last:border-0 ${
            v.version === currentVersion ? 'bg-blue-50' : ''
          }`}
        >
          <button
            onClick={() => {
              setExpanded(expanded === v.version ? null : v.version);
              onSelectVersion(v.version, v.prototype_url);
            }}
            className="w-full p-2 text-left hover:bg-gray-50 transition-colors flex items-center justify-between"
          >
            <div className="flex items-center gap-2">
              <span className="text-xs font-mono font-medium">
                v{v.version}
              </span>
              {statusBadge(v.status)}
              {v.version === currentVersion && (
                <span className="text-xs text-blue-500">当前</span>
              )}
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-gray-400">
                {v.annotations?.length || 0} 条标注
              </span>
              <span className="text-xs text-gray-300">
                {expanded === v.version ? '▾' : '▸'}
              </span>
            </div>
          </button>

          {expanded === v.version && (
            <div className="px-3 pb-2">
              {v.created_at && (
                <p className="text-xs text-gray-400">
                  创建: {new Date(v.created_at).toLocaleString('zh-CN')}
                </p>
              )}
              {v.screens?.length > 0 && (
                <div className="mt-1">
                  <span className="text-xs text-gray-500">
                    {v.screens.length} 张截图
                  </span>
                </div>
              )}
              {v.annotations?.length > 0 && (
                <div className="mt-1">
                  <span className="text-xs text-gray-500">标注:</span>
                  {v.annotations.slice(0, 3).map((a: any, i: number) => (
                    <p key={i} className="text-xs text-gray-500 ml-2 truncate">
                      [{ANNOTATION_TYPE_MAP[a.type] || a.type}] {a.comment}
                    </p>
                  ))}
                  {v.annotations.length > 3 && (
                    <p className="text-xs text-gray-400 ml-2">
                      ...共 {v.annotations.length} 条
                    </p>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

const ANNOTATION_TYPE_MAP: Record<string, string> = {
  layout_change: '布局',
  content_change: '内容',
  style_change: '样式',
  add_element: '新增',
  remove_element: '删除',
  flow_change: '流程',
  other: '其他',
};

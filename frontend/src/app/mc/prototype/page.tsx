'use client';

import { useSearchParams } from 'next/navigation';
import { Suspense } from 'react';
import PrototypeWorkspace from './PrototypeWorkspace';

function PrototypePageInner() {
  const searchParams = useSearchParams();
  const reqId = searchParams.get('req_id') || '';

  if (!reqId) {
    return (
      <div className="p-8 text-center text-gray-500">
        <p className="text-lg">缺少需求 ID</p>
        <p className="text-sm mt-2">请从需求详情页进入原型工作区</p>
      </div>
    );
  }

  return <PrototypeWorkspace reqId={reqId} />;
}

export default function PrototypePage() {
  return (
    <Suspense
      fallback={
        <div className="flex items-center justify-center h-64 text-gray-400">
          <div className="animate-spin w-8 h-8 border-2 border-blue-400 border-t-transparent rounded-full" />
        </div>
      }
    >
      <PrototypePageInner />
    </Suspense>
  );
}

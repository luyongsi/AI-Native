'use client';

type ViewType = 'swarm' | 'livetail' | 'topology';

interface ViewSwitcherProps {
  activeView: ViewType;
  onViewChange: (view: ViewType) => void;
}

const views: { key: ViewType; label: string }[] = [
  { key: 'swarm', label: '需求蜂群' },
  { key: 'livetail', label: '活动直播' },
  { key: 'topology', label: '协作拓扑图' },
];

export default function ViewSwitcher({ activeView, onViewChange }: ViewSwitcherProps) {
  return (
    <div className="flex bg-slate-700 rounded-lg p-0.5">
      {views.map((v) => (
        <button
          key={v.key}
          onClick={() => onViewChange(v.key)}
          className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
            activeView === v.key
              ? 'bg-slate-800 text-slate-100 shadow-sm'
              : 'text-slate-400'
          }`}
        >
          {v.label}
        </button>
      ))}
    </div>
  );
}

import { create } from 'zustand';

interface WidgetInstance {
  widgetId: string;
  position: { x: number; y: number };
  size: { w: number; h: number };
}

interface DashboardStore {
  widgets: WidgetInstance[];
  addWidget: (widgetId: string) => void;
  removeWidget: (instanceId: string) => void;
  moveWidget: (widgetId: string, position: { x: number; y: number }) => void;
  resizeWidget: (widgetId: string, size: { w: number; h: number }) => void;
  resetLayout: () => void;
}

const defaultWidgets: WidgetInstance[] = [
  { widgetId: 'pipeline', position: { x: 0, y: 0 }, size: { w: 2, h: 1 } },
  { widgetId: 'approvals', position: { x: 2, y: 0 }, size: { w: 1, h: 1 } },
  { widgetId: 'my-requirements', position: { x: 0, y: 1 }, size: { w: 2, h: 1 } },
  { widgetId: 'agent-activity', position: { x: 2, y: 1 }, size: { w: 1, h: 1 } },
  { widgetId: 'topology', position: { x: 0, y: 2 }, size: { w: 3, h: 1 } },
];

export const useDashboardStore = create<DashboardStore>((set) => ({
  widgets: defaultWidgets,
  addWidget: (widgetId) =>
    set((state) => ({
      widgets: [...state.widgets, { widgetId, position: { x: 0, y: Infinity }, size: { w: 1, h: 1 } }],
    })),
  removeWidget: (widgetId) =>
    set((state) => ({ widgets: state.widgets.filter((w) => w.widgetId !== widgetId) })),
  moveWidget: (widgetId, position) =>
    set((state) => ({
      widgets: state.widgets.map((w) => (w.widgetId === widgetId ? { ...w, position } : w)),
    })),
  resizeWidget: (widgetId, size) =>
    set((state) => ({
      widgets: state.widgets.map((w) => (w.widgetId === widgetId ? { ...w, size } : w)),
    })),
  resetLayout: () => set({ widgets: defaultWidgets }),
}));

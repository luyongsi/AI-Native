"use client";

import { useState, useCallback, useRef, useEffect, ReactNode } from "react";

interface ThreeColumnLayoutProps {
  left: ReactNode;
  center: ReactNode;
  right: ReactNode;
  defaultLeftWidth?: number;
  defaultCenterWidth?: number;
  minWidth?: number;
}

export default function ThreeColumnLayout({
  left,
  center,
  right,
  defaultLeftWidth = 30,
  defaultCenterWidth = 40,
  minWidth = 250,
}: ThreeColumnLayoutProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [leftWidth, setLeftWidth] = useState(defaultLeftWidth);
  const [centerWidth, setCenterWidth] = useState(defaultCenterWidth);
  const [dragging, setDragging] = useState<"left" | "right" | null>(null);

  const rightWidth = 100 - leftWidth - centerWidth;

  const handleMouseDown = useCallback(
    (side: "left" | "right") => (e: React.MouseEvent) => {
      e.preventDefault();
      setDragging(side);
    },
    []
  );

  useEffect(() => {
    if (!dragging) return;

    const handleMouseMove = (e: MouseEvent) => {
      if (!containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      const totalWidth = rect.width;
      const x = e.clientX - rect.left;
      const pct = (x / totalWidth) * 100;

      if (dragging === "left") {
        const newLeft = Math.max(20, Math.min(45, pct));
        const maxCenter = 100 - newLeft - 20;
        const newCenter = Math.min(centerWidth, maxCenter);
        setLeftWidth(newLeft);
        setCenterWidth(newCenter);
      } else {
        const newRight = 100 - pct;
        const clampedRight = Math.max(20, Math.min(45, newRight));
        const newCenter = 100 - leftWidth - clampedRight;
        if (newCenter >= 20) {
          setCenterWidth(newCenter);
        }
      }
    };

    const handleMouseUp = () => setDragging(null);

    document.addEventListener("mousemove", handleMouseMove);
    document.addEventListener("mouseup", handleMouseUp);
    return () => {
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
    };
  }, [dragging, centerWidth, leftWidth]);

  return (
    <div
      ref={containerRef}
      className="flex h-full overflow-hidden"
      style={{ userSelect: dragging ? "none" : "auto" }}
    >
      {/* Left Panel */}
      <div
        className="flex-shrink-0 overflow-y-auto border-r border-slate-700 bg-slate-800"
        style={{ width: `${leftWidth}%`, minWidth }}
      >
        {left}
      </div>

      {/* Left Resizer */}
      <ResizerHandle onMouseDown={handleMouseDown("left")} isDragging={dragging === "left"} />

      {/* Center Panel */}
      <div
        className="flex-1 overflow-hidden flex flex-col"
        style={{ minWidth: 350 }}
      >
        {center}
      </div>

      {/* Right Resizer */}
      <ResizerHandle onMouseDown={handleMouseDown("right")} isDragging={dragging === "right"} />

      {/* Right Panel */}
      <div
        className="flex-shrink-0 overflow-y-auto border-l border-slate-700 bg-slate-800"
        style={{ width: `${rightWidth}%`, minWidth }}
      >
        {right}
      </div>
    </div>
  );
}

function ResizerHandle({
  onMouseDown,
  isDragging,
}: {
  onMouseDown: (e: React.MouseEvent) => void;
  isDragging: boolean;
}) {
  return (
    <div
      onMouseDown={onMouseDown}
      className={`w-1.5 flex-shrink-0 cursor-col-resize relative group
        hover:bg-brand/20 transition-colors z-10
        ${isDragging ? "bg-brand/30" : "bg-transparent"}`}
    >
      <div
        className={`absolute inset-y-0 left-1/2 -translate-x-1/2 w-0.5 rounded-full transition-all
          ${isDragging ? "bg-brand scale-x-150" : "bg-slate-200 group-hover:bg-brand/50 group-hover:scale-x-150"}`}
      />
    </div>
  );
}

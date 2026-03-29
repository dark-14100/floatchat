"use client";

import { useEffect, useMemo, useState } from "react";
import { Responsive, type Layout, type LayoutItem } from "react-grid-layout";
import { Trash2, BarChart2 } from "lucide-react";
import VisualizationPanel from "@/components/visualization/VisualizationPanel";
import { useChatStore } from "@/store/chatStore";

const ResponsiveGridLayout = Responsive;

export default function DashboardPage() {
  const [gridWidth, setGridWidth] = useState(1200);
  const pinnedWidgets = useChatStore((s) => s.pinnedWidgets);
  const removeWidget = useChatStore((s) => s.removeWidget);
  const updateWidgetLayout = useChatStore((s) => s.updateWidgetLayout);

  useEffect(() => {
    const updateWidth = () => {
      setGridWidth(window.innerWidth - 340);
    };

    updateWidth();
    window.addEventListener("resize", updateWidth);
    return () => window.removeEventListener("resize", updateWidth);
  }, []);

  const layouts = useMemo(() => {
    const base = pinnedWidgets.map((widget) => ({
      i: widget.id,
      x: widget.layout.x,
      y: widget.layout.y,
      w: widget.layout.w,
      h: widget.layout.h,
      minW: 3,
      minH: 4,
    }));

    return {
      lg: base,
      md: base,
      sm: base,
    };
  }, [pinnedWidgets]);

  const handleLayoutChange = (currentLayout: Layout) => {
    currentLayout.forEach((item) => {
      const gridItem = item as LayoutItem;
      updateWidgetLayout(item.i, {
        x: gridItem.x,
        y: gridItem.y,
        w: gridItem.w,
        h: gridItem.h,
      });
    });
  };

  if (pinnedWidgets.length === 0) {
    return (
      <div className="flex h-full min-h-[calc(100vh-3.5rem)] items-center justify-center p-8">
        <div className="max-w-md rounded-2xl border border-border-subtle bg-bg-surface p-10 text-center shadow-md">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-ocean-lighter/30">
            <BarChart2 className="h-7 w-7 text-ocean-primary" />
          </div>
          <h1 className="font-display text-2xl font-semibold text-text-primary">Dashboard</h1>
          <p className="mt-3 text-sm leading-relaxed text-text-secondary">
            No visualizations pinned yet. Ask questions in the chat and pin
            charts or maps to build your dashboard.
          </p>
          <a
            href="/chat"
            className="mt-6 inline-flex items-center gap-2 rounded-md bg-ocean-primary px-5 py-2.5 text-sm font-medium text-text-inverse transition-colors hover:bg-ocean-light"
          >
            Start a conversation
          </a>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full p-4 md:p-6">
      <div className="mb-4 flex items-center justify-between">
        <h1 className="font-display text-2xl text-foreground">Dashboard</h1>
        <p className="text-xs text-muted-foreground">{pinnedWidgets.length}/10 widgets</p>
      </div>

      <ResponsiveGridLayout
        className="layout"
        width={Math.max(gridWidth, 320)}
        layouts={layouts}
        breakpoints={{ lg: 1200, md: 768, sm: 480 }}
        cols={{ lg: 12, md: 8, sm: 4 }}
        rowHeight={36}
        margin={[16, 16]}
        onLayoutChange={handleLayoutChange}
      >
        {pinnedWidgets.map((widget) => (
          <div key={widget.id} className="overflow-hidden rounded-xl border border-border bg-card shadow-sm">
            <div className="widget-drag flex cursor-move items-center justify-between border-b border-border px-3 py-2">
              <p className="truncate text-sm font-medium text-foreground">{widget.label}</p>
              <button
                type="button"
                onClick={() => removeWidget(widget.id)}
                className="rounded p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                aria-label="Remove widget"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
            <div className="h-[calc(100%-40px)] overflow-auto p-2">
              <VisualizationPanel
                columns={widget.columns}
                rows={widget.rows}
                messageId={widget.id}
              />
            </div>
          </div>
        ))}
      </ResponsiveGridLayout>
    </div>
  );
}

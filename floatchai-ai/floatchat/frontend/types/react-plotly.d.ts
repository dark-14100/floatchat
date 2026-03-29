/**
 * Type declaration for react-plotly.js.
 * The package does not ship its own TypeScript types.
 */
declare module "react-plotly.js" {
    import * as Plotly from "plotly.js";
    import * as React from "react";

    interface PlotParams {
        data: Plotly.Data[];
        layout?: Partial<Plotly.Layout>;
        frames?: Plotly.Frame[];
        config?: Partial<Plotly.Config>;
        useResizeHandler?: boolean;
        style?: React.CSSProperties;
        className?: string;
        divId?: string;

        onInitialized?: (
            figure: Readonly<{ data: Plotly.Data[]; layout: Partial<Plotly.Layout>; frames?: Plotly.Frame[] }>,
            graphDiv: HTMLElement,
        ) => void;
        onUpdate?: (
            figure: Readonly<{ data: Plotly.Data[]; layout: Partial<Plotly.Layout>; frames?: Plotly.Frame[] }>,
            graphDiv: HTMLElement,
        ) => void;
        onPurge?: (
            figure: Readonly<{ data: Plotly.Data[]; layout: Partial<Plotly.Layout>; frames?: Plotly.Frame[] }>,
            graphDiv: HTMLElement,
        ) => void;
        onError?: (err: Error) => void;

        onAfterExport?: () => void;
        onAfterPlot?: () => void;
        onAnimated?: () => void;
        onAnimatingFrame?: (event: Plotly.FrameAnimationEvent) => void;
        onAnimationInterrupted?: () => void;
        onAutoSize?: () => void;
        onBeforeExport?: () => void;
        onBeforeHover?: (event: Plotly.PlotMouseEvent) => boolean;
        onClick?: (event: Plotly.PlotMouseEvent) => void;
        onClickAnnotation?: (event: Plotly.ClickAnnotationEvent) => void;
        onDeselect?: () => void;
        onDoubleClick?: () => void;
        onFramework?: () => void;
        onHover?: (event: Plotly.PlotMouseEvent) => void;
        onLegendClick?: (event: Plotly.LegendClickEvent) => boolean;
        onLegendDoubleClick?: (event: Plotly.LegendClickEvent) => boolean;
        onRelayout?: (event: Plotly.PlotRelayoutEvent) => void;
        onRelayouting?: (event: Plotly.PlotRelayoutEvent) => void;
        onRestyle?: (event: Plotly.PlotRestyleEvent) => void;
        onRedraw?: () => void;
        onSelected?: (event: Plotly.PlotSelectionEvent) => void;
        onSelecting?: (event: Plotly.PlotSelectionEvent) => void;
        onSliderChange?: (event: Plotly.SliderChangeEvent) => void;
        onSliderEnd?: (event: Plotly.SliderEndEvent) => void;
        onSliderStart?: (event: Plotly.SliderStartEvent) => void;
        onSunburstClick?: (event: Plotly.SunburstClickEvent) => void;
        onTransitioning?: () => void;
        onTransitionInterrupted?: () => void;
        onUnhover?: (event: Plotly.PlotMouseEvent) => void;
        onWebGlContextLost?: () => void;
    }

    const Plot: React.ComponentType<PlotParams>;
    export default Plot;
}

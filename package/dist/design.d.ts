import type { WaveFrame } from '@dg-kit/core';
export type DesignSegment = RampSegment | HoldSegment | PulseSegment | SilenceSegment;
export interface RampSegment {
    type: 'ramp';
    /** Start intensity, 0-100. */
    from: number;
    /** End intensity, 0-100. */
    to: number;
    /** Total segment duration in milliseconds; rounded to 25 ms frame grid. */
    durationMs: number;
    /** Pulse-frequency value in ms (10-1000). Default 100. */
    frequencyMs?: number;
}
export interface HoldSegment {
    type: 'hold';
    intensity: number;
    durationMs: number;
    frequencyMs?: number;
}
export interface PulseSegment {
    type: 'pulse';
    intensity: number;
    /** On phase in milliseconds; rounded to 25 ms grid. */
    onMs: number;
    /** Off phase in milliseconds; rounded to 25 ms grid. */
    offMs: number;
    /** Number of on/off cycles. */
    count: number;
    frequencyMs?: number;
}
export interface SilenceSegment {
    type: 'silence';
    durationMs: number;
}
export interface CompiledDesign {
    frames: WaveFrame[];
    totalDurationMs: number;
}
export declare function compileWaveformDesign(segments: DesignSegment[]): CompiledDesign;
//# sourceMappingURL=design.d.ts.map
import type { WaveFrame } from '@dg-kit/core';
export declare function encodeFreq(value: number): number;
export interface ParsedPulse {
    /** Embedded waveform name from the file (the part before "="); empty if missing. */
    name: string;
    frames: WaveFrame[];
}
export declare function parsePulseText(data: string): ParsedPulse;
/**
 * Convenience helper: turn a parsed pulse + filename into a `WaveformDefinition`
 * with a stable-but-unique id. Used by importers (browser file input, Node fs).
 */
export declare function pulseToWaveformDefinition(fileName: string, parsed: ParsedPulse, options?: {
    idPrefix?: string;
}): {
    id: string;
    name: string;
    frames: WaveFrame[];
};
//# sourceMappingURL=pulse.d.ts.map
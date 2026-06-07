const BUILTIN_WAVEFORMS = [
    {
        id: 'breath',
        name: '呼吸',
        description: '渐强渐弱，最温柔的铺垫波形',
        frames: [
            [10, 0],
            [10, 20],
            [10, 40],
            [10, 60],
            [10, 80],
            [10, 100],
            [10, 100],
            [10, 100],
            [10, 0],
            [10, 0],
            [10, 0],
            [10, 0],
        ],
    },
    {
        id: 'tide',
        name: '潮汐',
        description: '波浪般起伏的慢节奏',
        frames: [
            [10, 0],
            [11, 16],
            [13, 33],
            [14, 50],
            [16, 66],
            [18, 83],
            [19, 100],
            [21, 92],
            [22, 84],
            [24, 76],
            [26, 68],
            [26, 0],
            [27, 16],
            [29, 33],
            [30, 50],
            [32, 66],
            [34, 83],
            [35, 100],
            [37, 92],
            [38, 84],
            [40, 76],
            [42, 68],
        ],
    },
    {
        id: 'pulse_low',
        name: '低脉冲',
        description: '轻柔的规律节奏',
        frames: Array.from({ length: 10 }, () => [10, 30]),
    },
    {
        id: 'pulse_mid',
        name: '中脉冲',
        description: '中等强度的规律节奏',
        frames: Array.from({ length: 10 }, () => [10, 60]),
    },
    {
        id: 'pulse_high',
        name: '高脉冲',
        description: '强烈的规律节奏',
        frames: Array.from({ length: 10 }, () => [10, 100]),
    },
    {
        id: 'tap',
        name: '敲击',
        description: '带节奏停顿的点触感',
        frames: [
            [10, 100],
            [10, 0],
            [10, 0],
            [10, 100],
            [10, 0],
            [10, 0],
        ],
    },
];
class BasicWaveformLibrary {
    byId = new Map(BUILTIN_WAVEFORMS.map((waveform) => [waveform.id, cloneWaveform(waveform)]));
    async getById(id) {
        const waveform = this.byId.get(id);
        return waveform ? cloneWaveform(waveform) : null;
    }
    async list() {
        return [...this.byId.values()].map(cloneWaveform);
    }
}
export function createBasicWaveformLibrary() {
    return new BasicWaveformLibrary();
}
export function listBuiltinWaveforms() {
    return BUILTIN_WAVEFORMS.map(cloneWaveform);
}
function cloneWaveform(waveform) {
    return {
        ...waveform,
        frames: waveform.frames.map((frame) => [frame[0], frame[1]]),
    };
}
//# sourceMappingURL=basic.js.map
"""Summarize all six native measurements without hiding per-run variation."""
import json
from pathlib import Path
import statistics


MIB = 2 ** 20
STAGES = ('single', 'multi', 'switch', 'settings', 'return')


def median(values):
    return statistics.median(values)


def summarize(data):
    assert not data['errors'], data['errors']
    result = {}
    for stage in STAGES:
        samples = [item for item in data['samples'] if item['stage'] == stage]
        assert len(samples) >= 10, stage
        start = samples[0]['time']
        steady = [item for item in samples if item['time'] >= start + 5]
        groups = {}
        for frame in data['frames']:
            if frame['stage'] == stage:
                groups.setdefault(frame['window'], []).append(frame)
        playback = []
        for window, frames in groups.items():
            discontinuities = sum(b['index'] - a['index'] - 1
                                  for a, b in zip(frames, frames[1:])
                                  if b['movie'] == a['movie'] and b['index'] > a['index'] + 1)
            interval = frames[-1]['time'] - frames[0]['time']
            playback.append({'window': window, 'displayed_frames': len(frames),
                             'delivery_fps': (len(frames) - 1) / interval if interval else 0,
                             'forward_source_gaps': discontinuities})
        assert playback, stage
        components = {}
        for kind in ('main', 'settings', 'ffmpeg'):
            values = [sum(p['footprint'] for p in sample['processes'].values()
                          if p['kind'] == kind) / MIB for sample in samples]
            steady_values = [sum(p['footprint'] for p in sample['processes'].values()
                                 if p['kind'] == kind) / MIB for sample in steady]
            components[kind] = {'stable_mib': median(steady_values), 'peak_mib': max(values)}
        # Short-phase tail-minus-head is a trend signal, not a long-term leak test.
        delta = (median(s['footprint'] for s in samples[-5:])
                 - median(s['footprint'] for s in samples[:5])) / MIB
        result[stage] = {'samples': len(samples), 'steady_samples': len(steady),
                         'stable_mib': median(s['footprint'] for s in steady) / MIB,
                         'peak_mib': max(s['footprint'] for s in samples) / MIB,
                         'rss_stable_mib': median(s['rss'] for s in steady) / MIB,
                         'tail_minus_head_mib': delta, 'components': components,
                         'playback': playback}
    return {'stages': result, 'queue_drops': data['perfstats'].get('webm.queue_drop', {}).get('count', 0),
            'perfstats': data['perfstats']}


def main():
    root = Path(__file__).resolve().parent.parent
    output = root / 'docs/evidence/dsr-pet'
    runs = {}
    for label in ('baseline', 'optimized'):
        runs[label] = []
        for repetition in (1, 2, 3):
            artifact = json.loads((output / f'{label}-{repetition}.run.json').read_text())
            assert artifact['exit_status'] == 0, artifact
            data = json.loads((output / f'{label}-{repetition}.json').read_text())
            runs[label].append(summarize(data))
    comparison = {}
    for stage in STAGES:
        entry = {}
        for label in runs:
            values = [run['stages'][stage]['stable_mib'] for run in runs[label]]
            entry[label] = {'stable_runs_mib': values, 'median_stable_mib': median(values),
                            'peaks_mib': [run['stages'][stage]['peak_mib'] for run in runs[label]],
                            'growth_runs_mib': [run['stages'][stage]['tail_minus_head_mib'] for run in runs[label]]}
        before, after = (entry[label]['median_stable_mib'] for label in ('baseline', 'optimized'))
        entry['change_percent'] = (after - before) / before * 100
        comparison[stage] = entry
        print(stage, f'{before:.1f} → {after:.1f} MiB ({entry["change_percent"]:+.1f}%)')
    (output / 'memory-comparison.json').write_text(json.dumps({
        'command': '.venv/bin/python scripts/summarize_dsr_memory.py', 'cwd': str(root),
        'metric': 'Process-tree macOS physical footprint; first 5 seconds excluded for stable median',
        'limits': 'Six short native runs; ambient macOS pressure/cache and decoder transitions remain variable',
        'growth_method': 'Median last 5 samples minus median first 5 samples per phase',
        'comparison': comparison, 'runs': runs, 'exit_status': 0,
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

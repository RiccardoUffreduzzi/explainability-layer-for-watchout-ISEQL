<script lang="ts">
  import { untrack } from 'svelte';
  import { api } from '$lib/api';
  import type {
    AnalysisRecord,
    ObjectMemoryEntry,
    ObjectMemoryResponse,
    ObjectMemoryStats,
    Unit,
  } from '$lib/types';
  import Button from '$lib/components/ui/button.svelte';
  import Input from '$lib/components/ui/input.svelte';
  import Label from '$lib/components/ui/label.svelte';
  import Field from '$lib/components/ui/field.svelte';
  import Badge from '$lib/components/ui/badge.svelte';
  import UnitToggle from '$lib/components/unit-toggle.svelte';
  import { DatabaseZap, Search } from 'lucide-svelte';

  const PAGE_SIZE = 100;

  type Props = {
    analysisId: string;
    fps?: number;
    unit?: Unit;
    onUnitChange?: (unit: Unit) => void;
  };
  let { analysisId, fps = 0, unit: controlledUnit, onUnitChange }: Props = $props();

  let stats = $state<ObjectMemoryStats | null>(null);
  let items = $state<ObjectMemoryEntry[]>([]);
  let total = $state(0);
  let error = $state<string | null>(null);
  let loading = $state(false);
  let loadingMore = $state(false);

  let classFilter = $state('');
  let classIdFilter = $state<number | null>(null);
  let descriptionFilter = $state('');
  let rangeMin = $state<number | null>(null);
  let rangeMax = $state<number | null>(null);
  let localUnit = $state<Unit>('frames');
  let unit = $derived(controlledUnit ?? localUnit);
  let lastUnit = $state<Unit>('frames');
  let fetchedFps = $state(0);

  let scrollEl = $state<HTMLDivElement | null>(null);
  let sentinelEl = $state<HTMLDivElement | null>(null);

  let hasMore = $derived(items.length < total);
  let effectiveFps = $derived(fps > 0 ? fps : fetchedFps);

  const CLASS_COLORS: Record<string, string> = {
    person: 'bg-info/10 text-info border-info/30',
    vehicle: 'bg-warning/10 text-warning border-warning/30',
    object: 'bg-success/10 text-success border-success/30',
  };

  function buildQuery(off: number): string {
    const parts: string[] = [`limit=${PAGE_SIZE}`, `offset=${off}`];
    if (classFilter) parts.push(`class_name=${encodeURIComponent(classFilter)}`);
    if (classIdFilter != null && !Number.isNaN(classIdFilter)) parts.push(`class_id=${classIdFilter}`);
    if (descriptionFilter) parts.push(`description=${encodeURIComponent(descriptionFilter)}`);
    if (rangeMin != null && !Number.isNaN(rangeMin)) parts.push(`frame_min=${toFrame(rangeMin)}`);
    if (rangeMax != null && !Number.isNaN(rangeMax)) parts.push(`frame_max=${toFrame(rangeMax)}`);
    return parts.join('&');
  }

  function fetchObjects(off: number) {
    return api.get<ObjectMemoryResponse>(`/api/analysis/${analysisId}/memory/objects?${buildQuery(off)}`);
  }

  async function fetchFrameRate(): Promise<number> {
    try {
      const records = await api.get<AnalysisRecord[]>('/api/analysis/list');
      return records.find((record) => record.id === analysisId)?.frame_rate ?? 0;
    } catch {
      return 0;
    }
  }

  async function load(): Promise<void> {
    if (!analysisId) return;
    loading = true;
    error = null;
    try {
      if (effectiveFps <= 0) fetchedFps = await fetchFrameRate();
      const [s, m] = await Promise.all([
        api.get<ObjectMemoryStats>(`/api/analysis/${analysisId}/memory/stats`),
        fetchObjects(0),
      ]);
      stats = s;
      items = m.items;
      total = m.total;
    } catch (e) {
      error = (e as Error).message;
      stats = null;
      items = [];
      total = 0;
    } finally {
      loading = false;
    }
  }

  async function loadMore(): Promise<void> {
    if (loading || loadingMore || !hasMore) return;
    loadingMore = true;
    error = null;
    try {
      const m = await fetchObjects(items.length);
      items = [...items, ...m.items];
      total = m.total;
    } catch (e) {
      error = (e as Error).message;
    } finally {
      loadingMore = false;
    }
  }

  function toFrame(value: number): number {
    return Math.round(unit === 'seconds' && effectiveFps > 0 ? value * effectiveFps : value);
  }

  function formatTime(frame: number): string {
    if (effectiveFps <= 0) return String(frame);
    const totalMilliseconds = Math.max(0, Math.round((frame / effectiveFps) * 1000));
    const milliseconds = totalMilliseconds % 1000;
    const totalSeconds = Math.floor(totalMilliseconds / 1000);
    const secs = totalSeconds % 60;
    const mins = Math.floor(totalSeconds / 60) % 60;
    const hours = Math.floor(totalSeconds / 3600);
    return `${String(hours).padStart(2, '0')}:${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}.${String(milliseconds).padStart(3, '0')}`;
  }

  function setUnit(next: Unit) {
    if (next === unit || (next === 'seconds' && effectiveFps <= 0)) return;
    if (controlledUnit !== undefined) onUnitChange?.(next);
    else localUnit = next;
  }

  function resetFilters() {
    classFilter = '';
    classIdFilter = null;
    descriptionFilter = '';
    rangeMin = null;
    rangeMax = null;
  }

  $effect(() => {
    const next = unit;
    if (next === lastUnit) return;
    lastUnit = next;
    untrack(() => {
      if (effectiveFps <= 0) return;
      const convert = (value: number | null) => {
        if (value == null) return null;
        return next === 'seconds'
          ? Number((value / effectiveFps).toFixed(3))
          : Math.round(value * effectiveFps);
      };
      rangeMin = convert(rangeMin);
      rangeMax = convert(rangeMax);
      if (rangeMin != null || rangeMax != null) load();
    });
  });

  $effect(() => {
    if (analysisId) load();
  });

  $effect(() => {
    if (!scrollEl || !sentinelEl) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) loadMore();
      },
      { root: scrollEl, rootMargin: '200px 0px' },
    );
    observer.observe(sentinelEl);
    return () => observer.disconnect();
  });
</script>

<div class="flex min-h-0 flex-1 flex-col gap-3">
  {#if error}
    <div class="rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">{error}</div>
  {/if}

  {#if !error && analysisId}
    <section class="flex flex-wrap items-center gap-2">
      <Badge variant="secondary"><DatabaseZap class="size-3 mr-1" />{stats?.total ?? 0} stored object detections</Badge>
      {#if stats?.frame_min != null}
        <Badge variant="secondary">
          {unit === 'frames'
            ? `frames ${stats.frame_min}–${stats.frame_max}`
            : `time ${formatTime(stats.frame_min)}–${formatTime(stats.frame_max ?? stats.frame_min)}`}
        </Badge>
      {/if}
      {#if stats?.per_class}
        {#each Object.entries(stats.per_class) as [cls, n] (cls)}
          <button
            type="button"
            class="inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs {CLASS_COLORS[cls] || 'bg-muted text-muted-foreground'}"
            class:border-primary={classFilter === cls}
            class:ring-2={classFilter === cls}
            onclick={() => { classFilter = classFilter === cls ? '' : cls; load(); }}>
            {cls} · {n}
          </button>
        {/each}
      {/if}
      {#if effectiveFps > 0}
        <div class="ml-auto flex items-center gap-1.5">
          <span class="text-xs text-muted-foreground">Unit</span>
          <UnitToggle {unit} onUnitChange={setUnit} secondsLabel="Time" />
        </div>
      {/if}
    </section>

    <section class="flex flex-wrap items-end gap-3 rounded-lg border p-3">
      <Field>
        <Label>Class</Label>
        <Input type="text" value={classFilter} placeholder="person / vehicle / object"
          oninput={(e) => (classFilter = (e.currentTarget as HTMLInputElement).value)} />
      </Field>
      <Field>
        <Label>ClassID</Label>
        <Input type="number" min="0" value={classIdFilter ?? ''}
          oninput={(e) => (classIdFilter = (e.currentTarget as HTMLInputElement).value === '' ? null : Number((e.currentTarget as HTMLInputElement).value))} />
      </Field>
      <Field>
        <Label>Description</Label>
        <Input type="text" value={descriptionFilter} placeholder="e.g. blue jacket"
          oninput={(e) => (descriptionFilter = (e.currentTarget as HTMLInputElement).value)} />
      </Field>
      <Field>
        <Label>{unit === 'frames' ? 'Frame min' : 'Time min (s)'}</Label>
        <Input type="number" min="0" step={unit === 'frames' ? 1 : 0.001} value={rangeMin ?? ''}
          oninput={(e) => (rangeMin = (e.currentTarget as HTMLInputElement).value === '' ? null : Number((e.currentTarget as HTMLInputElement).value))} />
      </Field>
      <Field>
        <Label>{unit === 'frames' ? 'Frame max' : 'Time max (s)'}</Label>
        <Input type="number" min="0" step={unit === 'frames' ? 1 : 0.001} value={rangeMax ?? ''}
          oninput={(e) => (rangeMax = (e.currentTarget as HTMLInputElement).value === '' ? null : Number((e.currentTarget as HTMLInputElement).value))} />
      </Field>
      <Button variant="secondary" size="sm" onclick={load}><Search class="size-3 mr-1" /> Apply</Button>
      {#if classFilter || classIdFilter != null || descriptionFilter || rangeMin != null || rangeMax != null}
        <Button variant="ghost" size="sm" onclick={() => { resetFilters(); load(); }}>Reset</Button>
      {/if}
    </section>

    <section class="flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border">
      <div class="min-h-0 flex-1 overflow-auto" bind:this={scrollEl}>
        <table class="w-full text-left text-xs">
          <thead class="sticky top-0 bg-card text-muted-foreground">
            <tr class="border-b">
              <th class="px-3 py-2 font-medium">{unit === 'frames' ? 'Frame' : 'Time'}</th>
              <th class="px-3 py-2 font-medium">ClassID</th>
              <th class="px-3 py-2 font-medium">Class</th>
              <th class="px-3 py-2 font-medium">Blocks</th>
              <th class="px-3 py-2 font-medium">Description</th>
              <th class="px-3 py-2 font-medium">Document</th>
            </tr>
          </thead>
          <tbody>
            {#each items as entry}
              <tr class="border-b last:border-0 hover:bg-muted/40">
                <td class="px-3 py-1.5 font-mono tabular-nums" title={`Frame ${entry.frame}`}>
                  {unit === 'frames' ? entry.frame : formatTime(entry.frame)}
                </td>
                <td class="px-3 py-1.5 font-mono tabular-nums">{entry.id}</td>
                <td class="px-3 py-1.5">
                  <span class="rounded-md border px-1.5 py-px text-[10px] font-medium {CLASS_COLORS[entry.class] || 'bg-muted text-muted-foreground'}">
                    {entry.class}
                  </span>
                </td>
                <td class="px-3 py-1.5 font-mono">{entry.blocks.length ? entry.blocks.join(',') : '-'}</td>
                <td class="px-3 py-1.5 max-w-xs truncate" title={entry.description}>{entry.description || '-'}</td>
                <td class="px-3 py-1.5 max-w-sm truncate" title={entry.document}>{entry.document}</td>
              </tr>
            {:else}
              <tr>
                <td colspan="6" class="px-3 py-6 text-center text-muted-foreground">
                  {loading ? 'Loading…' : 'No stored objects for this analysis.'}
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
        <div bind:this={sentinelEl} class="h-px" aria-hidden="true"></div>
      </div>
    </section>

    <footer class="flex items-center justify-between text-xs text-muted-foreground">
      <span>{items.length} of {total} loaded</span>
      {#if hasMore}
        <Button variant="outline" size="sm" disabled={loadingMore} onclick={loadMore}>
          {loadingMore ? 'Loading…' : 'Load more'}
        </Button>
      {/if}
    </footer>
  {/if}
</div>

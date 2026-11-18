<script lang="ts">
  import Card from '$lib/components/ui/card.svelte';
  import CardHeader from '$lib/components/ui/card-header.svelte';
  import CardTitle from '$lib/components/ui/card-title.svelte';
  import CardContent from '$lib/components/ui/card-content.svelte';
  import Input from '$lib/components/ui/input.svelte';
  import CountBadge from '$lib/components/ui/count-badge.svelte';
  import UnitToggle from '$lib/components/unit-toggle.svelte';
  import * as Popover from '$lib/components/ui/popover/index.js';
  import { DatabaseZap, Hand, ImageOff, Info, LayoutGrid, List, MousePointerClick } from 'lucide-svelte';
  import { cn } from '$lib/utils';
  import type { DetectionResult, Unit } from '$lib/types';

  type Props = {
    result: DetectionResult | null;
    running?: boolean;
    error?: string | null;
    unit: Unit;
    analysisId: string | null;
    fps: number;
    onUnitChange: (u: Unit) => void;
    onMemory?: () => void;
  };
  let {
    result,
    running = false,
    error = null,
    unit,
    analysisId = null,
    fps = 0,
    onUnitChange,
    onMemory,
  }: Props = $props();

  const cols = $derived(
    result && result.rows.length > 0
      ? Object.keys(result.rows[0])
          .filter((k) => !k.startsWith('__p'))
          .filter((k) =>
            unit === 'seconds'
              ? !k.endsWith('.sf') && !k.endsWith('.ef')
              : !k.endsWith('.st') && !k.endsWith('.et')
          )
          .map((k) => ({ label: k.replace(/^M(\d+)_/, 'M$1.'), key: k }))
      : []
  );

  let search = $state('');
  let showClickHint = $state(true);
  let resultView = $state<'list' | 'gallery'>('gallery');
  let failedThumbnails = $state<Record<string, boolean>>({});

  const filteredRows = $derived(
    (result?.rows ?? []).map((row, i) => ({ row, i })).filter(({ row }) => {
      const q = search.trim().toLowerCase();
      if (!q) return true;
      return Object.values(row).some((v) => String(v ?? '').toLowerCase().includes(q));
    })
  );

  function parseTimeValue(raw: unknown): number | null {
    if (typeof raw === 'number') return Number.isFinite(raw) ? raw : null;
    if (typeof raw !== 'string') return null;
    const value = raw.trim();
    const numeric = Number(value);
    if (Number.isFinite(numeric)) return numeric;
    const match = value.match(/^(\d+):(\d{2}):(\d{2})(?:\.(\d{1,3}))?$/);
    if (!match) return null;
    const [, hours, minutes, seconds, fraction = ''] = match;
    return (
      Number(hours) * 3600 +
      Number(minutes) * 60 +
      Number(seconds) +
      Number(fraction.padEnd(3, '0')) / 1000
    );
  }

  // --- video + timeline ---
  let videoEl = $state<HTMLVideoElement | null>(null);
  let duration = $state(0);
  let selectedKey = $state<string | null>(null);
  let stopAt = $state<number | null>(null);
  let seekingToEvent = $state(false);

  const intervals = $derived.by(() => {
    const out: {
      key: string;
      event: string;
      startSec: number;
      endSec: number;
      startFrame: number | null;
      endFrame: number | null;
    }[] = [];
    (result?.rows ?? []).forEach((row, i) => {
      let startSec: number | null = null;
      let endSec: number | null = null;
      let startFrame: number | null = null;
      let endFrame: number | null = null;
      for (const k of Object.keys(row)) {
        const raw = row[k];
        if (raw === null || raw === undefined || raw === '') continue;
        if (k.endsWith('.st') || k.endsWith('_st') || k === 'st') {
          const value = parseTimeValue(raw);
          if (value !== null) startSec = startSec === null ? value : Math.min(startSec, value);
          continue;
        }
        if (k.endsWith('.et') || k.endsWith('_et') || k === 'et') {
          const value = parseTimeValue(raw);
          if (value !== null) endSec = endSec === null ? value : Math.max(endSec, value);
          continue;
        }
        const v = Number(raw);
        if (!Number.isFinite(v)) continue;
        if (k.endsWith('.sf') || k.endsWith('_sf') || k === 'sf') {
          startFrame = startFrame === null ? v : Math.min(startFrame, v);
        } else if (k.endsWith('.ef') || k.endsWith('_ef') || k === 'ef') {
          endFrame = endFrame === null ? v : Math.max(endFrame, v);
        }
      }
      if (startSec === null && startFrame !== null && fps > 0) startSec = startFrame / fps;
      if (endSec === null && endFrame !== null && fps > 0) endSec = endFrame / fps;
      if (startSec === null || endSec === null) return;
      out.push({
        key: `row-${i}`,
        event: String(row['Event'] ?? 'event'),
        startSec,
        endSec,
        startFrame,
        endFrame,
      });
    });
    return out;
  });

  const cardColumns = $derived(
    cols.filter(
      (c) =>
        c.key !== 'Event' &&
        !/^M\d+_/.test(c.key) &&
        !/(^|[._])(st|et|sf|ef)$/.test(c.key) &&
        !/(^|[._])arg\d+$/.test(c.key) &&
        !c.key.startsWith('__p')
    )
  );

  const galleryRows = $derived(
    filteredRows.map(({ row, i }) => {
      const key = `row-${i}`;
      const interval = intervals.find((item) => item.key === key) ?? null;
      let previewFrame: number | null = null;
      if (interval) {
        if (interval.startFrame !== null && interval.endFrame !== null) {
          previewFrame = Math.floor((interval.startFrame + interval.endFrame) / 2);
        } else if (fps > 0) {
          previewFrame = Math.floor(((interval.startSec + interval.endSec) / 2) * fps);
        }
      }
      return {
        row,
        i,
        key,
        previewFrame,
        thumbKey: `${analysisId ?? 'none'}-${i}`,
        interval,
      };
    })
  );

  function markThumbnailFailed(key: string) {
    failedThumbnails = { ...failedThumbnails, [key]: true };
  }

  function displayValue(value: unknown): string {
    if (value === null || value === undefined) return '';
    return typeof value === 'object' ? JSON.stringify(value) : String(value);
  }

  function formatEventTime(seconds: number) {
    const totalMilliseconds = Math.max(0, Math.round(seconds * 1000));
    const milliseconds = totalMilliseconds % 1000;
    const totalSeconds = Math.floor(totalMilliseconds / 1000);
    const secs = totalSeconds % 60;
    const mins = Math.floor(totalSeconds / 60) % 60;
    const hours = Math.floor(totalSeconds / 3600);
    return `${String(hours).padStart(2, '0')}:${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}.${String(milliseconds).padStart(3, '0')}`;
  }

  function formatIntervalRange(interval: {
    startSec: number;
    endSec: number;
    startFrame: number | null;
    endFrame: number | null;
  }) {
    if (unit === 'frames') {
      const startFrame =
        interval.startFrame ?? (fps > 0 ? Math.round(interval.startSec * fps) : null);
      const endFrame =
        interval.endFrame ?? (fps > 0 ? Math.round(interval.endSec * fps) : null);
      if (startFrame !== null && endFrame !== null) {
        return `${startFrame} – ${endFrame} frames`;
      }
    }
    return `${formatEventTime(interval.startSec)} – ${formatEventTime(interval.endSec)}`;
  }

  function seekToEvent(startSec: number, endSec: number) {
    if (!videoEl) return;
    const videoEnd = Number.isFinite(videoEl.duration) ? videoEl.duration : Infinity;
    const target = Math.min(Math.max(0, startSec), videoEnd);
    const previewEnd = endSec - startSec <= 0.1 ? startSec + 1 : endSec;
    stopAt = Math.min(Math.max(target, previewEnd), videoEnd);
    videoEl.pause();
    if (Math.abs(videoEl.currentTime - target) < 0.01) {
      seekingToEvent = false;
      void videoEl.play().catch(() => {});
      return;
    }
    seekingToEvent = true;
    videoEl.currentTime = target;
  }

  function seekRow(i: number) {
    const iv = intervals.find((x) => x.key === `row-${i}`);
    if (!iv) return;
    selectedKey = iv.key;
    seekToEvent(iv.startSec, iv.endSec);
  }

  function onTimeUpdate() {
    if (!videoEl) return;
    if (videoEl.duration && Number.isFinite(videoEl.duration)) duration = videoEl.duration;
    if (seekingToEvent) return;
    if (stopAt != null && videoEl.currentTime >= stopAt) {
      videoEl.pause();
      stopAt = null;
    }
  }

  function onSeeked() {
    if (!videoEl || !seekingToEvent) return;
    seekingToEvent = false;
    void videoEl.play().catch(() => {});
  }

  function onLoadedMetadata() {
    if (videoEl && Number.isFinite(videoEl.duration)) duration = videoEl.duration;
  }
</script>

<Card class="flex min-h-0 flex-1 flex-col">
  <CardHeader class="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center">
    <div class="flex flex-wrap items-center justify-between gap-2 sm:contents">
      <CardTitle class="flex shrink-0 items-center gap-1.5 sm:order-1">
        Results
        {#if result}<CountBadge filtered={filteredRows.length} total={result.rows.length} filtering={search.trim() !== ''} />{/if}
      </CardTitle>
      <div class="flex shrink-0 flex-wrap items-center gap-2 sm:order-4">
        <div class="flex items-center gap-1.5">
          <span class="text-xs text-muted-foreground">View</span>
          <div
            class="inline-flex h-7 items-center rounded-lg border border-border bg-muted/30 p-0.5"
            role="group"
            aria-label="Results view"
          >
            <button
              type="button"
              title="Gallery"
              aria-label="Gallery"
              aria-pressed={resultView === 'gallery'}
              class={cn(
                'inline-flex h-full w-7 items-center justify-center rounded-md transition-colors',
                resultView === 'gallery'
                  ? 'bg-card text-foreground shadow-sm'
                  : 'text-muted-foreground hover:text-foreground'
              )}
              onclick={() => (resultView = 'gallery')}
            >
              <LayoutGrid class="size-3.5" />
            </button>
            <button
              type="button"
              title="List"
              aria-label="List"
              aria-pressed={resultView === 'list'}
              class={cn(
                'inline-flex h-full w-7 items-center justify-center rounded-md transition-colors',
                resultView === 'list'
                  ? 'bg-card text-foreground shadow-sm'
                  : 'text-muted-foreground hover:text-foreground'
              )}
              onclick={() => (resultView = 'list')}
            >
              <List class="size-3.5" />
            </button>
          </div>
        </div>
        <div class="flex items-center gap-1.5">
          <span class="text-xs text-muted-foreground">Unit</span>
          <UnitToggle {unit} {onUnitChange} secondsLabel="Time" />
        </div>
      </div>
    </div>
    <div class="flex flex-col gap-2 sm:contents">
      <Input class="h-7 w-full min-w-0 font-mono text-xs sm:order-2 sm:min-w-[18rem] sm:flex-1" placeholder="Search results…" value={search} oninput={(e) => (search = (e.currentTarget as HTMLInputElement).value)} />
      {#if onMemory}
        <button
          type="button"
          title="View object memory"
          class="inline-flex h-7 shrink-0 self-start items-center gap-1.5 rounded-lg border border-input bg-card px-2.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground sm:order-3 sm:self-auto"
          onclick={onMemory}
        >
          <DatabaseZap class="size-3.5" /> Object memory
        </button>
      {/if}
    </div>
  </CardHeader>

  {#if showClickHint && result && result.rows.length > 0}
    <div class="flex shrink-0 items-center gap-1.5 border-b border-border/60 bg-muted/30 px-5 py-1 text-[10px] leading-tight text-muted-foreground">
      <MousePointerClick class="size-3 shrink-0" />
      <Hand class="size-3 shrink-0" />
      <span>Click or tap a result to play the video from that event's start to end</span>
      <button
        type="button"
        class="ml-auto shrink-0 rounded-md px-0.5 text-muted-foreground hover:text-foreground"
        title="Dismiss"
        aria-label="Dismiss row click hint"
        onclick={() => (showClickHint = false)}
      >✕</button>
    </div>
  {/if}

  {#if analysisId && result && result.rows.length > 0}
    <div class="shrink-0 border-b border-border/50 px-5 pb-3">
      <!-- svelte-ignore a11y_media_has_caption -->
      <video
        bind:this={videoEl}
        src={`/api/analysis/${analysisId}/video`}
        controls
        preload="metadata"
        class="max-h-[35dvh] w-full rounded-lg bg-black"
        ontimeupdate={onTimeUpdate}
        onseeked={onSeeked}
        onloadedmetadata={onLoadedMetadata}
      ></video>
    </div>
  {/if}

  <CardContent class="min-h-0 flex-1 overflow-y-auto">
    {#if running}
      <p class="text-sm text-muted-foreground">Running detection...</p>
    {:else if error}
      <p class="text-sm text-destructive">{error}</p>
    {:else if !result}
      <p class="text-sm text-muted-foreground">
        Start or load an analysis to see results.
      </p>
    {:else if result.rows.length === 0}
      <p class="text-sm text-muted-foreground">No events detected.</p>
    {:else if filteredRows.length === 0}
      <p class="text-sm text-muted-foreground">No results match your search.</p>
    {:else if resultView === 'list'}
      <div class="overflow-x-auto">
        <table class={cn('w-full text-left text-sm')}>
          <thead class="border-b border-border text-xs uppercase text-muted-foreground">
            <tr>
              {#each cols as c (c.key)}
                <th class="px-2 py-2 font-medium">{c.label}</th>
              {/each}
            </tr>
          </thead>
          <tbody>
            {#each filteredRows as { row, i } (i)}
              <tr
                class={cn(
                  'cursor-pointer border-b border-border/50 transition-colors last:border-0',
                  selectedKey === `row-${i}` ? 'bg-primary/10' : 'hover:bg-muted/40'
                )}
                onclick={() => seekRow(i)}
              >
                {#each cols as c (c.key)}
                  <td class="px-2 py-1.5">
                    {#if typeof row[c.key] === 'object' && row[c.key] !== null}
                      <code class="text-xs">{JSON.stringify(row[c.key])}</code>
                    {:else}
                      <span>{row[c.key]}</span>
                    {/if}
                  </td>
                {/each}
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {:else}
      <div class="grid grid-cols-1 gap-3 pb-1 pt-3 sm:grid-cols-2 xl:grid-cols-3">
        {#each galleryRows as item (item.key)}
          <div class="relative min-w-0">
            <button
              type="button"
              class={cn(
                'group flex w-full min-w-0 flex-col overflow-hidden rounded-xl border bg-card text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                selectedKey === item.key
                  ? 'border-primary/60 ring-1 ring-primary/30'
                  : 'border-border hover:border-primary/40 hover:bg-muted/20'
              )}
              onclick={() => seekRow(item.i)}
            >
              {#if item.previewFrame !== null && !failedThumbnails[item.thumbKey]}
                <img
                  src={`/api/analysis/${analysisId}/thumbnail?frame=${item.previewFrame}`}
                  alt=""
                  loading="lazy"
                  class="aspect-video w-full bg-black object-cover"
                  onerror={() => markThumbnailFailed(item.thumbKey)}
                />
              {:else}
                <span class="flex aspect-video w-full items-center justify-center bg-muted/40 text-muted-foreground">
                  <ImageOff class="size-5" />
                </span>
              {/if}
              <span class="flex flex-1 flex-col gap-2 p-3">
                <span class="flex flex-col gap-0.5">
                  <span class="truncate text-sm font-medium">{String(item.row['Event'] ?? 'Result')}</span>
                  {#if item.interval}
                    <span class="font-mono text-[10px] text-muted-foreground">
                      {formatIntervalRange(item.interval)}
                    </span>
                  {/if}
                </span>
                {#if cardColumns.length > 0}
                  <span class="grid grid-cols-2 gap-x-3 gap-y-1.5 border-t border-border/60 pt-2 text-[11px]">
                    {#each cardColumns as c (c.key)}
                      <span class="min-w-0">
                        <span class="block truncate text-muted-foreground">{c.label}</span>
                        <span class="block truncate font-mono text-foreground">
                          {displayValue(item.row[c.key])}
                        </span>
                      </span>
                    {/each}
                  </span>
                {/if}
              </span>
            </button>

            <Popover.Root>
              <Popover.Trigger
                class="absolute right-2 top-2 z-20 inline-flex size-7 items-center justify-center rounded-md border border-border/60 bg-background/85 text-muted-foreground shadow-sm backdrop-blur transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                title="Show result metadata"
                aria-label="Show result metadata"
              >
                <Info class="size-3.5" />
              </Popover.Trigger>
              <Popover.Content class="w-[22rem] max-w-[calc(100vw-2rem)] p-3" align="end">
                <div class="max-h-64 space-y-1.5 overflow-y-auto pr-1">
                  {#each cols as column (column.key)}
                    <div class="grid grid-cols-[minmax(0,1fr)_minmax(0,1.35fr)] items-baseline gap-2 text-xs">
                      <span class="truncate text-muted-foreground" title={column.key}>{column.label}</span>
                      <span class="truncate text-right font-mono text-foreground" title={displayValue(item.row[column.key])}>{displayValue(item.row[column.key])}</span>
                    </div>
                  {/each}
                </div>
              </Popover.Content>
            </Popover.Root>
          </div>
        {/each}
      </div>
    {/if}
  </CardContent>
</Card>

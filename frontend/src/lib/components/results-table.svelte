<script lang="ts">
  import Card from '$lib/components/ui/card.svelte';
  import CardHeader from '$lib/components/ui/card-header.svelte';
  import CardTitle from '$lib/components/ui/card-title.svelte';
  import CardContent from '$lib/components/ui/card-content.svelte';
  import Input from '$lib/components/ui/input.svelte';
  import CountBadge from '$lib/components/ui/count-badge.svelte';
  import UnitToggle from '$lib/components/unit-toggle.svelte';
  import { DatabaseZap, Images, List, MousePointerClick, Hand } from 'lucide-svelte';
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
  let highlightsView = $state<'gallery' | 'list'>('gallery');

  const filteredRows = $derived(
    (result?.rows ?? []).map((row, i) => ({ row, i })).filter(({ row }) => {
      const q = search.trim().toLowerCase();
      if (!q) return true;
      return Object.values(row).some((v) => String(v ?? '').toLowerCase().includes(q));
    })
  );

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
        const v = Number(raw);
        if (!Number.isFinite(v)) continue;
        if (k.endsWith('.st') || k.endsWith('_st') || k === 'st') {
          startSec = startSec === null ? v : Math.min(startSec, v);
        } else if (k.endsWith('.et') || k.endsWith('_et') || k === 'et') {
          endSec = endSec === null ? v : Math.max(endSec, v);
        } else if (k.endsWith('.sf') || k.endsWith('_sf') || k === 'sf') {
          startFrame = startFrame === null ? v : Math.min(startFrame, v);
          if (fps > 0) {
            const s = v / fps;
            startSec = startSec === null ? s : Math.min(startSec, s);
          }
        } else if (k.endsWith('.ef') || k.endsWith('_ef') || k === 'ef') {
          endFrame = endFrame === null ? v : Math.max(endFrame, v);
          if (fps > 0) {
            const e = v / fps;
            endSec = endSec === null ? e : Math.max(endSec, e);
          }
        }
      }
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

  const highlights = $derived(
    intervals
      .filter((interval) =>
        interval.startFrame !== null &&
        interval.endFrame !== null &&
        interval.startFrame >= 0 &&
        interval.endFrame >= interval.startFrame
      )
      .map((interval) => ({
        ...interval,
        representativeFrame: Math.floor((interval.startFrame! + interval.endFrame!) / 2),
      }))
  );

  function formatEventTime(seconds: number) {
    const totalCentiseconds = Math.max(0, Math.round(seconds * 100));
    const centiseconds = totalCentiseconds % 100;
    const totalSeconds = Math.floor(totalCentiseconds / 100);
    const secs = totalSeconds % 60;
    const mins = Math.floor(totalSeconds / 60) % 60;
    const hours = Math.floor(totalSeconds / 3600);
    return `${String(hours).padStart(2, '0')}:${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}.${String(centiseconds).padStart(2, '0')}`;
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

  function playHighlight(key: string, startSec: number, endSec: number) {
    selectedKey = key;
    seekToEvent(startSec, endSec);
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
    <div class="flex items-center justify-between gap-2 sm:contents">
      <CardTitle class="flex shrink-0 items-center gap-1.5 sm:order-1">
        Results
        {#if result}<CountBadge filtered={filteredRows.length} total={result.rows.length} filtering={search.trim() !== ''} />{/if}
      </CardTitle>
      <div class="flex shrink-0 items-center gap-1.5 sm:order-4">
        <span class="text-xs text-muted-foreground">Unit</span>
        <UnitToggle {unit} {onUnitChange} secondsLabel="Time" />
      </div>
    </div>
    <div class="flex flex-col gap-2 sm:contents">
      <Input class="h-7 w-full min-w-0 font-mono text-xs sm:order-2 sm:flex-1" placeholder="Search results…" value={search} oninput={(e) => (search = (e.currentTarget as HTMLInputElement).value)} />
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
    <div class="flex shrink-0 items-center gap-1.5 border-b border-border/60 bg-muted/30 px-4 py-1 text-[10px] leading-tight text-muted-foreground">
      <MousePointerClick class="size-3 shrink-0" />
      <Hand class="size-3 shrink-0" />
      <span>Click or tap a row to play the video from that event's start to end</span>
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
    <div class="shrink-0 border-b border-border/50 px-4 pb-3">
      <!-- svelte-ignore a11y_media_has_caption -->
      <video
        bind:this={videoEl}
        src={`/api/analysis/${analysisId}/video`}
        controls
        preload="metadata"
        class="max-h-[30dvh] w-full rounded-lg bg-black"
        ontimeupdate={onTimeUpdate}
        onseeked={onSeeked}
        onloadedmetadata={onLoadedMetadata}
      ></video>
    </div>
    {#if highlights.length > 0}
      <section class="shrink-0 border-b border-border/50 px-4 py-3" aria-label="Highlights">
        <div class="mb-2 flex flex-wrap items-center justify-between gap-2">
          <h3 class="text-sm font-medium">Highlights</h3>
          <div class="inline-flex items-center rounded-md border border-input bg-muted/30 p-0.5" role="group" aria-label="Highlights view">
            <button
              type="button"
              class={cn(
                'inline-flex h-6 items-center gap-1 rounded px-2 text-xs font-medium transition-colors',
                highlightsView === 'gallery' ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'
              )}
              aria-pressed={highlightsView === 'gallery'}
              onclick={() => (highlightsView = 'gallery')}
            >
              <Images class="size-3.5" /> Gallery
            </button>
            <button
              type="button"
              class={cn(
                'inline-flex h-6 items-center gap-1 rounded px-2 text-xs font-medium transition-colors',
                highlightsView === 'list' ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'
              )}
              aria-pressed={highlightsView === 'list'}
              onclick={() => (highlightsView = 'list')}
            >
              <List class="size-3.5" /> List
            </button>
          </div>
        </div>
        {#if highlightsView === 'gallery'}
          <div class="flex flex-nowrap gap-3 overflow-x-auto pb-1">
            {#each highlights as highlight (highlight.key)}
              <button
                type="button"
                class="group w-32 shrink-0 overflow-hidden rounded-md border border-border bg-muted/20 text-left transition-colors hover:border-primary hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:w-40"
                title={`Play ${highlight.event} from ${formatEventTime(highlight.startSec)} to ${formatEventTime(highlight.endSec)}`}
                onclick={() => playHighlight(highlight.key, highlight.startSec, highlight.endSec)}
              >
                <img
                  src={`/api/analysis/${analysisId}/thumbnail?frame=${highlight.representativeFrame}`}
                  alt={`${highlight.event} at ${formatEventTime(highlight.startSec)}`}
                  loading="lazy"
                  class="aspect-video w-full bg-black object-cover"
                />
                <span class="block truncate px-2 pt-1.5 text-xs font-medium">{highlight.event}</span>
                <span class="block px-2 pb-2 text-[11px] text-muted-foreground">{formatEventTime(highlight.startSec)}</span>
              </button>
            {/each}
          </div>
        {:else}
          <div class="space-y-2">
            {#each highlights as highlight (highlight.key)}
              <button
                type="button"
                class="group flex w-full min-w-0 items-center gap-3 rounded-md border border-border bg-muted/20 p-2 text-left transition-colors hover:border-primary hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                title={`Play ${highlight.event} from ${formatEventTime(highlight.startSec)} to ${formatEventTime(highlight.endSec)}`}
                onclick={() => playHighlight(highlight.key, highlight.startSec, highlight.endSec)}
              >
                <img
                  src={`/api/analysis/${analysisId}/thumbnail?frame=${highlight.representativeFrame}`}
                  alt={`${highlight.event} at ${formatEventTime(highlight.startSec)}`}
                  loading="lazy"
                  class="h-14 w-20 shrink-0 rounded bg-black object-cover sm:h-16 sm:w-24"
                />
                <span class="min-w-0">
                  <span class="block truncate text-sm font-medium">{highlight.event}</span>
                  <span class="block text-xs text-muted-foreground">{formatEventTime(highlight.startSec)} – {formatEventTime(highlight.endSec)}</span>
                </span>
              </button>
            {/each}
          </div>
        {/if}
      </section>
    {/if}
  {/if}

  <CardContent class="min-h-0 flex-none overflow-visible">
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
    {:else}
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
    {/if}
  </CardContent>
</Card>

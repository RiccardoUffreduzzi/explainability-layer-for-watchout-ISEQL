<script lang="ts">
  import Card from '$lib/components/ui/card.svelte';
  import CardHeader from '$lib/components/ui/card-header.svelte';
  import CardTitle from '$lib/components/ui/card-title.svelte';
  import CardContent from '$lib/components/ui/card-content.svelte';
  import Input from '$lib/components/ui/input.svelte';
  import CountBadge from '$lib/components/ui/count-badge.svelte';
  import UnitToggle from '$lib/components/unit-toggle.svelte';
  import { DatabaseZap, MousePointerClick, Hand } from 'lucide-svelte';
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

  const intervals = $derived.by(() => {
    const out: { key: string; event: string; startSec: number; endSec: number }[] = [];
    (result?.rows ?? []).forEach((row, i) => {
      let startSec: number | null = null;
      let endSec: number | null = null;
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
          if (fps > 0) {
            const s = v / fps;
            startSec = startSec === null ? s : Math.min(startSec, s);
          }
        } else if (k.endsWith('.ef') || k.endsWith('_ef') || k === 'ef') {
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
      });
    });
    return out;
  });

  function seekToEvent(startSec: number, endSec: number) {
    if (!videoEl) return;
    videoEl.currentTime = Math.max(0, startSec);
    stopAt = endSec;
    void videoEl.play().catch(() => {});
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
    if (stopAt != null && videoEl.currentTime >= stopAt) {
      videoEl.pause();
      stopAt = null;
    }
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
        class="max-h-[35dvh] w-full rounded-lg bg-black"
        ontimeupdate={onTimeUpdate}
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

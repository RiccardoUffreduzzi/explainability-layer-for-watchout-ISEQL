<script lang="ts">
  import { api } from '$lib/api';
  import type { ObjectMemoryEntry, ObjectMemoryResponse, ObjectMemoryStats } from '$lib/types';
  import Button from '$lib/components/ui/button.svelte';
  import Input from '$lib/components/ui/input.svelte';
  import Label from '$lib/components/ui/label.svelte';
  import Field from '$lib/components/ui/field.svelte';
  import Badge from '$lib/components/ui/badge.svelte';
  import { DatabaseZap, Search } from 'lucide-svelte';

  const PAGE_SIZE = 100;

  type Props = {
    analysisId: string;
  };
  let { analysisId }: Props = $props();

  let stats = $state<ObjectMemoryStats | null>(null);
  let items = $state<ObjectMemoryEntry[]>([]);
  let total = $state(0);
  let error = $state<string | null>(null);
  let loading = $state(false);
  let loadingMore = $state(false);

  let classFilter = $state('');
  let classIdFilter = $state<number | null>(null);
  let descriptionFilter = $state('');
  let frameMin = $state<number | null>(null);
  let frameMax = $state<number | null>(null);

  let scrollEl = $state<HTMLDivElement | null>(null);
  let sentinelEl = $state<HTMLDivElement | null>(null);

  let hasMore = $derived(items.length < total);

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
    if (frameMin != null && !Number.isNaN(frameMin)) parts.push(`frame_min=${frameMin}`);
    if (frameMax != null && !Number.isNaN(frameMax)) parts.push(`frame_max=${frameMax}`);
    return parts.join('&');
  }

  function fetchObjects(off: number) {
    return api.get<ObjectMemoryResponse>(`/api/analysis/${analysisId}/memory/objects?${buildQuery(off)}`);
  }

  async function load(): Promise<void> {
    if (!analysisId) return;
    loading = true;
    error = null;
    try {
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

  function resetFilters() {
    classFilter = '';
    classIdFilter = null;
    descriptionFilter = '';
    frameMin = null;
    frameMax = null;
  }

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
        <Badge variant="secondary">frames {stats.frame_min}–{stats.frame_max}</Badge>
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
        <Label>Frame min</Label>
        <Input type="number" min="0" value={frameMin ?? ''}
          oninput={(e) => (frameMin = (e.currentTarget as HTMLInputElement).value === '' ? null : Number((e.currentTarget as HTMLInputElement).value))} />
      </Field>
      <Field>
        <Label>Frame max</Label>
        <Input type="number" min="0" value={frameMax ?? ''}
          oninput={(e) => (frameMax = (e.currentTarget as HTMLInputElement).value === '' ? null : Number((e.currentTarget as HTMLInputElement).value))} />
      </Field>
      <Button variant="secondary" size="sm" onclick={load}><Search class="size-3 mr-1" /> Apply</Button>
      {#if classFilter || classIdFilter != null || descriptionFilter || frameMin != null || frameMax != null}
        <Button variant="ghost" size="sm" onclick={() => { resetFilters(); load(); }}>Reset</Button>
      {/if}
    </section>

    <section class="flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border">
      <div class="min-h-0 flex-1 overflow-auto" bind:this={scrollEl}>
        <table class="w-full text-left text-xs">
          <thead class="sticky top-0 bg-card text-muted-foreground">
            <tr class="border-b">
              <th class="px-3 py-2 font-medium">Frame</th>
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
                <td class="px-3 py-1.5 font-mono tabular-nums">{entry.frame}</td>
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

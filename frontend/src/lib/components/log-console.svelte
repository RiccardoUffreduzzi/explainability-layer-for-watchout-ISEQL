<script lang="ts">
  import { Trash2, Terminal } from 'lucide-svelte';
  import Button from '$lib/components/ui/button.svelte';
  import type { LogEvent } from '$lib/types';

  type Props = { entries: LogEvent[]; onClear: () => void };
  let { entries, onClear }: Props = $props();

  let logContainer: HTMLDivElement | undefined = $state();

  $effect(() => {
    entries;
    if (logContainer) {
      requestAnimationFrame(() => {
        logContainer!.scrollTop = logContainer!.scrollHeight;
      });
    }
  });

  function fmtTs(ts: number): string {
    const d = new Date(ts * 1000);
    return d.toLocaleTimeString('en-GB', { hour12: false });
  }
  const STAGE_PREFIXES: Array<[string, string]> = [
    ['done', 'text-success'],
    ['failed', 'text-destructive'],
    ['vlm', 'text-chart-1'],
    ['interval', 'text-chart-4'],
    ['audio', 'text-chart-3'],
    ['detection', 'text-chart-5'],
  ];

  function stageClass(s: string): string {
    for (const [prefix, cls] of STAGE_PREFIXES) {
      if (s === prefix || s.startsWith(prefix)) return cls;
    }
    return 'text-muted-foreground';
  }
</script>

<div class="flex min-h-0 flex-1 flex-col rounded-xl border border-border bg-card">
  <div class="flex items-center justify-between border-b border-border px-4 py-2">
    <div class="flex items-center gap-2 text-sm font-medium">
      <Terminal class="size-4" />
      <span>Log Console</span>
      <span class="text-xs text-muted-foreground">({entries.length} entries)</span>
    </div>
    <Button size="sm" variant="ghost" onclick={onClear} disabled={entries.length === 0}>
      <Trash2 /> Clear
    </Button>
  </div>
  <div bind:this={logContainer} class="flex-1 overflow-y-auto p-3 font-mono text-xs">
    {#if entries.length === 0}
      <p class="text-muted-foreground">No log entries yet. Start an analysis to see output.</p>
    {:else}
      {#each entries as entry, i (i)}
        <div class="flex gap-2 py-0.5">
          <span class="text-muted-foreground">{fmtTs(entry.ts)}</span>
          <span class={stageClass(entry.stage)}>[{entry.stage}]</span>
          <span class="text-foreground/90 break-all">{entry.message}</span>
        </div>
      {/each}
    {/if}
  </div>
</div>

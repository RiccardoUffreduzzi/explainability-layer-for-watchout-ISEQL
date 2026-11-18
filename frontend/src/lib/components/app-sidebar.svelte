<script lang="ts">
  import { APP_NAME, APP_VERSION, APP_TAGLINE } from '$lib/app';
  import Separator from '$lib/components/ui/separator.svelte';
  import Badge from '$lib/components/ui/badge.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import ThemeToggle from '$lib/components/ui/theme-toggle.svelte';
  import type { BadgeVariant } from '$lib/components/ui/badge';
  import { cn } from '$lib/utils';
  import { Clock, FileVideo, Trash2, Database, DatabaseZap, PanelLeftClose, PanelLeftOpen } from 'lucide-svelte';
  import type { AnalysisRecord } from '$lib/types';

  const STAGE_VARIANT: Record<string, BadgeVariant> = {
    done: 'success',
    failed: 'destructive',
  };
  const CONDITION_COLORS: Record<string, string> = {
    A: 'bg-info/10 text-info border-info/30',
    B: 'bg-warning/10 text-warning border-warning/30',
    C: 'bg-success/10 text-success border-success/30',
  };

  type Props = {
    class?: string;
    currentStage?: string;
    previousAnalyses?: AnalysisRecord[];
    analysisId?: string | null;
    loadAnalysis?: (item: AnalysisRecord) => void;
    onDeleteAnalysis?: (id: string) => void;
    onResetDb?: () => void;
    resetDisabled?: boolean;
    collapsed?: boolean;
    onToggle?: () => void;
  };
  let {
    class: className = '',
    currentStage = 'idle',
    previousAnalyses = [],
    analysisId = null,
    loadAnalysis,
    onDeleteAnalysis,
    onResetDb,
    resetDisabled = false,
    collapsed = false,
    onToggle = () => undefined,
  }: Props = $props();

  function formatDate(iso: string): string {
    if (!iso) return '--';
    const d = new Date(iso);
    return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
  }
</script>

{#if collapsed}
  <aside class="flex h-full w-12 shrink-0 flex-col items-center border-r border-border bg-card py-3 text-card-foreground">
    <button
      class="group flex size-8 items-center justify-center rounded-lg transition-colors hover:bg-accent"
      title="Show sidebar"
      onclick={onToggle}
    >
      <span class="text-xl font-bold tracking-tight group-hover:hidden">
        {APP_NAME.split(' ').map((w) => w[0]).join('').slice(0, 2)}
      </span>
      <PanelLeftOpen class="hidden size-4 text-muted-foreground group-hover:block group-hover:text-foreground" />
    </button>
    <ThemeToggle variant="ghost" class="mt-2" menuSide="right" />
    <div class="mt-auto flex w-full flex-col items-center gap-1.5 px-1" title={`Status: ${currentStage}`}>
      <span class="text-xs tracking-wide text-muted-foreground">Status</span>
      <Badge variant={STAGE_VARIANT[currentStage] || 'secondary'} class="w-full max-w-10 justify-center px-1.5 truncate text-center text-[10px]">
        {currentStage}
      </Badge>
    </div>
  </aside>
{:else}
<aside class={cn('flex h-full w-72 shrink-0 flex-col border-r border-border bg-card text-card-foreground max-sm:fixed max-sm:inset-0 max-sm:z-50 max-sm:w-full max-sm:border-r-0', className)}>
  <div class="flex items-start justify-between gap-2 px-5 py-3">
    <div class="flex flex-col gap-1">
      <h1 class="text-xl font-bold tracking-tight">{APP_NAME}</h1>
      <p class="text-xs text-muted-foreground">{APP_TAGLINE}</p>
    </div>
    <div class="flex shrink-0 items-center gap-1">
      <ThemeToggle variant="ghost" />
      <button
        class="flex size-8 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
        title="Hide sidebar"
        onclick={onToggle}
      >
        <PanelLeftClose class="size-4" />
      </button>
    </div>
  </div>
  <Separator />
  <div class="flex-1 overflow-y-auto px-3 py-3">
    {#if previousAnalyses.length > 0}
      <div class="space-y-2">
        <p class="text-xs font-medium text-muted-foreground">PREVIOUS ANALYSES</p>
        <div class="space-y-1">
          {#each previousAnalyses as item (item.id)}
            <div
              class={cn(
                'group flex w-full items-start rounded-lg border text-left text-xs transition-colors',
                item.id === analysisId && 'bg-primary/10 border-primary/30',
                item.id !== analysisId && 'border-transparent',
              )}
            >
              <button
                class="flex-1 flex-col gap-0.5 px-2.5 py-2 min-w-0"
                onclick={() => loadAnalysis?.(item)}
                title={item.id}
              >
                <div class="flex items-center gap-1.5">
                  <FileVideo class="size-3 shrink-0 text-muted-foreground" />
                  <span class="truncate font-medium text-foreground">{item.video_filename}</span>
                </div>
                <div class="flex items-center gap-1.5 mt-0.5">
                  <span class={cn('rounded-md border px-1.5 py-0.5 text-[10px] font-medium', CONDITION_COLORS[item.condition] || 'bg-muted text-muted-foreground')}>
                    {item.condition}
                  </span>
                  <span class={cn(
                    'rounded-md px-1.5 py-0.5 text-[10px]',
                    item.stage === 'done' && 'bg-success/15 text-success',
                    item.stage === 'failed' && 'bg-destructive/15 text-destructive',
                    item.stage !== 'done' && item.stage !== 'failed' && 'bg-muted text-muted-foreground',
                  )}>
                    {item.stage}
                  </span>
                  {#if item.created_at}
                    <span class="ml-auto flex items-center gap-0.5 text-[10px] text-muted-foreground">
                      <Clock class="size-2.5" />{formatDate(item.created_at)}
                    </span>
                  {:else}
                    <span class="ml-auto text-[10px] text-muted-foreground">--</span>
                  {/if}
                </div>
              </button>
              <a
                class="shrink-0 p-1.5 text-muted-foreground/50 hover:text-foreground opacity-0 group-hover:opacity-100 transition-opacity"
                href={`/memory/${item.id}`}
                title="Object memory"
              >
                <DatabaseZap class="size-3" />
              </a>
              <button
                class="shrink-0 p-1.5 text-muted-foreground/50 hover:text-destructive opacity-0 group-hover:opacity-100 transition-opacity"
                onclick={(e: MouseEvent) => { e.stopPropagation(); onDeleteAnalysis?.(item.id); }}
                title="Delete analysis"
              >
                <Trash2 class="size-3" />
              </button>
            </div>
          {/each}
        </div>
      </div>
    {:else}
      <p class="text-xs text-muted-foreground">No previous analyses.</p>
    {/if}
  </div>

  {#if onResetDb}
    <div class="px-3 pb-2">
      <Button
        variant="ghost"
        size="sm"
        class="w-full justify-start text-xs text-muted-foreground hover:text-destructive"
        onclick={onResetDb}
        disabled={resetDisabled}
      >
        <Database class="size-3 mr-1.5" /> Clear analysis data
      </Button>
    </div>
  {/if}
  <Separator />
  <div class="flex flex-col gap-2 px-5 py-3 text-xs text-muted-foreground">
    <div class="flex items-center justify-between">
      <span>Status</span>
      <Badge variant={STAGE_VARIANT[currentStage] || 'secondary'} class="text-[10px]">
        {currentStage}
      </Badge>
    </div>
    <p class="text-[10px]">
      {APP_NAME} v{APP_VERSION} © 2026 Ghiffary Rifqialdi
    </p>
  </div>
</aside>
{/if}

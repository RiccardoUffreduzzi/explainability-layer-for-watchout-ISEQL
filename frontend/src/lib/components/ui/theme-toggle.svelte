<script lang="ts">
  import { mode, toggleMode } from 'mode-watcher';
  import { Moon, Sun } from 'lucide-svelte';
  import { cn } from '$lib/utils';

  type Props = { class?: string; showLabel?: boolean };
  let { class: className = '', showLabel = false }: Props = $props();

  const dark = $derived($mode === 'dark');
</script>

<button
  type="button"
  onclick={toggleMode}
  title={dark ? 'Switch to light theme' : 'Switch to dark theme'}
  aria-label={dark ? 'Switch to light theme' : 'Switch to dark theme'}
  aria-pressed={dark}
  class={cn(
    'inline-flex h-8 items-center justify-center gap-2 rounded-lg border border-border/70 bg-card text-muted-foreground shadow-sm transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50',
    showLabel ? 'px-3' : 'size-8',
    className
  )}
>
  {#if dark}
    <Sun class="size-4" />
    {#if showLabel}<span class="text-xs font-medium">Light</span>{/if}
  {:else}
    <Moon class="size-4" />
    {#if showLabel}<span class="text-xs font-medium">Dark</span>{/if}
  {/if}
</button>

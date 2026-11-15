<script lang="ts">
  import { mode, toggleMode } from 'mode-watcher';
  import { Moon, Sun } from 'lucide-svelte';
  import { cn } from '$lib/utils';

  type Props = {
    class?: string;
    showLabel?: boolean;
    variant?: 'default' | 'ghost';
    size?: 'default' | 'sm';
  };
  let { class: className = '', showLabel = false, variant = 'default', size = 'default' }: Props = $props();

  const dark = $derived($mode === 'dark');
  const sizeClass = $derived(showLabel ? (size === 'sm' ? 'h-9 px-3' : 'h-8 px-3') : size === 'sm' ? 'h-9 w-9' : 'size-8');
</script>

<button
  type="button"
  onclick={toggleMode}
  title={dark ? 'Switch to light theme' : 'Switch to dark theme'}
  aria-label={dark ? 'Switch to light theme' : 'Switch to dark theme'}
  aria-pressed={dark}
  class={cn(
    'inline-flex items-center justify-center gap-2 rounded-lg transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50',
    variant === 'ghost'
      ? 'text-muted-foreground hover:bg-accent hover:text-foreground'
      : 'border border-border/70 bg-card text-muted-foreground shadow-sm hover:bg-accent hover:text-accent-foreground',
    sizeClass,
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

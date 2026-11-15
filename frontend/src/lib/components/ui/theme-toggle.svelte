<script lang="ts">
  import { mode, setMode, userPrefersMode } from 'mode-watcher';
  import { Check, Monitor, Moon, Sun } from 'lucide-svelte';
  import { cn } from '$lib/utils';

  type Props = {
    class?: string;
    showLabel?: boolean;
    variant?: 'default' | 'ghost';
    size?: 'default' | 'sm';
    menuAlign?: 'start' | 'end';
    menuSide?: 'bottom' | 'right';
  };
  let {
    class: className = '',
    showLabel = false,
    variant = 'default',
    size = 'default',
    menuAlign = 'end',
    menuSide = 'bottom',
  }: Props = $props();

  const MODES = [
    { value: 'light', label: 'Light', icon: Sun },
    { value: 'dark', label: 'Dark', icon: Moon },
    { value: 'system', label: 'System', icon: Monitor },
  ] as const;

  let open = $state(false);
  let root = $state<HTMLDivElement | null>(null);

  const dark = $derived($mode === 'dark');
  const preference = $derived($userPrefersMode);
  const currentLabel = $derived(
    preference === 'system' ? 'System' : preference === 'dark' ? 'Dark' : 'Light'
  );
  const title = $derived(
    preference === 'system'
      ? `Theme: System (${dark ? 'dark' : 'light'})`
      : `Theme: ${currentLabel}`
  );
  const sizeClass = $derived(
    showLabel ? (size === 'sm' ? 'h-9 px-3' : 'h-8 px-3') : size === 'sm' ? 'h-9 w-9' : 'size-8'
  );
  const menuPosition = $derived(
    menuSide === 'right'
      ? 'left-full top-0 ml-2'
      : cn('top-full mt-2', menuAlign === 'start' ? 'left-0' : 'right-0')
  );

  function choose(next: 'light' | 'dark' | 'system') {
    setMode(next);
    open = false;
  }

  function closeOnPointerDown(event: PointerEvent) {
    if (!root?.contains(event.target as Node)) open = false;
  }

  function closeOnKeydown(event: KeyboardEvent) {
    if (event.key === 'Escape') open = false;
  }

  $effect(() => {
    if (!open) return;
    window.addEventListener('pointerdown', closeOnPointerDown);
    window.addEventListener('keydown', closeOnKeydown);
    return () => {
      window.removeEventListener('pointerdown', closeOnPointerDown);
      window.removeEventListener('keydown', closeOnKeydown);
    };
  });
</script>

<div bind:this={root} class={cn('relative inline-flex', className)}>
  <button
    type="button"
    onclick={() => (open = !open)}
    {title}
    aria-label={title}
    aria-haspopup="menu"
    aria-expanded={open}
    class={cn(
      'inline-flex items-center justify-center gap-2 rounded-lg transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50',
      variant === 'ghost'
        ? 'text-muted-foreground hover:bg-accent hover:text-foreground'
        : 'border border-border/70 bg-card text-muted-foreground shadow-sm hover:border-primary/40 hover:bg-accent hover:text-accent-foreground',
      sizeClass
    )}
  >
    {#if preference === 'system'}
      <Monitor class="size-4" />
    {:else if preference === 'dark'}
      <Moon class="size-4" />
    {:else}
      <Sun class="size-4" />
    {/if}
    {#if showLabel}<span class="text-xs font-medium">{currentLabel}</span>{/if}
  </button>

  {#if open}
    <div
      class={cn(
        'absolute z-[80] w-36 rounded-lg border border-border bg-popover p-1 text-popover-foreground shadow-float',
        menuPosition
      )}
      role="menu"
      aria-label="Theme"
    >
      {#each MODES as option (option.value)}
        {@const Icon = option.icon}
        <button
          type="button"
          role="menuitemradio"
          aria-checked={preference === option.value}
          class={cn(
            'flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-xs transition-colors',
            preference === option.value
              ? 'bg-accent text-foreground'
              : 'text-muted-foreground hover:bg-accent hover:text-foreground'
          )}
          onclick={() => choose(option.value)}
        >
          <Icon class="size-3.5" />
          <span class="flex-1 text-left">{option.label}</span>
          {#if preference === option.value}<Check class="size-3.5" />{/if}
        </button>
      {/each}
    </div>
  {/if}
</div>

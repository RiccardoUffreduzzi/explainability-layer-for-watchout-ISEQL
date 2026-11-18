<script lang="ts">
  import { mode, setMode, userPrefersMode } from 'mode-watcher';
  import { Check, Monitor, Moon, Sun } from 'lucide-svelte';
  import * as DropdownMenu from '$lib/components/ui/dropdown-menu/index.js';
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
</script>

<DropdownMenu.Root>
  <DropdownMenu.Trigger
    {title}
    aria-label={title}
    class={cn(
      'inline-flex items-center justify-center gap-2 rounded-lg transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50',
      variant === 'ghost'
        ? 'text-muted-foreground hover:bg-accent hover:text-foreground'
        : 'border border-border/70 bg-card text-muted-foreground shadow-sm hover:border-primary/40 hover:bg-accent hover:text-accent-foreground',
      sizeClass,
      className
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
  </DropdownMenu.Trigger>

  <DropdownMenu.Content
    class="w-40"
    side={menuSide}
    align={menuSide === 'right' ? 'start' : menuAlign}
    sideOffset={8}
  >
    {#each MODES as option (option.value)}
      {@const Icon = option.icon}
      <DropdownMenu.Item
        class={cn(
          'gap-2.5 px-2.5 py-2 text-xs',
          preference === option.value && 'bg-accent text-accent-foreground'
        )}
        onSelect={() => setMode(option.value)}
      >
        <Icon class="size-4" />
        <span class="flex-1">{option.label}</span>
        {#if preference === option.value}<Check class="size-3.5" />{/if}
      </DropdownMenu.Item>
    {/each}
  </DropdownMenu.Content>
</DropdownMenu.Root>

<script lang="ts">
  import { getContext } from 'svelte';
  import { cn } from '$lib/utils';
  import type { HTMLButtonAttributes } from 'svelte/elements';

  type Props = HTMLButtonAttributes & { value: string; children?: import('svelte').Snippet };
  let { class: className = '', value, children, ...rest }: Props = $props();

  const ctx = getContext<{ value: string; setValue: (v: string) => void }>('tabs');
  const active = $derived(ctx.value === value);
</script>

<button
  {...rest}
  type="button"
  role="tab"
  aria-selected={active}
  class={cn(
    'inline-flex h-full items-center justify-center whitespace-nowrap rounded-md px-3 py-1.5 text-sm font-medium ring-offset-background transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 focus-visible:ring-offset-2',
    active
      ? 'bg-card text-foreground shadow-sm'
      : 'text-muted-foreground hover:text-foreground',
    className
  )}
  onclick={() => ctx.setValue(value)}
>
  {@render children?.()}
</button>

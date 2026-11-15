<script lang="ts">
  import type { HTMLInputAttributes } from 'svelte/elements';
  import { cn } from '$lib/utils';

  type Props = HTMLInputAttributes & { class?: string; value?: string | number };
  let { class: className = '', value = $bindable(), ...rest }: Props = $props();
</script>

<input
  class={cn(
    'flex h-10 w-full rounded-lg border border-input bg-card px-3 py-2 text-sm ring-offset-background transition-colors placeholder:text-muted-foreground focus-visible:border-primary/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 file:border-0 file:bg-transparent file:text-sm file:font-medium',
    className
  )}
  bind:value
  {...rest}
/>

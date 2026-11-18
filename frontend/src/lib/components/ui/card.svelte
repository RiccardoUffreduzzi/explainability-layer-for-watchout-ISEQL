<script lang="ts">
  import type { HTMLAttributes } from 'svelte/elements';
  import { cn } from '$lib/utils';

  type Props = HTMLAttributes<HTMLDivElement> & { class?: string; children?: import('svelte').Snippet };
  let { class: className = '', children, ...rest }: Props = $props();
</script>

<div class={cn('rounded-xl border border-border/70 bg-card text-card-foreground shadow-soft', className)} {...rest}>
  {@render children?.()}
</div>

<script lang="ts">
  import { cn } from '$lib/utils';
  import type { HTMLAttributes } from 'svelte/elements';
  type Props = HTMLAttributes<HTMLDivElement> & { children?: import('svelte').Snippet };
  let { class: className = '', children, ...rest }: Props = $props();
</script>

<div {...rest} class={cn('inline-flex h-9 items-center justify-center rounded-lg bg-muted/80 p-1 text-muted-foreground', className)}>
  {@render children?.()}
</div>

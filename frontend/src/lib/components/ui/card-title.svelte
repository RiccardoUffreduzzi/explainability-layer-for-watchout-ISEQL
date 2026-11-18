<script lang="ts">
  import type { HTMLAttributes } from 'svelte/elements';
  import { cn } from '$lib/utils';
  type Props = HTMLAttributes<HTMLHeadingElement> & { class?: string; children?: import('svelte').Snippet };
  let { class: className = '', children, ...rest }: Props = $props();
</script>

<h3 class={cn('text-base font-semibold leading-none tracking-tight', className)} {...rest}>
  {@render children?.()}
</h3>

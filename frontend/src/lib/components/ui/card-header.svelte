<script lang="ts" module>
  import { cn } from '$lib/utils';
  type Props = import('svelte/elements').HTMLAttributes<HTMLHeadingElement> & { class?: string; children?: import('svelte').Snippet };
  export function header(props: Props) { return props; }
</script>

<script lang="ts">
  type Props = import('svelte/elements').HTMLAttributes<HTMLDivElement> & { class?: string; children?: import('svelte').Snippet };
  let { class: className = '', children, ...rest }: Props = $props();
</script>

<div class={cn('flex flex-col space-y-1.5 p-5 pb-3', className)} {...rest}>
  {@render children?.()}
</div>

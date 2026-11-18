<script lang="ts">
  import { MousePointerClick, Hand } from 'lucide-svelte';

  let visible = $state(true);
</script>

{#if visible}
  <div class="flex items-center gap-1.5 rounded-lg border border-border/60 bg-muted/30 px-2 py-1 text-[10px] leading-tight text-muted-foreground">
    <MousePointerClick class="size-3 shrink-0" />
    <Hand class="size-3 shrink-0" />
    <span>Right-click (desktop) or long-press (touch) to delete</span>
    <button
      type="button"
      class="ml-auto shrink-0 rounded-md px-0.5 text-muted-foreground hover:text-foreground"
      title="Dismiss"
      aria-label="Dismiss delete hint"
      onclick={() => (visible = false)}
    >✕</button>
  </div>
{/if}

<script lang="ts">
  import Button from '$lib/components/ui/button.svelte';
  import { confirmState, resolveConfirm } from '$lib/confirm.svelte';

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') resolveConfirm(false);
    if (e.key === 'Enter') resolveConfirm(true);
  }
</script>

<svelte:window onkeydown={onKeydown} />

{#if confirmState.open}
  <div
    class="fixed inset-0 z-[110] flex items-center justify-center p-4"
    role="dialog"
    aria-modal="true"
    aria-labelledby="confirm-title"
    aria-describedby="confirm-message"
    tabindex="-1"
    onkeydown={(e) => { if (e.key === 'Escape') resolveConfirm(false); }}
  >
    <div class="absolute inset-0 bg-black/50 backdrop-blur-sm" role="presentation" onclick={() => resolveConfirm(false)}></div>
    <div class="relative z-10 w-full max-w-sm rounded-2xl border bg-card p-5 shadow-float">
      <h2 id="confirm-title" class="text-sm font-semibold">{confirmState.title}</h2>
      <p id="confirm-message" class="mt-2 text-xs leading-relaxed text-muted-foreground">{confirmState.message}</p>
      <div class="mt-4 flex justify-end gap-2">
        <Button type="button" variant="ghost" onclick={() => resolveConfirm(false)}>{confirmState.cancelLabel}</Button>
        <Button type="button" variant="destructive" onclick={() => resolveConfirm(true)}>{confirmState.confirmLabel}</Button>
      </div>
    </div>
  </div>
{/if}

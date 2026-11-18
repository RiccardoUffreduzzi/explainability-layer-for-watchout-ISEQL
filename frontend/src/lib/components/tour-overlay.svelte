<script lang="ts">
  import { onMount } from 'svelte';
  import { tick } from 'svelte';
  import { tour, tourNext, tourPrev, tourEnd, type TourStep } from '$lib/tour.svelte';

  let tooltipEl = $state<HTMLElement | null>(null);
  let targetRect = $state<DOMRect | null>(null);
  let hasTarget = $state(false);
  let tipH = $state(0);
  let vw = $state(0);
  let vh = $state(0);

  const step: TourStep | null = $derived(tour.active ? (tour.steps[tour.index] ?? null) : null);
  const progress = $derived(tour.steps.length ? ((tour.index + 1) / tour.steps.length) * 100 : 0);

  onMount(() => {
    vw = window.innerWidth;
    vh = window.innerHeight;
  });

  function resolveTarget() {
    if (!tour.active || !step) {
      targetRect = null;
      hasTarget = false;
      return;
    }
    const t = step.target ? document.querySelector<HTMLElement>(`[data-tour="${step.target}"]`) : null;
    if (t) {
      t.scrollIntoView({ block: 'center', behavior: 'auto' });
      targetRect = t.getBoundingClientRect();
      hasTarget = true;
    } else {
      targetRect = null;
      hasTarget = false;
    }
  }

  $effect(() => {
    if (!tour.active || !step) {
      targetRect = null;
      hasTarget = false;
      return;
    }
    void vw;
    void vh;
    step.action?.();
    // Wait for the action's state changes to hit the DOM before highlighting.
    tick().then(resolveTarget);
  });

  $effect(() => {
    if (!tour.active || !step) {
      tipH = 0;
      return;
    }
    void targetRect;
    tick().then(() => {
      tipH = tooltipEl?.offsetHeight ?? 0;
    });
  });

  function clamp(v: number, lo: number, hi: number): number {
    return Math.max(lo, Math.min(v, hi));
  }

  function tooltipStyle(): string {
    const gap = 12;
    const maxW = Math.max(120, Math.min(360, vw - gap * 2));
    const h = Math.max(tipH, 0);
    const maxTop = Math.max(gap, vh - h - gap);

    if (targetRect && hasTarget) {
      const rect = targetRect;
      const placement = step?.placement ?? 'bottom';
      const left = clamp(rect.left + rect.width / 2 - maxW / 2, gap, vw - maxW - gap);

      if (placement === 'top') {
        let top = rect.top - gap - h;
        if (top < gap) top = rect.bottom + gap;
        return `left:${left}px; top:${clamp(top, gap, maxTop)}px; width:${maxW}px;`;
      }
      if (placement === 'left') {
        let x = rect.left - maxW - gap;
        if (x < gap) x = rect.right + gap;
        return `left:${clamp(x, gap, vw - maxW - gap)}px; top:${clamp(rect.top, gap, maxTop)}px; width:${maxW}px;`;
      }
      if (placement === 'right') {
        let x = rect.right + gap;
        if (x + maxW > vw - gap) x = rect.left - maxW - gap;
        return `left:${clamp(x, gap, vw - maxW - gap)}px; top:${clamp(rect.top, gap, maxTop)}px; width:${maxW}px;`;
      }
      // bottom (default)
      let top = rect.bottom + gap;
      if (top + h > vh - gap) top = rect.top - gap - h;
      return `left:${left}px; top:${clamp(top, gap, maxTop)}px; width:${maxW}px;`;
    }

    // centered (no target)
    return `left:${Math.round((vw - maxW) / 2)}px; top:${clamp(Math.round(vh / 2 - h / 2), gap, maxTop)}px; width:${maxW}px;`;
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') tourEnd();
    if (e.key === 'ArrowRight') tourNext();
    if (e.key === 'ArrowLeft') tourPrev();
  }
</script>

<svelte:window
  onkeydown={onKeydown}
  onresize={() => {
    vw = window.innerWidth;
    vh = window.innerHeight;
  }}
/>

{#if tour.active && step}
  <div class="fixed inset-0 z-[100]">
    {#if targetRect && hasTarget}
      <!-- spotlight (dim everything except the target) -->
      <div
        class="absolute rounded-xl shadow-[0_0_0_9999px_rgba(0,0,0,0.6)]"
        style="left: {targetRect.left}px; top: {targetRect.top}px; width: {targetRect.width}px; height: {targetRect.height}px;"
      ></div>
    {:else}
      <!-- svelte-ignore a11y_no_static_element_interactions -->
      <div class="absolute inset-0 bg-black/60" role="presentation" onclick={tourNext}></div>
    {/if}

    <div
      bind:this={tooltipEl}
        class="absolute max-h-[calc(100dvh-24px)] overflow-y-auto rounded-xl border bg-popover p-4 text-popover-foreground shadow-float"
      style={tooltipStyle()}
    >
      <div class="mb-3 h-1 w-full overflow-hidden rounded-full bg-muted">
        <div class="h-full rounded-full bg-primary transition-all" style="width: {progress}%"></div>
      </div>
      <h3 class="text-sm font-semibold">{step.title}</h3>
      <p class="mt-1 text-xs leading-relaxed text-muted-foreground">{step.body}</p>
      <div class="mt-3 flex items-center justify-between gap-3">
        <button
          type="button"
          class="rounded-lg border px-2.5 py-1 text-xs text-muted-foreground hover:bg-muted"
          onclick={tourEnd}
        >Skip</button>
        <div class="flex items-center gap-2">
          <span class="text-xs tabular-nums text-muted-foreground">{tour.index + 1} / {tour.steps.length}</span>
          {#if tour.index > 0}
            <button
              type="button"
              class="rounded-lg border px-2.5 py-1 text-xs text-muted-foreground hover:bg-muted"
              onclick={tourPrev}
            >Back</button>
          {/if}
          <button
            type="button"
            class="rounded-lg bg-primary px-3 py-1 text-xs font-medium text-primary-foreground hover:bg-primary/90"
            onclick={tourNext}
          >
            {tour.index < tour.steps.length - 1 ? 'Next' : 'Done'}
          </button>
        </div>
      </div>
    </div>
  </div>
{/if}

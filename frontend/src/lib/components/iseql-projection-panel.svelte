<script lang="ts">
  import { autoProjection, domainAttr, type BuilderGroup, type Unit } from '$lib/iseql-model';

  type Props = {
    group: BuilderGroup | null;
    unit: Unit;
    onChange: (group: BuilderGroup) => void;
  };
  let { group, unit, onChange }: Props = $props();

  let pickerOpen = $state(false);
  let dragIndex = $state<number | null>(null);
  let dropIndex = $state<number | null>(null);
  let listEl = $state<HTMLDivElement | null>(null);

  const allFields = $derived.by(() => {
    if (!group) return [] as string[];
    const { start, end } = domainAttr(unit);
    const fields: string[] = [];
    group.intervals.forEach((iv, i) => {
      const m = `M${i + 1}`;
      for (let k = 1; k <= iv.args.length; k++) fields.push(`${m}.arg${k}`);
      fields.push(`${m}.${start}`, `${m}.${end}`);
    });
    return fields;
  });

  const current = $derived(group ? (group.projection ?? autoProjection(group, unit)) : []);
  const availableFields = $derived(allFields.filter((f) => !current.includes(f)));

  function pick(field: string) {
    if (!group) return;
    onChange({ ...group, projection: [...current, field] });
    pickerOpen = false;
  }

  function reset() {
    if (!group) return;
    onChange({ ...group, projection: null });
  }

  function removeField(i: number) {
    if (!group) return;
    onChange({ ...group, projection: current.filter((_, k) => k !== i) });
  }

  function moveField(i: number, dir: -1 | 1) {
    if (!group) return;
    const j = i + dir;
    if (j < 0 || j >= current.length) return;
    const next = [...current];
    [next[i], next[j]] = [next[j], next[i]];
    onChange({ ...group, projection: next });
  }

  function reorderField(from: number, insertIdx: number) {
    if (!group || from === insertIdx) return;
    if (from < 0 || from >= current.length || insertIdx < 0 || insertIdx >= current.length) return;
    const next = [...current];
    const [moved] = next.splice(from, 1);
    next.splice(insertIdx, 0, moved);
    onChange({ ...group, projection: next });
  }

  function insertionIndex(clientY: number): number {
    if (!listEl) return 0;
    const rows = [...listEl.querySelectorAll<HTMLElement>('[data-field-row]')];
    let idx = 0;
    for (const row of rows) {
      const rect = row.getBoundingClientRect();
      if (clientY < rect.top + rect.height / 2) break;
      idx++;
    }
    return idx;
  }

  function onDragStart(i: number, e: DragEvent) {
    dragIndex = i;
    dropIndex = null;
    if (e.dataTransfer) {
      e.dataTransfer.setData('text/plain', String(i));
      e.dataTransfer.effectAllowed = 'move';
    }
  }

  function onListDragOver(e: DragEvent) {
    if (dragIndex == null) return;
    e.preventDefault();
    dropIndex = insertionIndex(e.clientY);
    if (e.dataTransfer) e.dataTransfer.dropEffect = 'move';
  }

  function onListDrop() {
    if (dragIndex == null || dropIndex == null) return;
    const from = dragIndex;
    const idx = dropIndex;
    const insertIdx = idx <= from ? idx : idx - 1;
    dragIndex = null;
    dropIndex = null;
    reorderField(from, insertIdx);
  }

  function endDrag() {
    dragIndex = null;
    dropIndex = null;
  }

  // Horizontal drop line at the insertion point.
  $effect(() => {
    void dragIndex;
    void dropIndex;
    if (!listEl) return;
    listEl.querySelectorAll('[data-drop-line]').forEach((c) => c.remove());
    if (dragIndex == null || dropIndex == null) return;
    const rows = [...listEl.querySelectorAll<HTMLElement>('[data-field-row]')];
    const line = document.createElement('div');
    line.setAttribute('data-drop-line', 'true');
    line.className = 'h-0.5 rounded bg-primary';
    if (dropIndex < rows.length) rows[dropIndex].before(line);
    else listEl.appendChild(line);
  });
</script>

{#if !group}
  <p class="text-xs text-muted-foreground">Select a group to edit its projection.</p>
{:else}
  <div class="space-y-1.5">
    <div class="flex items-center justify-between">
      <span class="text-xs font-semibold">Projection</span>
      <div class="flex items-center gap-1">
        <button type="button" class="rounded-md border px-1.5 py-0.5 text-xs text-muted-foreground hover:bg-muted" title="Reset to auto" onclick={reset}>⟲</button>
        <button type="button" class="rounded-md border px-1.5 py-0.5 text-xs text-muted-foreground hover:bg-muted" title="Add field" onclick={() => (pickerOpen = true)}>＋</button>
      </div>
    </div>

    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div class="max-h-40 space-y-1 overflow-y-auto pr-1" bind:this={listEl} ondragover={onListDragOver} ondrop={onListDrop}>
      {#each current as f, i (i)}
        <div
          data-field-row="true"
          class={[
            'flex cursor-grab items-center gap-1 rounded-md border px-1.5 py-0.5 font-mono text-xs transition-all',
            dragIndex === i ? 'opacity-40' : '',
          ].join(' ')}
          draggable="true"
          ondragstart={(e) => onDragStart(i, e)}
          ondragend={endDrag}
        >
          <span class="flex-1">{f}</span>
          <button type="button" draggable="false" class="text-muted-foreground hover:text-foreground" title="move up" onclick={() => moveField(i, -1)}>▲</button>
          <button type="button" draggable="false" class="text-muted-foreground hover:text-foreground" title="move down" onclick={() => moveField(i, 1)}>▼</button>
          <button type="button" draggable="false" class="text-muted-foreground hover:text-foreground" title="remove" onclick={() => removeField(i)}>✕</button>
        </div>
      {:else}
        <p class="text-xs text-muted-foreground">No fields.</p>
      {/each}
    </div>
  </div>

  {#if pickerOpen}
    <div class="fixed inset-0 z-50 flex items-center justify-center p-4" role="presentation" onkeydown={(e) => { if (e.key === 'Escape') pickerOpen = false; }}>
      <div class="absolute inset-0 bg-black/40" onclick={() => (pickerOpen = false)} role="presentation"></div>
      <div class="relative z-10 w-full max-w-xs rounded-2xl border bg-card p-4 shadow-float" role="dialog" aria-modal="true" tabindex="-1">
        <div class="mb-2 text-sm font-semibold">Add projection field</div>
        <div class="grid max-h-72 grid-cols-2 gap-1 overflow-y-auto">
          {#each availableFields as f (f)}
            <button type="button" class="rounded-md border px-2 py-1 font-mono text-xs hover:bg-muted" onclick={() => pick(f)}>{f}</button>
          {:else}
            <p class="col-span-2 text-xs text-muted-foreground">No fields left to add.</p>
          {/each}
        </div>
        <div class="mt-2 flex justify-end">
          <button type="button" class="rounded-md border px-2 py-1 text-xs text-muted-foreground hover:bg-muted" onclick={() => (pickerOpen = false)}>Cancel</button>
        </div>
      </div>
    </div>
  {/if}
{/if}

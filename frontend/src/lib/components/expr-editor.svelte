<script lang="ts">
  import { longpress } from '$lib/actions/longpress';
  import type { EditorToken } from '$lib/iseql-model';

  type Props = {
    text: string;
    tokens: EditorToken[] | null;
    options: string[];
    operators: string[];
    kind: string;
    onText: (t: string) => void;
    onOpen?: (name: string) => void;
    onHover?: (names: string[]) => void;
    labelOf?: (name: string) => string;
  };
  let { text, tokens, options, operators, kind, onText, onOpen = () => undefined, onHover = () => undefined, labelOf }: Props = $props();

  const display = (name: string): string => labelOf?.(name) ?? name;

  let el = $state<HTMLDivElement | null>(null);
  let paletteEl = $state<HTMLDivElement | null>(null);
  let suppress = false;
  let search = $state('');
  let menu = $state<{ x: number; y: number; name: string } | null>(null);
  let dragging = $state<{ type: 'reorder' | 'insert'; name: string } | null>(null);
  let dropIndex = $state<number | null>(null);
  let overPalette = $state(false);

  // transient, non-reactive drag bookkeeping
  let pending: { type: 'reorder' | 'insert'; name: string; startX: number; startY: number } | null = null;
  let dragActive = false;

  const mentioned = $derived([...new Set(text.split(/[^A-Za-z0-9_]+/).filter(Boolean))]);
  const unusedOptions = $derived(options.filter((n) => !mentioned.includes(n)));
  const filteredOptions = $derived(unusedOptions.filter((n) => n.toLowerCase().includes(search.trim().toLowerCase())));

  function esc(s: string): string {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  $effect(() => {
    void tokens;
    void operators;
    if (suppress) { suppress = false; return; }
    render();
  });

  // Drag visual feedback: dim the grabbed chip while it's being dragged.
  $effect(() => {
    void dragging;
    if (!el) return;
    const chips = el.querySelectorAll('[data-item]');
    chips.forEach((c) => {
      const name = c.getAttribute('data-item');
      c.classList.remove('opacity-40');
      if (dragging?.type === 'reorder' && name === dragging.name) c.classList.add('opacity-40');
    });
  });

  // Drop caret: show a caret at the insertion point for both inserting a list
  // item and reordering an existing chip.
  $effect(() => {
    void dragging;
    void dropIndex;
    void overPalette;
    if (!el) return;
    el.querySelectorAll('[data-caret]').forEach((c) => c.remove());
    if (!dragging || overPalette) return;
    const chips = [...el.querySelectorAll('[data-item]')];
    const idx = dropIndex == null ? chips.length : dropIndex;
    const caret = document.createElement('span');
    caret.setAttribute('data-caret', 'true');
    caret.setAttribute('contenteditable', 'false');
    caret.className = 'pointer-events-none mx-0.5 inline-block h-5 w-[2px] rounded bg-primary align-middle';
    if (idx >= 0 && idx < chips.length) chips[idx].before(caret);
    else el.appendChild(caret);
  });

  function render() {
    if (!el || !tokens) return;
    el.innerHTML = tokens.map((t) => tokenHtml(t)).join('');
  }

  function tokenHtml(t: EditorToken): string {
    switch (t.type) {
      case 'item':
        return `<span contenteditable="false" draggable="false" data-item="${esc(t.name)}" class="mx-0.5 inline-flex select-none touch-none align-middle"><button type="button" class="rounded-md border border-primary/40 bg-primary/10 px-1.5 py-0.5 font-mono text-xs">${esc(display(t.name))}</button></span>`;
      case 'op':
        return `<select contenteditable="false" class="mx-0.5 h-6 rounded-md border bg-card px-0.5 py-0 align-middle font-mono text-xs">${operators.map((o) => `<option${o === t.op ? ' selected' : ''}>${esc(o)}</option>`).join('')}</select>`;
      case 'open':
        return '<span class="text-muted-foreground">(</span>';
      case 'close':
        return '<span class="text-muted-foreground">)</span>';
    }
  }

  function extractText(node: Node): string {
    if (node.nodeType === Node.TEXT_NODE) return node.textContent ?? '';
    const el = node as HTMLElement;
    if (el.tagName === 'SELECT') return (el as HTMLSelectElement).value;
    if (el.hasAttribute && el.hasAttribute('data-item')) return el.dataset.item ?? '';
    let out = '';
    node.childNodes.forEach((c) => { out += extractText(c); });
    return out;
  }

  function sync() {
    if (!el) return;
    suppress = true;
    onText(extractText(el));
    setTimeout(() => { suppress = false; }, 0);
  }

  function insertItem(name: string, index: number | null = null) {
    if (!el) return;
    const chips = [...el.querySelectorAll('[data-item]')];
    const op = operators[0] ?? '';
    const chip = `<span contenteditable="false" draggable="false" data-item="${esc(name)}" class="mx-0.5 inline-flex select-none touch-none align-middle"><button type="button" class="rounded-md border border-primary/40 bg-primary/10 px-1.5 py-0.5 font-mono text-xs">${esc(display(name))}</button></span>`;
    const opHtml = `<select contenteditable="false" class="mx-0.5 h-6 rounded-md border bg-card px-0.5 py-0 align-middle font-mono text-xs">${operators.map((o) => `<option>${esc(o)}</option>`).join('')}</select>`;
    const hasContent = extractText(el).trim().length > 0;
    if (!hasContent) {
      el.innerHTML = chip;
    } else if (index != null && index >= 0 && index < chips.length) {
      const frag = document.createRange().createContextualFragment(`${chip} ${opHtml}`);
      chips[index].before(frag);
    } else {
      el.insertAdjacentHTML('beforeend', ` ${opHtml} ${chip}`);
    }
    sync();
  }

  function pointInRect(x: number, y: number, rect: DOMRect): boolean {
    return x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom;
  }

  function onPointerDown(e: PointerEvent) {
    if (e.button !== 0) return;
    const chip = (e.target as HTMLElement).closest('[data-item]') as HTMLElement | null;
    if (chip) {
      pending = { type: 'reorder', name: chip.dataset.item ?? '', startX: e.clientX, startY: e.clientY };
      dragActive = false;
      return;
    }
    const pitem = (e.target as HTMLElement).closest('[data-palette-item]') as HTMLElement | null;
    if (pitem) {
      pending = { type: 'insert', name: pitem.dataset.paletteItem ?? '', startX: e.clientX, startY: e.clientY };
      dragActive = false;
    }
  }

  function onPointerMove(e: PointerEvent) {
    if (!pending) return;
    if (!dragActive) {
      if (Math.hypot(e.clientX - pending.startX, e.clientY - pending.startY) <= 6) return;
      dragActive = true;
      dragging = { type: pending.type, name: pending.name };
      (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
    }
    if (!dragging) return;
    overPalette = paletteEl ? pointInRect(e.clientX, e.clientY, paletteEl.getBoundingClientRect()) : false;
    dropIndex = insertionIndex(e.clientX);
  }

  function onPointerUp() {
    if (!pending) return;
    const wasDrag = dragActive;
    const d = dragging;
    const idx = dropIndex;
    const overPal = overPalette;
    pending = null;
    dragActive = false;
    dragging = null;
    dropIndex = null;
    overPalette = false;
    if (!wasDrag || !d) return;
    if (d.type === 'reorder') {
      if (overPal) removeItem(d.name);
      else moveItem(d.name, idx);
    } else if (!overPal) {
      insertItem(d.name, idx);
    }
  }

  function insertionIndex(clientX: number): number {
    if (!el) return 0;
    const chips = [...el.querySelectorAll('[data-item]')];
    let idx = 0;
    for (const chip of chips) {
      const rect = chip.getBoundingClientRect();
      if (clientX < rect.left + rect.width / 2) break;
      idx++;
    }
    return idx;
  }

  function moveItem(name: string, idx: number | null) {
    if (!el || idx == null) return;
    const chips = [...el.querySelectorAll<HTMLElement>('[data-item]')];
    const di = chips.findIndex((c) => c.dataset.item === name);
    if (di < 0) return;
    const chipNode = chips[di] as ChildNode;

    // operator to move together with the chip (trailing, or leading if last)
    let after = chipNode.nextSibling;
    while (after && after.nodeType === 3 && !(after.textContent ?? '').trim()) after = after.nextSibling;
    const afterOp = after && (after as HTMLElement).tagName === 'SELECT' ? (after as ChildNode) : null;
    let opNode: ChildNode | null = afterOp;
    if (!opNode) {
      let before = chipNode.previousSibling;
      while (before && before.nodeType === 3 && !(before.textContent ?? '').trim()) before = before.previousSibling;
      if (before && (before as HTMLElement).tagName === 'SELECT') opNode = before as ChildNode;
    }

    chipNode.remove();
    if (opNode) opNode.remove();

    // insertion index in the list without the dragged chip
    const insertIdx = idx <= di ? idx : idx - 1;
    const remaining = [...el.querySelectorAll('[data-item]')];
    if (insertIdx >= 0 && insertIdx < remaining.length) {
      const target = remaining[insertIdx];
      target.before(chipNode);
      if (opNode) chipNode.after(opNode);
    } else {
      if (opNode) el.appendChild(opNode);
      el.appendChild(chipNode);
    }
    sync();
  }

  function removeItem(name: string) {
    if (!el) return;
    const chip = el.querySelector(`[data-item="${CSS.escape(name)}"]`);
    if (!chip) return;
    let prev = chip.previousSibling;
    while (prev && prev.nodeType === 3 && !(prev.textContent ?? '').trim()) prev = prev.previousSibling;
    let next = chip.nextSibling;
    while (next && next.nodeType === 3 && !(next.textContent ?? '').trim()) next = next.nextSibling;
    if (next && (next as HTMLElement).tagName === 'SELECT') {
      chip.remove();
      next.remove();
    } else if (prev && (prev as HTMLElement).tagName === 'SELECT') {
      chip.remove();
      prev.remove();
    } else {
      chip.remove();
    }
    sync();
  }

  function onContextMenu(e: MouseEvent) {
    const chip = (e.target as HTMLElement).closest('[data-item]') as HTMLElement | null;
    if (!chip) return;
    e.preventDefault();
    menu = { x: e.clientX, y: e.clientY, name: chip.dataset.item ?? '' };
  }

  function onClick(e: MouseEvent) {
    const btn = (e.target as HTMLElement).closest('button');
    if (!btn) return;
    const chip = btn.closest('[data-item]') as HTMLElement | null;
    if (chip) onOpen(chip.dataset.item ?? '');
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter' || e.key === ' ') {
      const btn = (e.target as HTMLElement).closest('button');
      if (btn) {
        const chip = btn.closest('[data-item]') as HTMLElement | null;
        if (chip) { e.preventDefault(); onOpen(chip.dataset.item ?? ''); }
      }
    }
  }

  function onMouseOver(e: MouseEvent) {
    const chip = (e.target as HTMLElement).closest('[data-item]') as HTMLElement | null;
    if (chip) onHover([chip.dataset.item ?? '']);
  }

  function onMouseOut() {
    onHover([]);
  }

  function onFocus(e: FocusEvent) {
    const chip = (e.target as HTMLElement).closest('[data-item]') as HTMLElement | null;
    if (chip) onHover([chip.dataset.item ?? '']);
  }

  function onBlur() {
    onHover([]);
  }

  function onInput() {
    sync();
  }
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="space-y-1.5" onpointerdown={onPointerDown} onpointermove={onPointerMove} onpointerup={onPointerUp} onpointercancel={onPointerUp}>
  <div
    bind:this={el}
    contenteditable="true"
    role="textbox"
    aria-multiline="false"
    tabindex="0"
    class={[
      'min-h-9 w-full rounded-lg border border-dashed bg-card px-2 py-1 font-mono text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring',
      dragging?.type === 'insert' ? 'ring-1 ring-primary' : '',
    ].join(' ')}
    oninput={onInput}
    onclick={onClick}
    onkeydown={onKeydown}
    onmouseover={onMouseOver}
    onmouseout={onMouseOut}
    onfocus={onFocus}
    onblur={onBlur}
    oncontextmenu={onContextMenu}
    use:longpress={{ onLongPress: (e) => { const chip = (e.target as HTMLElement).closest('[data-item]') as HTMLElement | null; if (chip) menu = { x: e.clientX, y: e.clientY, name: chip.dataset.item ?? '' }; } }}
  ></div>

  <div class="mb-1 text-[10px] text-muted-foreground">Drag into the box (each is used once); type ( and ) for grouping:</div>
  <input
    type="text"
    placeholder="Search…"
    class="h-6 w-full rounded-lg border bg-card px-1.5 text-xs outline-none focus-visible:ring-1 focus-visible:ring-ring"
    bind:value={search}
  />
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div
    bind:this={paletteEl}
    class={[
      'flex max-h-36 touch-pan-y flex-col gap-1 overflow-y-auto rounded-lg pr-1',
      overPalette ? 'ring-1 ring-primary bg-primary/5' : '',
    ].join(' ')}
  >
    {#each filteredOptions as name (name)}
      <button
        type="button"
        data-palette-item={name}
        class="inline-flex cursor-grab touch-none items-center rounded-md border border-primary/40 bg-primary/10 px-2 py-0.5 font-mono text-xs"
        title="Drag into the expression · click to configure"
        onclick={() => onOpen(name)}
        onmouseenter={() => onHover([name])}
        onmouseleave={() => onHover([])}
      >{display(name)}</button>
    {:else}
      <span class="text-[10px] text-muted-foreground">{search ? 'No matches.' : 'All items are used.'}</span>
    {/each}
  </div>
</div>

{#if menu}
  <div
    class="fixed inset-0 z-50"
    role="presentation"
    onclick={() => (menu = null)}
    oncontextmenu={(e) => { e.preventDefault(); menu = null; }}
  ></div>
  <div class="fixed z-50 w-44 rounded-xl border bg-popover py-1 text-xs shadow-float" style="left: {menu.x}px; top: {menu.y}px">
    <button
      type="button"
      class="block w-full px-3 py-1 text-left hover:bg-muted"
      onclick={() => { removeItem(menu!.name); menu = null; }}
    >Delete from expression</button>
  </div>
{/if}

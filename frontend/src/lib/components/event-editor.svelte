<script lang="ts">
  import { onMount } from 'svelte';
  import { browser } from '$app/environment';
  import { api } from '$lib/api';
  import Button from '$lib/components/ui/button.svelte';
  import Input from '$lib/components/ui/input.svelte';
  import IseqlTimeline from '$lib/components/iseql-timeline.svelte';
  import UnitToggle from '$lib/components/unit-toggle.svelte';
  import { AlertTriangle, CircleCheck } from 'lucide-svelte';
  import { normalizeModel, predicateLabel, unitFromModel, type IseqlModel, type PredicateVocab, type Unit, type Vocabulary } from '$lib/iseql-model';
  import type { Condition } from '$lib/types';
  import { inputStr } from '$lib/dom-helpers';
  import { registerTourSteps, startTour, hasSeenTour, tour, type TourStep } from '$lib/tour.svelte';

  const EDITOR_TOUR: TourStep[] = [
    { target: '', title: 'Event editor', body: 'Author an ISEQL event here. Edit it as raw ISEQL text or visually on the timeline, then save it.' },
    { target: 'editor-mode', title: 'Text / Timeline', body: 'Switch between writing the ISEQL query as text and the visual timeline builder.', action: () => setView('text') },
    { target: 'editor-unit', title: 'Seconds / Frames', body: 'Choose whether temporal attributes (st/et vs sf/ef) and thresholds are in seconds or frames.' },
    { target: 'editor-query', title: 'ISEQL query + SQL', body: 'Type your ISEQL query; it compiles live to SQL. Type pred=" to get predicate autocomplete with correct arguments.', action: () => setView('text') },
    { target: 'editor-canvas', title: 'Timeline canvas', body: 'Draw intervals on the empty canvas, drag blocks to move them, and drag their edges to resize. Right-click or long-press an interval to delete it.', action: () => setView('timeline') },
    { target: 'editor-intervals', title: 'Intervals & Sets', body: 'Intervals and sets are listed here. Right-click or long-press an item to delete it; click to edit.', action: () => setView('timeline') },
    { target: 'editor-save', title: 'Save event', body: 'When the query is ready, save the event. It then appears in the Events tab and in the analysis event list.' },
  ];

  type Props = {
    condition: Condition;
    initialId?: string | null;
    mode?: 'new' | 'open';
    onBack?: () => void;
    onSaved?: (id: string) => void;
    onOpenPredicate?: (name: string, modality: 'visual' | 'audio') => void;
  };
  let { condition, initialId = null, mode = 'open', onBack = () => undefined, onSaved = () => undefined, onOpenPredicate = () => undefined }: Props = $props();

  let view = $state<'text' | 'timeline'>('text');
  let eventId = $state('');
  let loadedId = $state<string | null>(null);
  let error = $state<string | null>(null);
  let status = $state<string | null>(null);
  let unit = $state<Unit>('seconds');

  let model = $state<IseqlModel | null>(null);
  let text = $state('');
  let sql = $state('');
  let vocabulary = $state<Vocabulary>({ predicates: [], participant_classes: [] });
  let taRef = $state<HTMLTextAreaElement | null>(null);
  type MenuItem = { label: string; insert: string; hint?: string };
  let menu = $state<{ start: number; end: number; items: MenuItem[] } | null>(null);
  let menuPos = $state<{ left: number; top: number }>({ left: 8, top: 8 });
  let menuIndex = $state(0);
  let menuEl = $state<HTMLDivElement | null>(null);
  let prevMenuRange = $state<{ start: number; end: number } | null>(null);

  const MENU_LIMIT = 5;
  let caretMirror: HTMLDivElement | null = null;

  const OPERATORS = ['Bef', 'Aft', 'SP', 'EF', 'DJ', 'RDJ', 'LOJ', 'ROJ'];
  const OPERATOR_PARAMS: Record<string, string> = {
    Bef: 'Bef(δ:∞; ζ:<=, ρ:0)',
    Aft: 'Aft(δ:∞; ζ:<=, ρ:0)',
    SP: 'SP(δ:∞; ζ:<=, ρ:0)',
    EF: 'EF(ε:∞; η:<=, ρ:0)',
    DJ: 'DJ(δ:∞, ε:∞; ζ:<=, η:<=, ρ:0)',
    RDJ: 'RDJ(δ:∞, ε:∞; ζ:<=, η:<=, ρ:0)',
    LOJ: 'LOJ(δ:∞, ε:∞; ζ:<=, η:<=, ρ:0)',
    ROJ: 'ROJ(δ:∞, ε:∞; ζ:<=, η:<=, ρ:0)',
  };

  const SYMBOLS = ['π', 'σ', '∪', '\\', '∩', '∧', '∨', '≠', '≤', '≥', '<', '>', 'δ', 'ε', 'ζ', 'η', 'ρ', '∞'];

  const conditionPreds = $derived(
    vocabulary.predicates.filter((p) =>
      condition === 'C' || (condition === 'A' ? p.modality === 'visual' : p.modality === 'audio')
    )
  );

  function errorReason(e: unknown): string {
    const body = (e as { body?: unknown })?.body;
    let detail: string;
    if (body && typeof body === 'object' && 'detail' in body) {
      detail = String((body as { detail: unknown }).detail);
    } else {
      detail = (e as Error).message;
    }
    return detail.replace(/^invalid (ISEQL query|model):\s*/i, '');
  }

  async function loadEvent() {
    if (!initialId) return;
    try {
      const resp = await api.get<{ model_json: string | null }>(`/api/events/${initialId}?condition=${condition}`);
      eventId = initialId;
      loadedId = initialId;
      let m: IseqlModel | null = null;
      if (resp.model_json) {
        try {
          m = normalizeModel(JSON.parse(resp.model_json));
        } catch { /* ignore */ }
      }
      model = m;
      unit = m ? unitFromModel(m) : 'seconds';
      let prefilled = (m as { iseql_text?: string } | null)?.iseql_text ?? '';
      if (!prefilled && m?.intervals?.length) {
        try {
          const p = await api.postJson<{ iseql: string }>('/api/iseql/preview', { model: m });
          prefilled = p.iseql || '';
        } catch { /* ignore */ }
      }
      text = prefilled || '';
    } catch (e) {
      error = `Failed to load event: ${(e as Error).message}`;
    }
  }

  onMount(async () => {
    try {
      vocabulary = await api.get<Vocabulary>('/api/iseql/vocabulary');
    } catch (e) {
      error = `Failed to load vocabulary: ${(e as Error).message}`;
    }
    if (initialId && mode === 'open') {
      await loadEvent();
      if (model) scheduleModelCompile();
    } else {
      eventId = '';
      model = null;
      text = '';
      sql = '';
    }
  });

  onMount(() => {
    registerTourSteps(EDITOR_TOUR, 'editor');
    if (!hasSeenTour('editor') && !tour.active) startTour(EDITOR_TOUR, 'editor');

    if (!browser) return;
    const mq = window.matchMedia('(max-width: 639px)');
    const onChange = (e: MediaQueryListEvent) => {
      if (e.matches) view = 'text';
    };
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  });

  // -------------------------------------------------------------------------
  // text <-> model synchronization
  // -------------------------------------------------------------------------

  function onTextInput(e: Event) {
    text = (e.currentTarget as HTMLTextAreaElement).value;
    scheduleTextCompile();
    updatePredMenu();
  }

  // -------------------------------------------------------------------------
  // predicate autocomplete
  // -------------------------------------------------------------------------

  function updatePredMenu() {
    const ta = taRef;
    if (!ta) { menu = null; prevMenuRange = null; return; }
    const pos = ta.selectionStart ?? text.length;
    const before = text.slice(0, pos);
    const result = predicateMenu(before, pos) ?? projectionMenu(before, pos) ?? operatorMenu(before, pos);
    menu = result;
    if (!result) { prevMenuRange = null; return; }
    // Reset the highlight only when the suggestion context actually changes
    // (caret moved or the partial token changed), not on arrow navigation.
    if (!prevMenuRange || prevMenuRange.start !== result.start || prevMenuRange.end !== result.end) {
      menuIndex = 0;
    }
    prevMenuRange = { start: result.start, end: result.end };
    const c = caretCoords(ta, pos);
    const container = ta.parentElement as HTMLElement | null;
    const cr = container?.getBoundingClientRect();
    const tr = ta.getBoundingClientRect();
    const lineH = parseFloat(getComputedStyle(ta).lineHeight) || 20;
    const left = cr ? tr.left - cr.left + c.left : c.left;
    const top = cr ? tr.top - cr.top + c.top - ta.scrollTop + lineH : c.top + lineH;
    menuPos = {
      left: Math.max(8, Math.min(left, (container?.clientWidth ?? 320) - 296)),
      top,
    };
  }

  function predicateMenu(before: string, pos: number): { start: number; end: number; items: MenuItem[] } | null {
    const m = /pred="([^"]*)$/.exec(before);
    if (!m) return null;
    const partial = m[1].toLowerCase();
    const start = pos - m[0].length;
    const items = conditionPreds
      .filter((p) => p.name.toLowerCase().includes(partial))
      .slice(0, MENU_LIMIT)
      .map((p) => ({ label: predicateLabel(p.name, p.args), insert: predSelectionText(p) }));
    return { start, end: pos, items };
  }

  function intervalAliases(): number[] {
    const nums = new Set<number>();
    for (const m of text.matchAll(/M(\d+)/g)) nums.add(Number(m[1]));
    return nums.size ? [...nums].sort((a, b) => a - b) : [1];
  }

  function intervalPredMap(): Map<number, string> {
    const map = new Map<number, string>();
    const re = /σ_\{[^}]*?pred="([^"]+)"[^}]*?\}\(M(\d+)\)/g;
    let m: RegExpExecArray | null;
    while ((m = re.exec(text))) map.set(Number(m[2]), m[1]);
    return map;
  }

  function projectionMenu(before: string, pos: number): { start: number; end: number; items: MenuItem[] } | null {
    const pi = before.lastIndexOf('π_{');
    if (pi < 0) return null;
    const afterPi = before.slice(pi + 3);
    if (afterPi.includes('}')) return null;
    const partial = afterPi.split(',').pop()!.trimStart();
    const preds = intervalPredMap();
    const dom = unit === 'seconds' ? ['st', 'et'] : ['sf', 'ef'];
    const items: MenuItem[] = [];
    for (const n of intervalAliases()) {
      const alias = `M${n}`;
      const slots = conditionPreds.find((p) => p.name === preds.get(n))?.args ?? [];
      const nArgs = Math.max(1, slots.length);
      const fields = [`${alias}.${dom[0]}`, `${alias}.${dom[1]}`];
      for (let k = 1; k <= nArgs; k++) fields.push(`${alias}.arg${k}`);
      for (const f of fields) {
        if (!partial || f.startsWith(partial)) items.push({ label: f, insert: f });
      }
      if (items.length >= MENU_LIMIT) break;
    }
    if (!items.length) return null;
    return { start: pos - partial.length, end: pos, items: items.slice(0, MENU_LIMIT) };
  }

  function operatorMenu(before: string, pos: number): { start: number; end: number; items: MenuItem[] } | null {
    const word = before.match(/[A-Za-z]+$/);
    if (!word) return null;
    const partial = word[0];
    if (partial.length < 2) return null;
    const start = pos - partial.length;
    const prev = before[start - 1] ?? '';
    if (/[A-Za-z0-9_]/.test(prev)) return null;
    const matches = OPERATORS.filter((op) => op.toLowerCase().startsWith(partial.toLowerCase()));
    if (!matches.length) return null;
    const items = matches.map((op) => ({ label: OPERATOR_PARAMS[op], insert: OPERATOR_PARAMS[op] }));
    return { start, end: pos, items };
  }

  function caretCoords(ta: HTMLTextAreaElement, index: number): { left: number; top: number } {
    let mirror = caretMirror;
    if (!mirror || !mirror.isConnected) {
      mirror = document.createElement('div');
      const cs = getComputedStyle(ta);
      mirror.style.cssText = [
        'position:absolute', 'visibility:hidden', 'white-space:pre-wrap',
        'word-wrap:break-word', 'overflow-wrap:break-word', 'overflow:hidden',
        'box-sizing:border-box', `font-family:${cs.fontFamily}`,
        `font-size:${cs.fontSize}`, `font-weight:${cs.fontWeight}`,
        `letter-spacing:${cs.letterSpacing}`, `line-height:${cs.lineHeight}`,
        `padding:${cs.padding}`, `border:${cs.borderTopWidth} solid transparent`,
      ].join(';');
      mirror.style.width = `${ta.clientWidth}px`;
      document.body.appendChild(mirror);
      caretMirror = mirror;
    }
    mirror.textContent = ta.value.slice(0, index);
    const marker = document.createElement('span');
    marker.textContent = '.';
    mirror.appendChild(marker);
    const left = marker.offsetLeft;
    const top = marker.offsetTop;
    mirror.removeChild(marker);
    return { left, top };
  }

  function predSelectionText(p: PredicateVocab): string {
    let s = `pred="${p.name}"`;
    p.args.forEach((slot, i) => {
      if (!slot.length) return;
      const attr = `arg${i + 1}`;
      const cond = slot.length > 1
        ? `(${slot.map((c) => `${attr}="${c}"`).join(' ∨ ')})`
        : `${attr}="${slot[0]}"`;
      s += ` ∧ ${cond}`;
    });
    return s;
  }

  function insertMenuItem(item: MenuItem) {
    const m = menu;
    if (!m) return;
    text = text.slice(0, m.start) + item.insert + text.slice(m.end);
    menu = null;
    scheduleTextCompile();
    const ta = taRef;
    if (ta) {
      requestAnimationFrame(() => {
        ta.focus();
        const caret = m.start + item.insert.length;
        ta.setSelectionRange(caret, caret);
      });
    }
  }

  function onTextareaKeydown(e: KeyboardEvent) {
    if (!menu || menu.items.length === 0) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      menuIndex = (menuIndex + 1) % menu.items.length;
      return;
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault();
      menuIndex = (menuIndex - 1 + menu.items.length) % menu.items.length;
      return;
    }
    if (e.key === 'Tab' || e.key === 'Enter') {
      e.preventDefault();
      const item = menu.items[menuIndex];
      if (item) insertMenuItem(item);
    }
  }

  // Keep the highlighted suggestion in view while navigating with the keyboard.
  $effect(() => {
    void menuIndex;
    void menu;
    if (!menu || !menuEl) return;
    const active = menuEl.querySelectorAll('button')[menuIndex];
    if (active) (active as HTMLElement).scrollIntoView({ block: 'nearest' });
  });

  let textTimer: ReturnType<typeof setTimeout> | null = null;
  function scheduleTextCompile() {
    if (textTimer) clearTimeout(textTimer);
    textTimer = setTimeout(async () => {
      if (!text.trim()) { sql = ''; return; }
      try {
        const resp = await api.postJson<{ model: IseqlModel; sql: string }>('/api/iseql/compile', {
          query: text,
          name: eventId.trim() || 'event',
          delta_unit: unit,
          condition,
        });
        model = normalizeModel(resp.model);
        sql = resp.sql;
        unit = unitFromModel(model);
        error = null;
      } catch (e) {
        sql = '';
        error = errorReason(e);
      }
    }, 400);
  }

  // Rewrite temporal projection attributes (st/et <-> sf/ef) when the
  // Time/Frames unit changes, so the query and SQL stay in the same domain.
  function swapTemporalAttrs(src: string, to: Unit): string {
    if (to === 'frames') {
      return src.replace(/\.st\b/g, '.sf').replace(/\.et\b/g, '.ef');
    }
    return src.replace(/\.sf\b/g, '.st').replace(/\.ef\b/g, '.et');
  }

  function onUnitChange(u: Unit) {
    if (u === unit) return;
    unit = u;
    if (view === 'text' && text.trim()) {
      text = swapTemporalAttrs(text, u);
      scheduleTextCompile();
    }
  }

  function onModelChange(m: IseqlModel) {
    model = m;
    scheduleModelCompile();
  }

  let modelTimer: ReturnType<typeof setTimeout> | null = null;
  function scheduleModelCompile() {
    if (modelTimer) clearTimeout(modelTimer);
    modelTimer = setTimeout(async () => {
      if (!model || !model.intervals?.length) { sql = ''; return; }
      try {
        const resp = await api.postJson<{ iseql: string; sql: string }>('/api/iseql/model/compile', { model, condition });
        text = resp.iseql;
        sql = resp.sql;
        unit = unitFromModel(model);
        error = null;
      } catch (e) {
        error = errorReason(e);
      }
    }, 300);
  }

  // -------------------------------------------------------------------------
  // save
  // -------------------------------------------------------------------------

  async function save() {
    error = null;
    status = null;
    if (!eventId.trim()) { error = 'Event ID is required.'; return; }
    let m = model;
    if (!m) {
      try {
        const resp = await api.postJson<{ model: IseqlModel }>('/api/iseql/compile', {
          query: text,
          name: eventId.trim(),
          delta_unit: unit,
          condition,
        });
        m = resp.model;
      } catch (e) {
        error = `Query does not compile: ${errorReason(e)}`;
        return;
      }
    }
    let iseqlText = (m as { iseql_text?: string }).iseql_text ?? '';
    if (!iseqlText) {
      try {
        const p = await api.postJson<{ iseql: string }>('/api/iseql/preview', { model: m });
        iseqlText = p.iseql || '';
      } catch { /* keep empty */ }
    }
    const full = { ...m, iseql_text: iseqlText };
    try {
      const updating = loadedId && loadedId === eventId.trim();
      if (updating) {
        await api.putJson(`/api/events/${eventId.trim()}`, {
          condition, model_json: JSON.stringify(full),
        });
      } else {
        await api.postJson('/api/events', {
          id: eventId.trim(), condition, model_json: JSON.stringify(full),
        });
      }
      loadedId = eventId.trim();
      status = updating ? `Updated event '${eventId.trim()}'.` : `Created event '${eventId.trim()}'.`;
      onSaved(eventId.trim());
    } catch (e) {
      error = `Failed to save event: ${(e as Error).message}`;
    }
  }

  function clear() {
    eventId = '';
    model = null;
    text = '';
    sql = '';
    error = null;
    status = null;
    unit = 'seconds';
  }

  function insertText(s: string) {
    const ta = taRef;
    if (!ta) { text = text + s; scheduleTextCompile(); return; }
    const start = ta.selectionStart ?? text.length;
    const end = ta.selectionEnd ?? text.length;
    text = text.slice(0, start) + s + text.slice(end);
    requestAnimationFrame(() => {
      ta.focus();
      ta.setSelectionRange(start + s.length, start + s.length);
    });
    scheduleTextCompile();
  }

  function symbolInsertText(s: string): string {
    if (s === 'π') return 'π_{';
    if (s === 'σ') return 'σ_{';
    return s;
  }

  function setView(v: 'text' | 'timeline') {
    view = v;
    if (v === 'text' && model) scheduleModelCompile();
  }

  const textareaClass =
    'h-full w-full resize-none rounded-lg border border-input bg-card p-2 font-mono text-xs leading-relaxed ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2';
</script>

<div class="flex min-h-0 flex-1 flex-col gap-2 overflow-hidden">
  <div class="flex shrink-0 flex-wrap items-center gap-2 rounded-lg border p-2">
    <Button type="button" size="icon" variant="ghost" class="h-8 w-8" title="Back to events" onclick={onBack}>⌂</Button>
    <Input class="w-48 font-mono" placeholder="event_name" value={eventId} onchange={(e) => (eventId = inputStr(e))} />

    <span class="text-xs text-muted-foreground">Mode</span>
    <div class="hidden h-7 items-center gap-0.5 rounded-lg border border-border p-0.5 text-xs sm:flex" data-tour="editor-mode">
      <button
        type="button"
        class={['h-full rounded-md px-2', view === 'text' ? 'bg-primary/10 font-medium text-foreground' : 'text-muted-foreground hover:bg-muted/40'].join(' ')}
        onclick={() => setView('text')}
      >Text</button>
      <button
        type="button"
        class={['h-full rounded-md px-2', view === 'timeline' ? 'bg-primary/10 font-medium text-foreground' : 'text-muted-foreground hover:bg-muted/40'].join(' ')}
        onclick={() => setView('timeline')}
      >Timeline</button>
    </div>

    <span class="text-xs text-muted-foreground">Unit</span>
    <span data-tour="editor-unit"><UnitToggle {unit} onUnitChange={onUnitChange} secondsLabel="Seconds" /></span>

    <div class="flex-1"></div>
    <Button type="button" variant="secondary" onclick={save} data-tour="editor-save">Save event</Button>
    <Button type="button" variant="ghost" onclick={clear}>Clear</Button>
  </div>

  {#if error}
    <div class="flex shrink-0 items-start gap-2.5 rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2.5" role="alert">
      <AlertTriangle class="mt-0.5 size-4 shrink-0 text-destructive" />
      <p class="min-w-0 flex-1 break-words text-xs leading-relaxed text-destructive">{error}</p>
      <button
        type="button"
        class="shrink-0 rounded-md px-1 text-destructive transition-colors hover:text-destructive/80"
        title="Dismiss"
        aria-label="Dismiss error"
        onclick={() => (error = null)}
      >✕</button>
    </div>
  {/if}
  {#if status}
    <div class="flex shrink-0 items-start gap-2.5 rounded-lg border border-success/40 bg-success/10 px-3 py-2.5" role="status">
      <CircleCheck class="mt-0.5 size-4 shrink-0 text-success" />
      <p class="min-w-0 flex-1 break-words text-xs leading-relaxed text-success">{status}</p>
    </div>
  {/if}

  {#if view === 'timeline'}
    <IseqlTimeline
      {condition}
      {model}
      {vocabulary}
      {unit}
      eventName={eventId.trim() || 'event'}
      onChange={onModelChange}
      {onOpenPredicate}
    />
  {:else}
    <div class="flex shrink-0 items-center gap-1 overflow-x-auto rounded-lg border px-2 py-1 text-xs text-muted-foreground">
      <span class="mr-1 shrink-0">Insert:</span>
      {#each SYMBOLS as s (s)}
        <button type="button" class="shrink-0 rounded-md border px-1.5 py-0.5 font-mono hover:bg-muted" onclick={() => insertText(symbolInsertText(s))} title={`Insert ${symbolInsertText(s)}`}>{s}</button>
      {/each}
      <span class="ml-2 hidden shrink-0 md:inline">
        π projection · σ selection · ∪/∖/∩ set ops · ∨ or · operators SP EF Bef Aft DJ RDJ LOJ ROJ with δ/ε/ζ/η/ρ
      </span>
    </div>

    <div class="grid min-h-0 flex-1 grid-cols-1 grid-rows-2 gap-2 lg:grid-cols-2 lg:grid-rows-1">
      <div class="flex min-h-0 flex-col rounded-lg border" data-tour="editor-query">
        <div class="shrink-0 border-b px-2 py-1 text-sm font-semibold">ISEQL Query</div>
        <div class="relative min-h-0 flex-1 p-2">
          <textarea
            bind:this={taRef}
            class={textareaClass}
            spellcheck="false"
            value={text}
            oninput={onTextInput}
            onclick={updatePredMenu}
            onkeyup={updatePredMenu}
            onkeydown={onTextareaKeydown}
            onblur={() => setTimeout(() => (menu = null), 150)}
          ></textarea>
          {#if menu}
            <div bind:this={menuEl} class="absolute z-20 max-h-56 w-72 overflow-y-auto rounded-xl border bg-popover py-1 shadow-float" style="left: {menuPos.left}px; top: {menuPos.top}px;">
              {#each menu.items as item, i (`${item.label}-${i}`)}
                <button
                  type="button"
                  class={['block w-full px-3 py-1 text-left font-mono text-xs', menuIndex === i ? 'bg-muted' : 'hover:bg-muted'].join(' ')}
                  onmousedown={(e) => e.preventDefault()}
                  onmouseenter={() => (menuIndex = i)}
                  onclick={() => insertMenuItem(item)}
                >{item.label}</button>
              {:else}
                <p class="px-3 py-2 text-xs text-muted-foreground">No suggestions.</p>
              {/each}
            </div>
          {/if}
        </div>
      </div>
      <div class="flex min-h-0 flex-col rounded-lg border">
        <div class="shrink-0 border-b px-2 py-1 text-sm font-semibold">SQL</div>
        <pre class="min-h-0 flex-1 overflow-auto p-2 font-mono text-xs leading-relaxed">{sql || '-- compile to see the SQL conversion'}</pre>
      </div>
    </div>
  {/if}
</div>

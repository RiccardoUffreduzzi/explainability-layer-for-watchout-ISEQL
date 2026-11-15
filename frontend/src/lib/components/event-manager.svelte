<script lang="ts">
  import { api } from '$lib/api';
  import { longpress } from '$lib/actions/longpress';
  import Input from '$lib/components/ui/input.svelte';
  import CountBadge from '$lib/components/ui/count-badge.svelte';
  import DeleteHint from '$lib/components/delete-hint.svelte';
  import { askConfirm } from '$lib/confirm.svelte';
  import type { Condition, EventTypeInfo } from '$lib/types';

  type Props = {
    condition: Condition;
    onOpen: (id: string) => void;
    onNew: () => void;
  };
  let { condition, onOpen, onNew }: Props = $props();

  let events = $state<EventTypeInfo[]>([]);
  let search = $state('');
  let error = $state<string | null>(null);
  let loading = $state(false);
  let ctxMenu = $state<{ x: number; y: number; id: string } | null>(null);

  async function load() {
    loading = true;
    error = null;
    try {
      const resp = await api.get<{ events: EventTypeInfo[] }>(`/api/events?condition=${condition}`);
      events = resp.events;
    } catch (e) {
      error = `Failed to load events: ${(e as Error).message}`;
    } finally {
      loading = false;
    }
  }

  $effect(() => { load(); });

  const filtered = $derived(
    events.filter((e) => e.id.toLowerCase().includes(search.toLowerCase()))
  );

  async function remove(e: EventTypeInfo) {
    if (!(await askConfirm(`Delete event '${e.id}' for condition ${condition}?`, { title: 'Delete event' }))) return;
    try {
      await api.del(`/api/events/${e.id}?condition=${condition}`);
      await load();
    } catch (err) {
      error = `Failed to delete event: ${(err as Error).message}`;
    }
  }

  async function removeById(id: string) {
    const e = events.find((x) => x.id === id);
    if (e) await remove(e);
  }
</script>

<div class="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto pt-1">
  {#if error}<p class="text-sm text-destructive">{error}</p>{/if}

  <div class="flex items-center gap-2">
    <span class="text-sm font-semibold">Events</span>
    <CountBadge filtered={filtered.length} total={events.length} filtering={search.trim() !== ''} />
    <Input class="h-7 flex-1 font-mono text-xs" placeholder="Search events…" value={search} oninput={(e) => (search = (e.currentTarget as HTMLInputElement).value)} />
    <button type="button" class="rounded border px-1.5 py-0.5 text-xs text-muted-foreground hover:bg-muted" title="Add event" onclick={onNew} data-tour="events-config-new-event">＋</button>
  </div>
  <DeleteHint />

  <div class="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-3" data-tour="events-config-list">
    {#each filtered as e (e.id)}
      <div
        role="button"
        tabindex="0"
        class="group cursor-pointer select-none touch-callout-none rounded-md border p-2 transition-colors hover:border-primary/50 hover:bg-muted/40"
        onclick={() => onOpen(e.id)}
        onkeydown={(ev) => { if (ev.key === 'Enter') onOpen(e.id); }}
        oncontextmenu={(ev) => { ev.preventDefault(); ctxMenu = { x: ev.clientX, y: ev.clientY, id: e.id }; }}
        use:longpress={{ onLongPress: (ev) => { ctxMenu = { x: ev.clientX, y: ev.clientY, id: e.id }; } }}
        title="Click to edit"
      >
        <span class="min-w-0 truncate font-mono text-sm font-medium">{e.id}</span>
      </div>
    {:else}
      <p class="col-span-full text-sm text-muted-foreground">
        {loading ? 'Loading events…' : 'No events yet. Create your first one.'}
      </p>
    {/each}
  </div>
</div>

{#if ctxMenu}
  <div class="fixed inset-0 z-50" role="presentation" onclick={() => (ctxMenu = null)} oncontextmenu={(e) => { e.preventDefault(); ctxMenu = null; }}></div>
  <div class="fixed z-50 w-44 rounded-xl border bg-popover py-1 text-xs shadow-float" style="left: {ctxMenu.x}px; top: {ctxMenu.y}px">
    <button type="button" class="block w-full px-3 py-1 text-left hover:bg-muted" onclick={() => { removeById(ctxMenu!.id); ctxMenu = null; }}>Delete</button>
  </div>
{/if}

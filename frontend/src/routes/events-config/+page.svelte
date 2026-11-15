<script lang="ts">
  import { onMount } from 'svelte';
  import Tabs from '$lib/components/ui/tabs.svelte';
  import TabsList from '$lib/components/ui/tabs-list.svelte';
  import TabsTrigger from '$lib/components/ui/tabs-trigger.svelte';
  import TabsContent from '$lib/components/ui/tabs-content.svelte';
  import EventEditor from '$lib/components/event-editor.svelte';
  import EventManager from '$lib/components/event-manager.svelte';
  import RelationConfigurator from '$lib/components/relation-configurator.svelte';
  import AudioSettings from '$lib/components/audio-settings.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import ThemeToggle from '$lib/components/ui/theme-toggle.svelte';
  import { ArrowLeft } from 'lucide-svelte';
  import type { Condition } from '$lib/types';
  import { registerTourSteps, startTour, hasSeenTour, tour, type TourStep } from '$lib/tour.svelte';
  import { backendStatus } from '$lib/backend-status.svelte';

  let active = $state('predicates');
  let condition = $state<Condition>('A');
  let editing = $state(false);
  let activeId = $state<string | null>(null);
  let mode = $state<'new' | 'open'>('new');
  let predicateFocus = $state<{ modality: 'visual' | 'audio'; name: string } | null>(null);

  const CONFIG_TOUR: TourStep[] = [
    { target: '', title: 'Events Configuration', body: 'Here you define the building blocks of your events: visual relations, audio classes, and the ISEQL events that combine them.' },
    { target: 'events-config-tabs', title: 'Two tabs', body: 'Predicates (visual relations + audio classes) and Events (ISEQL). Define predicates first, then author events.' },
    { target: 'events-config-visual', title: 'Visual predicates', body: 'Relations the VLM can detect, e.g. running(person). Click a row to edit; right-click (desktop) or long-press (touch) to delete.' },
    { target: 'events-config-audio', title: 'Audio predicates', body: 'Audio classes, e.g. gunshot. Click to edit synonyms; right-click or long-press to delete.' },
    { target: 'events-config-events-tab', title: 'Author events', body: 'Switch to the Events (ISEQL) tab to author events. This is where you create new events, write ISEQL as text or on a timeline, and choose seconds or frames.', action: () => { active = 'events'; } },
    { target: 'events-config-new-event', title: 'Create a new event', body: 'Click + to create a new ISEQL event. The editor then walks you through text/timeline mode, units, the query, and the timeline canvas.', action: () => { active = 'events'; } },
    { target: 'events-config-list', title: 'Event list', body: 'Existing events appear here. Click to edit; right-click (desktop) or long-press (touch) to delete.', action: () => { active = 'events'; } },
  ];

  onMount(() => {
    registerTourSteps(CONFIG_TOUR, 'config');
  });

  let initialized = false;
  $effect(() => {
    if (backendStatus.ready && !initialized) {
      initialized = true;
      if (!hasSeenTour('config') && !tour.active) startTour(CONFIG_TOUR, 'config');
    }
  });
</script>

<div class="mx-auto flex h-dvh w-full max-w-7xl flex-col gap-3 p-4">
  <header class="flex items-center justify-between">
    <div>
      <h1 class="text-lg font-semibold">Events Configuration</h1>
      <p class="text-xs text-muted-foreground">
        Define predicates (relations and audio classes) first, then author ISEQL events that use them.
      </p>
    </div>
    <div class="flex items-center gap-2">
      <ThemeToggle showLabel />
      <Button href="/" variant="outline" size="sm"><ArrowLeft /> Back to analysis</Button>
    </div>
  </header>

  {#if backendStatus.ready}
    <Tabs bind:value={active} class="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border bg-card/50 shadow-soft">
    <TabsList class="shrink-0 border-b px-2 py-1" data-tour="events-config-tabs">
      <TabsTrigger value="predicates">Predicates</TabsTrigger>
      <TabsTrigger value="events" data-tour="events-config-events-tab">Events (ISEQL)</TabsTrigger>
    </TabsList>

    {#if active === 'predicates'}
      <TabsContent value="predicates" class="flex min-h-0 flex-1 flex-col gap-3 overflow-hidden p-3">
        <section class="flex min-h-0 flex-1 flex-col rounded-lg border bg-card p-2" data-tour="events-config-visual">
          <div class="flex min-h-0 flex-1 flex-col">
            <RelationConfigurator focusRelation={predicateFocus?.modality === 'visual' ? predicateFocus.name : null} onFocused={() => (predicateFocus = null)} />
          </div>
        </section>
        <section class="flex min-h-0 flex-1 flex-col rounded-lg border bg-card p-2" data-tour="events-config-audio">
          <div class="flex min-h-0 flex-1 flex-col">
            <AudioSettings />
          </div>
        </section>
      </TabsContent>
    {/if}

    {#if active === 'events'}
      <TabsContent value="events" class="flex min-h-0 flex-1 flex-col gap-2 overflow-hidden p-2">
        <div class="flex shrink-0 flex-wrap items-center gap-2">
          <span class="text-sm text-muted-foreground">Condition:</span>
          {#each [
            { id: 'A' as Condition, label: 'A · Visual', hint: 'VLM + ISEQL (visual only)' },
            { id: 'B' as Condition, label: 'B · Audio', hint: 'PANNs + ISEQL (audio only)' },
            { id: 'C' as Condition, label: 'C · Multimodal', hint: 'visual + audio via set operations (∪/∖/∩)' },
          ] as c}
            <button
              type="button"
              title={c.hint}
              class={[
                'rounded-md border px-3 py-1 text-sm',
                condition === c.id ? 'border-primary bg-primary/10 font-medium' : 'text-muted-foreground hover:bg-muted/40',
              ].join(' ')}
              onclick={() => { condition = c.id; editing = false; }}
            >
              {c.label}
            </button>
          {/each}
        </div>

        <div class="flex min-h-0 flex-1 flex-col overflow-hidden">
          {#if editing}
            <EventEditor
              condition={condition}
              initialId={activeId}
              mode={mode}
              onBack={() => (editing = false)}
              onSaved={() => { activeId = null; editing = false; }}
              onOpenPredicate={(name, modality) => { editing = false; predicateFocus = { modality, name }; active = 'predicates'; }}
            />
          {:else}
            <EventManager
              condition={condition}
              onNew={() => { activeId = null; mode = 'new'; editing = true; }}
              onOpen={(id) => { activeId = id; mode = 'open'; editing = true; }}
            />
          {/if}
        </div>
      </TabsContent>
    {/if}
    </Tabs>
  {/if}
</div>

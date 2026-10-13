<script lang="ts">
  import { onMount } from 'svelte';
  import { browser } from '$app/environment';
  import { api, ApiError } from '$lib/api';
  import { openLogStream } from '$lib/sse';
  import { APP_NAME, APP_VERSION } from '$lib/app';
  import type {
    AnalysisRecord,
    AnalysisStartResponse,
    AnalysisStatusResponse,
    AudioConfig,
    Condition,
    Deltas,
    DetectionResult,
    EventTypeInfo,
    EventTypesResponse,
    LogEvent,
    SchemaResponse,
    VlmConfig,
  } from '$lib/types';

  import AppSidebar from '$lib/components/app-sidebar.svelte';
  import VideoUploader from '$lib/components/video-uploader.svelte';
  import VlmConfigForm from '$lib/components/vlm-config-form.svelte';
  import AudioConfigForm from '$lib/components/audio-config-form.svelte';
  import ConditionSelector from '$lib/components/condition-selector.svelte';
  import EventPicker from '$lib/components/event-picker.svelte';
  import LogConsole from '$lib/components/log-console.svelte';
  import ResultsTable from '$lib/components/results-table.svelte';
  import ObjectMemoryViewer from '$lib/components/object-memory-viewer.svelte';

  import Card from '$lib/components/ui/card.svelte';
  import CardHeader from '$lib/components/ui/card-header.svelte';
  import CardTitle from '$lib/components/ui/card-title.svelte';
  import CardContent from '$lib/components/ui/card-content.svelte';
  import Tabs from '$lib/components/ui/tabs.svelte';
  import TabsList from '$lib/components/ui/tabs-list.svelte';
  import TabsTrigger from '$lib/components/ui/tabs-trigger.svelte';
  import TabsContent from '$lib/components/ui/tabs-content.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import { Play, AlertTriangle, Square } from 'lucide-svelte';

  import UnitToggle from '$lib/components/unit-toggle.svelte';
  import type { Unit } from '$lib/types';
  import { registerTourSteps, startTour, hasSeenTour, tour, type TourStep } from '$lib/tour.svelte';
  import { askConfirm } from '$lib/confirm.svelte';
  import { backendStatus, markBackendDown } from '$lib/backend-status.svelte';

  const LANDING_TOUR: TourStep[] = [
    { target: '', title: 'Welcome to WATCHOUT ISEQL', body: 'This guided tour walks you through the app. Use Next / Back to move around, or Skip to close it at any time. You can reopen it anytime with the ? button at the bottom right.' },
    { target: 'landing-video', title: 'Upload a video', body: 'Start here: upload the surveillance video you want to analyze.' },
    { target: 'landing-condition', title: 'Pick an ablation condition', body: 'A = visual only, B = audio only, C = visual + audio. This controls which models run.' },
    { target: 'landing-config', title: 'Model settings', body: 'Configure the VLM (conditions A/C) and audio model (conditions B/C) used for detection.' },
    { target: 'landing-deltas', title: 'Operator parameters', body: 'Fine-tune the δ/ε/ζ/η/ρ parameters for each event operator, in seconds or frames.' },
    { target: 'landing-start', title: 'Run the analysis', body: 'Click Start analysis to detect events from the uploaded video.' },
    { target: 'landing-results', title: 'Review the results', body: 'Detected events appear here with a searchable table and a video player. Click or tap a row to play the video from that event start to end.', action: () => { rightTab = 'results'; } },
    { target: 'landing-events-config', title: 'Define your events', body: 'Use Events Configuration to author your own ISEQL events, visual relations and audio classes. You can delete any item by right-clicking (desktop) or long-pressing (touch).' },
  ];

  function convertValues(values: Deltas, from: Unit, to: Unit, fps: number): Deltas {
    if (from === to || fps <= 0) return values;
    return Object.fromEntries(
      Object.entries(values).map(([k, v]) => {
        if (typeof v !== 'number') return [k, v];
        return [k, to === 'frames' ? Math.round(v * fps) : Math.round((v / fps) * 100) / 100];
      })
    );
  }

  let video = $state<File | null>(null);
  let condition = $state<Condition>('A');
  let availableProviders = $state<string[]>([]);
  let availableAudioProviders = $state<string[]>(['panns', 'huggingface']);
  let vlmConfig = $state<VlmConfig>({
    provider: 'mistral',
    model: 'ministral-14b-2512',
    grid_rows: 2,
    grid_cols: 4,
    vlm_delay: 3.0,
    max_retries: 10,
    embed_provider: 'huggingface',
    embed_model: 'google/siglip-base-patch16-224',
    memory_n: 3,
    memory_top_k: 5,
  });
  let audioConfig = $state<AudioConfig>({
    provider: 'panns',
    model: 'CNN14',
    quantization: 'none',
    window: 2.5,
    hop: 1.25,
  });
  let sidebarCollapsed = $state(browser ? window.matchMedia('(max-width: 639px)').matches : false);
  let deltas = $state<Deltas>({});
  let eventTypes = $state<EventTypesResponse>({ A_visual: [], B_audio_only: [], C_audio_visual: [] });

  function collectDefaultDeltas(et: EventTypesResponse): Deltas {
    const out: Deltas = {};
    for (const key of ['A_visual', 'B_audio_only', 'C_audio_visual'] as const) {
      for (const e of et[key] ?? []) {
        Object.assign(out, e.default_deltas ?? {});
      }
    }
    return out;
  }
  const defaultDeltas = $derived(collectDefaultDeltas(eventTypes));

  let analysisId = $state<string | null>(null);
  let showMemory = $state(false);
  let stage = $state<string>('idle');
  let logs = $state<LogEvent[]>([]);
  let result = $state<DetectionResult | null>(null);
  let error = $state<string | null>(null);
  let busy = $state(false);
  let detecting = $state(false);

  let previousAnalyses = $state<AnalysisRecord[]>([]);
  let detectedFps = $state(0);
  let analysisDone = $state(false);
  let lastConfigSnapshot = $state('');
  let unit = $state<Unit>('seconds');
  let rightTab = $state<'logs' | 'results'>('logs');

  $effect(() => {
    if (stage === 'done') {
      rightTab = 'results';
    } else if (stage !== 'idle') {
      rightTab = 'logs';
    }
  });

  let closeSse: (() => void) | null = null;

  function convertDeltasUnit(from: Unit, to: Unit): void {
    if (from === to) return;
    deltas = convertValues(deltas, from, to, detectedFps);
  }

  const defaultDeltasForUnit = $derived(
    convertValues(defaultDeltas, 'seconds', unit, detectedFps)
  );

  function takeConfigSnapshot(): string {
    return JSON.stringify({
      condition, vlm_provider: vlmConfig.provider, vlm_model: vlmConfig.model,
      grid_rows: vlmConfig.grid_rows, grid_cols: vlmConfig.grid_cols,
      audio_provider: audioConfig.provider, audio_model: audioConfig.model,
    });
  }

  function onlyDeltasChanged(): boolean {
    return takeConfigSnapshot() === lastConfigSnapshot && analysisDone && !!analysisId;
  }

  // Reset restart shortcut when non-delta config changes
  $effect(() => {
    if (stage !== 'done') return;
    const snap = takeConfigSnapshot();
    if (snap && lastConfigSnapshot) {
      analysisDone = snap === lastConfigSnapshot;
    }
  });

  async function refreshAnalysisList() {
    try {
      previousAnalyses = await api.get<AnalysisRecord[]>('/api/analysis/list');
    } catch { /* non-fatal */ }
  }

  async function deleteAnalysis(id: string) {
    if (!(await askConfirm('Delete this analysis? Its video, detections, and object memory will be removed.', { title: 'Delete analysis' }))) return;
    try {
      await api.post(`/api/analysis/${id}/delete`);
    } catch { /* non-fatal */ }
    if (analysisId === id) reset();
    await refreshAnalysisList();
  }

  const RESET_ACTIVE_STAGES = ['queued', 'vlm', 'interval', 'audio', 'audio_interval', 'detection'];
  const resetDisabled = $derived(busy || RESET_ACTIVE_STAGES.includes(stage));

  async function resetDatabase() {
    if (!(await askConfirm('Clear analysis data? This deletes all analyses and detections. Your settings and events are kept.', { title: 'Clear analysis data' }))) return;
    try {
      await api.post('/api/db/reset');
      reset();
      await refreshAnalysisList();
    } catch (e) {
      error = `Failed to reset database: ${(e as Error).message}`;
    }
  }

  onMount(() => {
    registerTourSteps(LANDING_TOUR, 'landing');
  });

  let initialized = false;
  $effect(() => {
    if (backendStatus.ready && !initialized) {
      initialized = true;
      if (!hasSeenTour('landing') && !tour.active) startTour(LANDING_TOUR, 'landing');
      loadInitialData();
    }
  });

  async function loadInitialData() {
    try {
      eventTypes = await api.get<EventTypesResponse>('/api/events/types');
      deltas = { ...collectDefaultDeltas(eventTypes) };
    } catch (e) {
      initialized = false;
      markBackendDown();
      error = `Failed to load event types: ${(e as Error).message}`;
    }
    try {
      const schema = await api.get<SchemaResponse>('/api/schema');
      availableProviders = schema.available_providers || [];
      availableAudioProviders = schema.available_audio_providers || ['panns', 'huggingface'];
    } catch { /* non-fatal */ }
    try {
      const cfg = await api.get<{ sections: Record<string, object> }>('/api/config');
    } catch { /* non-fatal */ }
    await refreshAnalysisList();
  }

  function appendLog(stage: string, message: string) {
    logs = [...logs, { ts: Date.now() / 1000, stage, message }];
  }
  function clearLogs() { logs = []; }
  function reset() {
    if (closeSse) { closeSse(); closeSse = null; }
    analysisId = null;
    stage = 'idle';
    result = null;
    error = null;
    logs = [];
    analysisDone = false;
  }

  function handleVideoChange(f: File | null) {
    if (f && f === video) return;
    if (analysisId || analysisDone || stage !== 'idle' || detectedFps) {
      reset();
      lastConfigSnapshot = '';
      detectedFps = 0;
    }
    video = f;
  }

  function getAllEventIds(): string[] {
    if (condition === 'A') return eventTypes.A_visual.map(e => e.id);
    if (condition === 'B') return eventTypes.B_audio_only.map(e => e.id);
    return eventTypes.C_audio_visual.map(e => e.id);
  }

  function eventTypesForCondition(): EventTypeInfo[] {
    if (condition === 'A') return eventTypes.A_visual;
    if (condition === 'B') return eventTypes.B_audio_only;
    return eventTypes.C_audio_visual;
  }

  function loadAnalysis(item: AnalysisRecord) {
    reset();
    analysisId = item.id;
    condition = item.condition as Condition;
    stage = item.stage;
    detectedFps = item.sampling_rate ?? 0;

    if (item.vlm_provider) {
      vlmConfig = {
        provider: item.vlm_provider,
        model: item.model ?? '',
        grid_rows: item.grid_rows ?? 2,
        grid_cols: item.grid_cols ?? 4,
        vlm_delay: item.vlm_delay ?? 0.0,
        max_retries: item.max_retries ?? 3,
        embed_provider: item.embed_provider ?? 'huggingface',
        embed_model: item.embed_model ?? 'google/siglip-base-patch16-224',
        memory_n: item.memory_n ?? 3,
        memory_top_k: item.memory_top_k ?? 5,
      };
    }
    if (item.audio_provider) {
      audioConfig = {
        provider: item.audio_provider,
        model: item.audio_model ?? '',
        quantization: item.audio_quantization ?? 'none',
        window: item.audio_window ?? 2.5,
        hop: item.audio_hop ?? 1.25,
      };
    }
    if (item.deltas) {
      deltas = { ...item.deltas };
      unit = item.delta_unit === 'frames' ? 'frames' : 'seconds';
    }

    appendLog('info', `>>> Loaded previous analysis ${item.id} (condition ${item.condition}, stage ${item.stage})`);
    if (item.stage === 'done') {
      lastConfigSnapshot = takeConfigSnapshot();
      analysisDone = true;
      setTimeout(() => runAllDetections(), 300);
    } else {
      appendLog('warning', `Analysis is not complete (stage: ${item.stage}). Detection may not be available.`);
    }
  }

  async function startAnalysis() {
    if (!video) {
      error = 'Please choose a video file first.';
      return;
    }
    if (analysisId) { reset(); }

    busy = true;
    error = null;
    appendLog('queued', `>>> Submitting ${video.name} (${(video.size / 1024 / 1024).toFixed(1)} MB)  [condition ${condition}]`);

    const form = new FormData();
    form.append('video', video);
    form.append('condition', condition);
    form.append('vlm_provider', vlmConfig.provider);
    form.append('model', vlmConfig.model);
    form.append('grid_rows', String(vlmConfig.grid_rows));
    form.append('grid_cols', String(vlmConfig.grid_cols));
    form.append('vlm_delay', String(vlmConfig.vlm_delay));
    form.append('max_retries', String(vlmConfig.max_retries));
    form.append('embed_provider', vlmConfig.embed_provider);
    form.append('embed_model', vlmConfig.embed_model);
    form.append('memory_n', String(vlmConfig.memory_n));
    form.append('memory_top_k', String(vlmConfig.memory_top_k));
    form.append('audio_provider', audioConfig.provider);
    form.append('audio_model', audioConfig.model);
    form.append('audio_quantization', audioConfig.quantization);
    form.append('audio_window', String(audioConfig.window));
    form.append('audio_hop', String(audioConfig.hop));

    try {
      const resp = await api.postForm<AnalysisStartResponse>('/api/analysis/start', form);
      analysisId = resp.analysis_id;
      stage = resp.stage;
      detectedFps = resp.sampling_rate;
      lastConfigSnapshot = takeConfigSnapshot();
      analysisDone = false;
      appendLog('queued', `analysis_id = ${analysisId} (condition ${resp.condition})`);
      await refreshAnalysisList();

      closeSse = openLogStream(
        `/api/analysis/${analysisId}/logs`,
        (evt) => {
          appendLog(evt.stage, evt.message);
          if (evt.stage && evt.stage !== 'queued' && evt.stage !== 'done' && evt.stage !== 'failed') {
            stage = evt.stage;
          }
        },
        async () => {
          stage = 'done';
          busy = false;
          analysisDone = true;
          appendLog('done', '>>> Run finished, running detection on all events...');
          try {
            const s = await api.get<AnalysisStatusResponse>(`/api/analysis/${analysisId}/status`);
            stage = s.stage;
          } catch { /* ignore */ }
          await refreshAnalysisList();
          runAllDetections();
        },
        (err) => {
          stage = 'failed';
          busy = false;
          appendLog('failed', `SSE error: ${err.message}`);
          refreshAnalysisList();
        },
        {
          getStatus: () => api.get<AnalysisStatusResponse>(`/api/analysis/${analysisId}/status`),
          onReconnect: (attempt) => {
            appendLog('info', `>>> Stream disconnected, reconnecting... (attempt ${attempt})`);
          },
        },
      );
    } catch (e) {
      busy = false;
      if (e instanceof ApiError) {
        error = `${e.status}: ${typeof e.body === 'string' ? e.body : JSON.stringify(e.body)}`;
      } else {
        error = (e as Error).message;
      }
      appendLog('failed', `Start failed: ${error}`);
    }
  }

  async function runAllDetections() {
    if (!analysisId || stage !== 'done') return;
    const events = getAllEventIds();
    if (events.length === 0) return;

    detecting = true;
    result = null;
    error = null;
    appendLog('detection', `>>> Auto-detecting all ${events.length} events for condition ${condition}`);

    const allRows: Array<Record<string, unknown>> = [];
    for (const evt of events) {
      try {
        const r = await api.postJson<DetectionResult>(
          `/api/analysis/${analysisId}/detect`,
          { event_type: evt, deltas, unit }
        );
        for (const row of r.rows) {
          allRows.push({ Event: evt, ...row });
        }
      } catch (e) {
        appendLog('failed', `Detection query failed for '${evt}': ${(e as Error).message}`);
      }
    }
    result = { analysis_id: analysisId!, event_type: 'all', condition: condition, rows: allRows };
    appendLog('detection', `<<< ${allRows.length} total row(s) across ${events.length} events.`);
    detecting = false;
  }

  const canStart = $derived(video !== null && !busy);
  const canStop = $derived(busy);

  function triggerAnalysis() {
    if (onlyDeltasChanged()) {
      runAllDetections();
    } else {
      startAnalysis();
    }
  }

  async function stopAnalysis() {
    if (!analysisId) return;
    try {
      await api.post(`/api/analysis/${analysisId}/stop`);
      busy = false;
      appendLog('info', '>>> Analysis stopped by user');
    } catch (e) {
      appendLog('failed', `Stop request failed: ${(e as Error).message}`);
    }
  }
</script>

<div class="flex h-dvh w-full overflow-hidden bg-background text-foreground">
  <AppSidebar
    currentStage={stage}
    {previousAnalyses}
    {analysisId}
    {loadAnalysis}
    onDeleteAnalysis={deleteAnalysis}
    onResetDb={resetDatabase}
    {resetDisabled}
    collapsed={sidebarCollapsed}
    onToggle={() => (sidebarCollapsed = !sidebarCollapsed)}
  />

  <main class="flex flex-1 flex-col gap-4 overflow-y-auto p-4 lg:overflow-hidden">
    <div class="grid grid-cols-1 gap-4 lg:min-h-0 lg:flex-1 lg:grid-cols-12 lg:grid-rows-[minmax(0,1fr)]">
      <section class="col-span-12 flex flex-col gap-4 overflow-y-auto pr-1 lg:col-span-5">
        <Button href="/events-config" variant="outline" class="w-full" data-tour="landing-events-config">
          Events Configuration →
        </Button>

        <Card data-tour="landing-video">
          <CardHeader><CardTitle>1. Video</CardTitle></CardHeader>
          <CardContent>
            <VideoUploader file={video} onChange={handleVideoChange} disabled={busy} />
          </CardContent>
        </Card>

        <Card data-tour="landing-condition">
          <CardHeader><CardTitle>2. Ablation condition</CardTitle></CardHeader>
          <CardContent>
            <ConditionSelector
              value={condition}
              onChange={(c) => { condition = c; }}
              disabled={busy}
            />
          </CardContent>
        </Card>

        <Card data-tour="landing-config">
          <CardHeader><CardTitle>3. VLM (conditions A and C)</CardTitle></CardHeader>
          <CardContent class="space-y-4">
            <VlmConfigForm
              value={vlmConfig}
              onChange={(v) => (vlmConfig = v)}
              disabled={busy || condition === 'B'}
              availableProviders={availableProviders}
              {detectedFps}
            />
            {#if condition === 'B'}
              <p class="text-xs text-muted-foreground">
                Condition B does not use the VLM. These settings are ignored.
              </p>
            {/if}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>4. Audio (conditions B and C)</CardTitle></CardHeader>
          <CardContent>
            <AudioConfigForm
              value={audioConfig}
              onChange={(v) => (audioConfig = v)}
              disabled={busy || condition === 'A'}
              availableProviders={availableAudioProviders}
            />
            {#if condition === 'A'}
              <p class="text-xs text-muted-foreground">
                Condition A does not use audio. These settings are ignored.
              </p>
            {/if}
          </CardContent>
        </Card>

        <Card data-tour="landing-deltas">
          <CardHeader class="flex flex-row items-center justify-between">
            <CardTitle>5. Parameters</CardTitle>
            <div class="flex shrink-0 items-center gap-1.5 sm:order-4">
            <span class="text-xs text-muted-foreground">Unit</span>
            <UnitToggle {unit} onUnitChange={(u) => { convertDeltasUnit(unit, u); unit = u; }} />
            </div>
          </CardHeader>
          <CardContent>
            <EventPicker
              condition={condition}
              deltas={deltas}
              eventTypes={eventTypesForCondition()}
              defaultDeltas={defaultDeltasForUnit}
              onChangeDeltas={(d) => (deltas = d)}
              disabled={busy}
              unit={unit}
              fps={detectedFps}
            />
          </CardContent>
        </Card>

        <div class="flex gap-2" data-tour="landing-start">
          {#if canStop}
            <Button class="flex-1" variant="destructive" onclick={stopAnalysis}>
              <Square class="size-4" /> Stop analysis
            </Button>
          {:else if onlyDeltasChanged()}
            <Button class="flex-1" variant="secondary" onclick={triggerAnalysis}>
              <Play class="size-4" /> Restart analysis (query only)
            </Button>
          {:else if analysisDone && canStart}
            <Button class="flex-1" onclick={triggerAnalysis}>
              <Play class="size-4" /> Restart analysis
            </Button>
          {:else}
            <Button class="flex-1" onclick={triggerAnalysis} disabled={!canStart}>
              <Play class="size-4" /> Start analysis
            </Button>
          {/if}
        </div>

        {#if error}
          <div class="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
            <AlertTriangle class="size-4 shrink-0" />
            <p class="break-all">{error}</p>
          </div>
        {/if}
      </section>

      <section class="col-span-12 flex flex-col lg:min-h-0 lg:col-span-7">
        <Tabs bind:value={rightTab} class="flex h-[75dvh] min-h-0 flex-col overflow-hidden rounded-md border lg:h-auto lg:flex-1">
          <TabsList class="shrink-0 border-b px-2 py-1">
            <TabsTrigger value="logs">Logs</TabsTrigger>
            <TabsTrigger value="results">Results</TabsTrigger>
          </TabsList>
          <TabsContent value="logs" class="mt-0 flex min-h-0 flex-1 flex-col overflow-hidden">
            <LogConsole entries={logs} onClear={clearLogs} />
          </TabsContent>
          <TabsContent value="results" class="mt-0 flex min-h-0 flex-1 flex-col overflow-hidden">
            <div class="flex min-h-0 flex-1 flex-col" data-tour="landing-results">
              <ResultsTable result={result} running={detecting} error={null}
                unit={unit}
                analysisId={analysisId}
                fps={detectedFps}
                onMemory={() => (showMemory = true)}
                onUnitChange={(u) => { convertDeltasUnit(unit, u); unit = u; }} />
            </div>
          </TabsContent>
        </Tabs>
      </section>
    </div>
  </main>

  {#if showMemory && analysisId}
    <div
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      role="presentation"
      onclick={(e) => { if (e.target === e.currentTarget) showMemory = false; }}
      onkeydown={(e) => { if (e.key === 'Escape') showMemory = false; }}
    >
      <div class="flex h-[85dvh] w-full max-w-4xl flex-col rounded-lg border bg-background shadow-xl">
        <header class="flex items-center justify-between border-b px-4 py-3">
          <div>
            <h2 class="text-sm font-semibold">Object Memory</h2>
            <p class="text-xs text-muted-foreground">Analysis <span class="font-mono">{analysisId}</span></p>
          </div>
          <div class="flex items-center gap-2">
            <a
              href={`/memory/${analysisId}`}
              class="rounded border border-input bg-background px-2.5 py-1 text-xs font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            >
              Open full page
            </a>
            <button
              type="button"
              title="Close"
              class="rounded border border-input bg-background px-2.5 py-1 text-xs font-medium text-muted-foreground hover:bg-accent hover:text-foreground"
              onclick={() => (showMemory = false)}
            >
              ✕
            </button>
          </div>
        </header>
        <div class="flex min-h-0 flex-1 flex-col p-4">
          <ObjectMemoryViewer analysisId={analysisId} />
        </div>
      </div>
    </div>
  {/if}
</div>

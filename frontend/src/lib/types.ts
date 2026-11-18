export type Condition = 'A' | 'B' | 'C';

export type AnalysisStage =
  | 'queued'
  | 'vlm'
  | 'interval'
  | 'audio'
  | 'detection'
  | 'done'
  | 'failed';

export interface LogEvent {
  ts: number;
  stage: string;
  message: string;
  [k: string]: unknown;
}

export interface AnalysisStartRequest {
  condition: Condition;
  vlm_provider: string;
  model: string;
  grid_rows: number;
  grid_cols: number;
  sampling_rate: number;
}

export interface AnalysisStartResponse {
  analysis_id: string;
  condition: Condition;
  stage: AnalysisStage;
  frame_rate: number;
  sampling_rate: number;
}

export interface AnalysisStatusResponse {
  id: string;
  condition: Condition;
  stage: AnalysisStage;
  counters: Record<string, number>;
}

export interface EventTypeInfo {
  id: string;
  delta_visual: string | null;
  delta_audio: string | null;
  epsilon_visual: string | null;
  epsilon_audio: string | null;
  eta_visual: string | null;
  eta_audio: string | null;
  zeta_visual: string | null;
  zeta_audio: string | null;
  rho_visual: string | null;
  rho_audio: string | null;
  default_deltas?: Record<string, number | string>;
  condition?: string;
  model_json?: string | null;
}

export interface EventRegistryResponse {
  events: EventTypeInfo[];
}

export interface EventTypesResponse {
  A_visual: EventTypeInfo[];
  B_audio_only: EventTypeInfo[];
  C_audio_visual: EventTypeInfo[];
}

export interface SchemaResponse {
  app: string;
  version: string;
  conditions: Condition[];
  available_providers: string[];
  available_audio_providers: string[];
  tables: Record<string, string>;
  events: {
    A_visual: string[];
    B_audio_only: string[];
    C_audio_visual: string[];
  };
}

export interface DetectionResult {
  analysis_id: string;
  event_type: string;
  condition: Condition;
  rows: Array<Record<string, unknown>>;
}

export interface VlmConfig {
  provider: string;
  model: string;
  grid_rows: number;
  grid_cols: number;
  sampling_rate: number;
  vlm_delay: number;
  max_retries: number;
  embed_provider: string;
  embed_model: string;
  memory_n: number;
  memory_top_k: number;
}

export interface PromptOverrides {
  relation_classids?: [string, string][];
  relation_descriptions?: Record<string, string>;
}

export interface AudioConfig {
  provider: string;
  model: string;
  quantization: string;
  window: number;
  hop: number;
}

export interface AnalysisRecord {
  id: string;
  video_filename: string;
  condition: string;
  stage: string;
  frame_rate?: number;
  sampling_rate: number;
  created_at: string;
  completed_at?: string;
  vlm_provider?: string;
  model?: string;
  grid_rows?: number;
  grid_cols?: number;
  vlm_delay?: number;
  max_retries?: number;
  embed_provider?: string;
  embed_model?: string;
  memory_n?: number;
  memory_top_k?: number;
  audio_provider?: string;
  audio_model?: string;
  audio_quantization?: string;
  audio_window?: number;
  audio_hop?: number;
  deltas?: Record<string, number | string> | null;
  delta_unit?: string;
}

export const DEFAULT_AUDIO_CLASSES = [
  'shout',
  'impact',
  'gunshot_or_explosion',
  'engine',
  'tire_squeal',
  'glass_breaking',
  'horn',
  'skidding',
];

export const DEFAULT_AUDIO_KEYWORDS: Record<string, string[]> = {
  shout: ['shout', 'yell', 'scream'],
  impact: ['impact', 'thump', 'thud', 'bang', 'slam', 'smash', 'crash', 'punch', 'hit'],
  gunshot_or_explosion: ['gunshot', 'gunfire', 'artillery_fire', 'artillery', 'explosion', 'explosive', 'firework', 'boom', 'burst', 'pop'],
  engine: ['engine', 'vehicle', 'car', 'vroom'],
  tire_squeal: ['tire', 'tyre', 'tire_squeal', 'screech', 'squeal'],
  skidding: ['skidding', 'skid'],
  glass_breaking: ['glass', 'glass_breaking', 'shatter', 'shattering'],
  horn: ['horn', 'honk', 'honking'],
};

export type Deltas = Record<string, number | string>;

export type Unit = 'seconds' | 'frames';

export interface ObjectMemoryEntry {
  id: number;
  frame: number;
  class: string;
  blocks: number[];
  description: string;
  document: string;
}

export interface ObjectMemoryStats {
  total: number;
  frame_min: number | null;
  frame_max: number | null;
  per_class: Record<string, number>;
}

export interface ObjectMemoryResponse {
  items: ObjectMemoryEntry[];
  count: number;
  total: number;
}

// ---------------------------------------------------------------------------
// AppConfig store section shapes + default templates. These templates populate
// the settings editor forms; the user reviews/edits them and SAVES them to the
// AppConfig store (the backend has no hardcoded defaults).
// ---------------------------------------------------------------------------

export interface RelationVocabConfig {
  relation_classids: [string, string][];
  relation_descriptions: Record<string, string>;
}

export const DEFAULT_RELATION_VOCAB_TEMPLATE: RelationVocabConfig = {
  relation_classids: [
    ['running', '(PersonID)'],
    ['enter_or_exit_vehicle', '(PersonID, VehicleID)'],
    ['carrying', '(PersonID, ObjectID)'],
    ['physical_altercation', '(PersonID, PersonID)'],
    ['vehicle_collision', '(VehicleID)'],
    ['gunshot_visible', '(PersonID)'],
    ['explosion_visible', '(VehicleID∨ObjectID)'],
  ],
  relation_descriptions: {
    running: "The person's body is in a running posture: legs visibly apart, arms extended away from the body, or the person is clearly moving fast. WALKING is NOT running. Look at leg and arm positions carefully.",
    enter_or_exit_vehicle: "The person is getting into or out of the DRIVER'S position. For a car, van, or truck this is the front-left door (driver door); for a motorcycle it is the driver seat. Report only driver-position entry/exit, NOT passengers using a rear or front-passenger door, and NOT a person merely standing near or leaning on the vehicle.",
    carrying: "The person is holding, carrying, or transporting any object of class 'object' (package, suitcase, bag, backpack). Report for ANY person touching or holding a transportable item, even briefly.",
    physical_altercation: 'Two or more people are involved in aggressive behavior: fighting, pushing, hitting, punching, making aggressive gestures, or throwing objects at each other. Include IDs of all people involved.',
    vehicle_collision: 'A vehicle has visible collision damage: broken windshield, dented hood or doors, deployed airbags, smoke from the hood, or another object embedded in the vehicle.',
    gunshot_visible: 'A person is holding or firing a gun: visible muzzle flash, gun in hand, recoil motion, or smoke from the barrel.',
    explosion_visible: 'A visible explosion: fireball, large smoke cloud, debris flying through the air, or shattered windows. Report the VehicleID or nearest object ID.',
  },
};

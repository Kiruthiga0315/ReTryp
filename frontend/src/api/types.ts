/** Shared API types. Mirrors the FastAPI response models in backend/app/schemas.py. */

export type Provenance = "LIVE" | "CACHED" | "REFERENCE" | "SIMULATED" | "UNAVAILABLE";

/** Where the running instance's data comes from. Shown as the header badge. */
export type DataStatus = "live" | "reference" | "unavailable";

export interface Place {
  code: string;
  name: string;
  city: string;
  country: string;
  timezone: string;
  latitude: number;
  longitude: number;
}

export interface TripSummary {
  id: string;
  reference: string;
  name: string;
  purpose: string | null;
  traveller_id: string;
  traveller_name: string;
  origin_code: string;
  destination_code: string;
  origin_city: string;
  destination_city: string;
  starts_at_utc: string;
  ends_at_utc: string;
  starts_at_local: string;
  ends_at_local: string;
  status: string;
  status_label: string;
  segment_count: number;
  hotel_count: number;
  ground_count: number;
  disruption_count: number;
  active_disruption_count: number;
  provenance: Provenance;
}

export interface JourneyPlace {
  code: string;
  name: string;
  city: string;
  country: string;
  timezone: string;
  kind: string;
  is_city: boolean;
  provenance: string;
}

export interface JourneyReason {
  code: string;
  label: string;
}

export interface JourneyOption {
  key: string;
  mode: string;
  mode_label: string;
  carrier_code: string | null;
  carrier_name: string | null;
  service_number: string | null;
  origin: string;
  destination: string;
  departure_utc: string;
  arrival_utc: string;
  departure_local: string;
  arrival_local: string;
  origin_tz: string;
  destination_tz: string;
  duration_minutes: number;
  cost_minor: number;
  cost_currency: string;
  cost_display: string;
  refundable: boolean;
  terminal: string | null;
  gate: string | null;
  platform: string | null;
  distance_km: number | null;
  note: string | null;
  provenance: Provenance;
}

export interface JourneyCoveragePair {
  origin: string;
  destination: string;
  origin_name: string;
  destination_name: string;
  label: string;
  detail: string | null;
}

export interface JourneyCoverage {
  rail_pairs: JourneyCoveragePair[];
  rail_source: string | null;
  rail_valid_from: string | null;
  rail_valid_to: string | null;
}

export interface JourneyBridge {
  via: string;
  via_name: string;
  via_city: string;
  hops: number;
  carriers: string[];
}

export interface TransitNode {
  osm_id: string;
  name: string;
  kind: "rail" | "bus";
  kind_label: string;
  lat: number;
  lon: number;
  operator: string | null;
}

export interface TransitNearby {
  lat: number;
  lon: number;
  radius_km: number;
  provenance: Provenance;
  fetched_at: string | null;
  source: string;
  notes: string[];
  summary: { rail: number; bus: number; total: number };
  nodes: TransitNode[];
}

export interface NetworkCoverage {
  nodes: number;
  edges: number;
  flight_nodes: number;
  rail_nodes: number;
  live_pairs: number;
  sources: string[];
}

export interface NetworkSummary {
  coverage: NetworkCoverage;
  hubs: { code: string; degree: number }[];
  flight_provider: string;
  live_search: boolean;
  data_mode: string;
}

export interface JourneyItineraryLeg {
  key: string;
  mode: string;
  carrier_code: string;
  carrier_name: string;
  service_number: string;
  origin_code: string;
  destination_code: string;
  departure_local: string;
  arrival_local: string;
  duration_minutes: number;
  cost_minor: number;
  currency: string;
  provenance: Provenance;
  note: string;
}

export interface JourneyItinerary {
  key: string;
  hub_code: string;
  hub_name: string;
  hub_city: string;
  hub_country: string;
  hub_tz: string;
  legs: JourneyItineraryLeg[];
  departure_local: string;
  arrival_local: string;
  duration_minutes: number;
  duration_display: string;
  cost_minor: number;
  cost_display: string;
  connection_buffer_minutes: number;
  connection_required_minutes: number;
  connection_safety: string;
  provenance: Provenance;
  note: string;
}

export interface JourneyOptionsPayload {
  origin: string;
  destination: string;
  date: string;
  distance_km: number | null;
  provenance: Provenance;
  sources: string[];
  notes: string[];
  coverage: JourneyCoverage;
  connections: JourneyBridge[];
  itineraries: JourneyItinerary[];
  options: JourneyOption[];
}

export interface JourneyConnection {
  at: string;
  feasible: boolean;
  safety: string;
  safety_code: string;
  buffer_minutes: number;
  required_minutes: number;
  shortfall_minutes: number;
  note: string;
  mct_source: string;
  mct_verified_on: string;
}

export interface JourneyLegCheck {
  segment: Segment;
  connection: JourneyConnection | null;
  arrival_shift_minutes: number;
}

export interface JourneyIssue {
  kind: string;
  at: string;
  segment_id: string;
  service_number: string | null;
  shortfall_minutes: number;
  required_minutes: number;
  detail: string;
}

export interface JourneyCheck {
  trip_id: string;
  reference: string;
  checked_at_utc: string;
  segment_count: number;
  connection_count: number;
  healthy: boolean;
  issues: JourneyIssue[];
  legs: JourneyLegCheck[];
  hotel: string[];
  ground: string[];
}

export interface JourneySelection {
  service_key: string;
  origin: string;
  destination: string;
  date: string;
  mode: string;
}

export interface JourneyBuildRequest {
  name: string;
  reason: string;
  origin: string;
  destination: string;
  date: string;
  segments: JourneySelection[];
  disrupted_service_key?: string | null;
  disruption_kind?: string | null;
  delay_minutes?: number;
}

export interface JourneyBuildResult {
  trip: TripSummary;
  check: JourneyCheck;
  cycle: number | null;
  plans: RecoveryPlan[];
}

export interface Segment {
  id: string;
  sequence: number;
  segment_type: string;
  mode_label: string;
  carrier_code: string | null;
  carrier_name: string | null;
  service_number: string | null;
  origin: Place;
  destination: Place;
  scheduled_departure_utc: string;
  scheduled_arrival_utc: string;
  estimated_departure_utc: string | null;
  estimated_arrival_utc: string | null;
  actual_departure_utc: string | null;
  actual_arrival_utc: string | null;
  scheduled_departure_local: string;
  scheduled_arrival_local: string;
  effective_departure_local: string;
  effective_arrival_local: string;
  duration_minutes: number;
  duration_display: string;
  delay_minutes: number;
  arrival_delay_minutes: number;
  status: string;
  status_label: string;
  booking_reference: string | null;
  terminal: string | null;
  gate: string | null;
  platform: string | null;
  cabin: string | null;
  fare_class: string | null;
  cost_minor: number | null;
  cost_currency: string | null;
  refundable: boolean | null;
  distance_km: number | null;
  is_recovery: boolean;
  replaces_segment_id: string | null;
  provenance: Provenance;
  source: string | null;
  fetched_at: string | null;
}

export interface HotelStay {
  id: string;
  name: string;
  city_code: string;
  city_name: string;
  timezone: string;
  address: string;
  latitude: number | null;
  longitude: number | null;
  check_in_utc: string;
  check_out_utc: string;
  check_in_local: string;
  check_out_local: string;
  nights: number;
  rooms: number;
  guests: number;
  booking_reference: string | null;
  status: string;
  status_label: string;
  late_arrival_notice: boolean;
  cost_minor: number;
  cost_currency: string;
  refundable: boolean;
  provenance: Provenance;
  source: string | null;
  fetched_at: string | null;
}

export interface GroundTransport {
  id: string;
  mode: string;
  mode_label: string;
  provider_name: string;
  from_label: string;
  to_label: string;
  city_code: string;
  timezone: string;
  pickup_utc: string;
  dropoff_utc: string | null;
  pickup_local: string;
  booking_reference: string | null;
  status: string;
  status_label: string;
  cost_minor: number;
  cost_currency: string;
  provenance: Provenance;
  source: string | null;
  fetched_at: string | null;
}

export interface Disruption {
  id: string;
  trip_id: string;
  segment_id: string | null;
  hotel_id: string | null;
  ground_id: string | null;
  kind: string;
  kind_label: string;
  status: string;
  severity: string;
  title: string;
  detail: string;
  delay_minutes: number | null;
  delay_display: string | null;
  detected_at_utc: string;
  resolved_at_utc: string | null;
  provenance: Provenance;
  source: string | null;
  cycle: number;
  parent_disruption_id: string | null;
  payload: Record<string, unknown>;
}

export interface ImpactItem {
  kind: string;
  severity: string;
  title: string;
  detail: string;
  segment_id: string | null;
  hotel_id: string | null;
  ground_id: string | null;
  delta_minutes: number | null;
  delta_display: string | null;
  requires_action: boolean;
}

export interface ConnectionCheck {
  airport_code: string;
  label: string;
  feasible: boolean;
  safety: string;
  buffer_minutes: number;
  required_minutes: number;
  shortfall_minutes: number;
  mct_source: string;
  mct_verified_on: string;
  note: string;
}

export interface ImpactAssessment {
  severity: string;
  connection_safety: string;
  summary: string;
  final_arrival_shift_minutes: number;
  final_arrival_shift_display?: string | null;
  items: ImpactItem[];
  connections: ConnectionCheck[];
}

export interface PlanSegment {
  key: string;
  mode: string;
  carrier_code: string | null;
  carrier_name: string | null;
  service_number: string | null;
  origin_code: string;
  origin_name: string;
  origin_tz: string;
  destination_code: string;
  destination_name: string;
  destination_tz: string;
  departure_utc: string;
  arrival_utc: string;
  departure_local: string;
  arrival_local: string;
  duration_minutes: number;
  cost_minor: number;
  currency: string;
  refundable: boolean;
  cabin: string | null;
  fare_class: string | null;
  platform: string | null;
  terminal: string | null;
  gate: string | null;
  connection_safety: string;
  buffer_minutes: number | null;
  required_minutes: number | null;
  provenance: Provenance;
  note: string;
}

export interface PlanHotelChange {
  hotel_id: string;
  name: string;
  action: string;
  action_label?: string;
  detail: string;
  cost_minor: number;
  currency: string;
  provenance: Provenance;
}

export interface PlanGroundChange {
  key: string;
  mode: string;
  provider_name: string;
  from_label: string;
  to_label: string;
  city_code: string;
  timezone: string;
  pickup_utc: string;
  dropoff_utc: string;
  pickup_local: string;
  cost_minor: number;
  currency: string;
  provenance: Provenance;
  note: string;
  action: string;
  replaces?: string | null;
  original_pickup_utc?: string | null;
}

export interface CompensationEstimate {
  outcome: string;
  outcome_label?: string;
  basis: string;
  basis_label?: string;
  amount_minor: number;
  currency: string;
  amount_display: string;
  delay_minutes: number;
  distance_km: number | null;
  factors: string[];
  care_entitlements: string[];
  refund_available: boolean;
  regulation_reference: string;
  regulation_url: string;
  last_verified: string;
  disclaimer: string;
  route?: string;
  departure_country?: string;
  destination_country?: string;
}

export interface PlanAction {
  id: string;
  sequence: number;
  action_type: string;
  target_kind: string;
  target_id: string | null;
  description: string;
  status: string;
  status_label: string;
  cost_minor: number;
  currency: string;
  executed_at_utc: string | null;
  result: Record<string, unknown>;
}

export interface RecoveryPlan {
  plan_id: string;
  disruption_id: string;
  trip_id: string;
  cycle: number;
  label: string;
  title: string;
  summary: string;
  status: string;
  status_label: string;
  recommended: boolean;
  score: number;
  score_breakdown: Record<string, number>;
  decision_factors: string[];
  segments: PlanSegment[];
  hotel_changes: PlanHotelChange[];
  ground_transport: PlanGroundChange[];
  restrictions: string[];
  compensation: CompensationEstimate;
  arrival_utc: string;
  arrival_local: string;
  original_arrival_utc: string;
  original_arrival_local: string;
  arrival_delta_minutes: number;
  arrival_delta_display: string;
  total_duration_minutes: number;
  total_duration_display: string;
  additional_cost_minor: number;
  additional_cost_display: string;
  refund_estimate_minor: number;
  refund_estimate_display: string;
  currency: string;
  risk_level: string;
  connection_safety: string;
  changes_count: number;
  provenance: Provenance;
  explanation: string;
  explanation_source: string;
  explanation_version: number;
  approved_at_utc: string | null;
  actions: PlanAction[];
}

export interface DashboardPayload {
  trip: TripSummary;
  current_location: {
    label: string;
    detail: string;
    place_code: string | null;
    kind: string;
  } | null;
  next_segment: Segment | null;
  segments: Segment[];
  hotels: HotelStay[];
  ground: GroundTransport[];
  active_disruption: Disruption | null;
  active_disruptions: Disruption[];
  recovery_plan_count: number;
  recommended_plan: RecoveryPlan | null;
}

export interface RecoveryPayload {
  trip: TripSummary;
  disruption: Disruption | null;
  impact: ImpactAssessment | null;
  plans: RecoveryPlan[];
  comparison: ComparisonRow[];
  recommended_plan_id: string | null;
  active_plan: RecoveryPlan | null;
  empty_reason: string | null;
}

export interface ComparisonRow {
  plan_id: string;
  label: string;
  title: string;
  recommended: boolean;
  score: number;
  arrival_delta_minutes: number;
  arrival_delta_display: string;
  total_duration_minutes: number;
  total_duration_display: string;
  additional_cost_minor: number;
  additional_cost_display: string;
  risk_level: string;
  connection_safety: string;
  changes_count: number;
  mode: string;
  carrier: string | null;
  service_number: string | null;
  hotel_change_count: number;
  ground_change_count: number;
  hotel_summary: string;
  ground_summary: string;
  compensation_outcome: string;
  compensation_display: string;
  compensation_amount_minor: number;
  score_breakdown: Record<string, number>;
}

export interface Notification {
  id: string;
  trip_id: string | null;
  kind: string;
  title: string;
  body: string;
  severity: string;
  read: boolean;
  created_at_utc: string;
  provenance: Provenance;
  wording_source: string;
}

export interface WeatherSnapshot {
  place_code: string;
  condition: string;
  temp_c: number;
  wind_kph: number;
  precip_mm: number;
  visibility_km: number;
  provenance: Provenance;
  source: string;
  fetched_at: string | null;
  note: string;
}

export interface DelayPrior {
  subject: string;
  scope: string;
  on_time_pct: number;
  avg_delay_minutes: number;
  sample: string;
  source_name: string;
  source_url: string;
  verified_on: string;
  provenance: Provenance;
  note: string;
}

export interface TripContext {
  weather: WeatherSnapshot[];
  delay_priors: DelayPrior[];
  disclaimer: string;
}

export interface AuditEntry {
  id: string;
  trip_id: string | null;
  actor_id: string | null;
  actor_name: string;
  actor_role: string;
  action: string;
  action_label: string;
  subject_kind: string;
  subject_id: string | null;
  summary: string;
  detail: Record<string, unknown>;
  created_at_utc: string;
  created_at_local: string;
  provenance: Provenance;
}

export interface MonitoringState {
  trip_id: string;
  watching: boolean;
  cycle: number;
  active_plan_id: string | null;
  last_result: Record<string, unknown> | null;
}

export interface MonitoringResult {
  checked_at_utc: string;
  active_plan_id: string | null;
  cycle: number;
  segments_checked: number;
  healthy: boolean;
  broken_connections: {
    airport_code: string;
    segment_id: string;
    service_number: string | null;
    shortfall_minutes: number;
    required_minutes: number;
  }[];
  escalation?: { disruption_id: string; cycle: number; plans: string[] };
}

export interface UserProfile {
  id: string;
  email: string;
  full_name: string;
  role: "traveller" | "travel_manager" | "admin";
  phone: string | null;
  home_airport: string | null;
  preferred_airlines: string[];
  preferred_seat: string | null;
  preferred_cabin: string | null;
  hotel_preferences: Record<string, unknown>;
  ground_preferences: Record<string, unknown>;
  budget_currency: string;
  budget_minor: number | null;
  accessibility_needs: string | null;
  passport_masked: string | null;
  passport_nationality: string | null;
  passport_expiry: string | null;
  settings: UserSettings;
}

export interface UserSettings {
  notifications: Record<string, boolean>;
  currency: string;
  language: string;
  timezone: string;
  travel_preferences: Record<string, unknown>;
  privacy: Record<string, boolean>;
}

export interface DataSourceInfo {
  name: string;
  detail: string;
  loaded: boolean;
  provenance: Provenance;
  fetched_at: string | null;
  valid_from?: string | null;
  valid_to?: string | null;
}

export interface DataStatusInfo {
  mode: DataStatus;
  flight_provider: string;
  live_providers: string[];
  reference_loaded?: boolean;
  reference_fetched_at?: string | null;
  rail_loaded?: boolean;
  rail_valid_from?: string | null;
  rail_valid_to?: string | null;
  sources?: DataSourceInfo[];
  note: string;
}

export interface ProviderHealth {
  data_status: DataStatus;
  providers: ProviderStatus[];
  note: string;
}

export interface ProviderStatus {
  name: string;
  provider: string;
  configured: boolean;
  circuit: string;
  last_error: string | null;
}

export interface TripHistory {
  trip: TripSummary;
  disruptions: Disruption[];
  plans: RecoveryPlan[];
  recovery_performed: number;
  final_arrival_utc: string | null;
  extra_cost_minor: number;
  extra_cost_display: string;
  refund_estimate_minor: number;
  refund_display: string;
  /** The currency the two totals above are expressed in. */
  currency: string;
}

export interface BookingsPayload {
  trip: { id: string; reference: string; name: string; provenance: Provenance };
  flights: Segment[];
  trains: Segment[];
  ground_transport: GroundTransport[];
  other_transport: Segment[];
  hotels: HotelStay[];
  counts: Record<string, number>;
}

export interface TimelinePayload {
  trip: TripSummary;
  segments: Segment[];
  hotels: HotelStay[];
  ground: GroundTransport[];
}

export interface HelpAnswer {
  answer: string;
  source: string;
  prompt: string;
}

export interface ScenarioKind {
  value: string;
  label: string;
}

export interface ScenarioCatalog {
  kinds: ScenarioKind[];
  note: string;
}

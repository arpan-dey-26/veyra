import createClient, { type ClientOptions } from "openapi-fetch";

import type { components, paths } from "./schema";
import { readCookie, sessionMiddleware, CSRF_COOKIE } from "./session";

export type { components, paths };
export { readCookie, sessionMiddleware, CSRF_COOKIE, CSRF_HEADER } from "./session";

type Schemas = components["schemas"];
export type MetaResponse = Schemas["MetaResponse"];
export type ReadinessResponse = Schemas["ReadinessResponse"];
export type MeResponse = Schemas["MeResponse"];
export type UserOut = Schemas["UserOut"];
export type RegisterDonorRequest = Schemas["RegisterDonorRequest"];
export type RegisterResponse = Schemas["RegisterResponse"];
export type VerificationOut = Schemas["VerificationOut"];
export type DonorProfile = Schemas["DonorProfile"];
export type UpdateDonorProfileRequest = Schemas["UpdateDonorProfileRequest"];
export type RegistrationReference = Schemas["RegistrationReference"];
export type FacilityOut = Schemas["FacilityOut"];
export type CreateFacilityRequest = Schemas["CreateFacilityRequest"];
export type CreatedInvite = Schemas["CreatedInvite"];
export type InviteOut = Schemas["InviteOut"];
export type InvitePreview = Schemas["InvitePreview"];
// Phase 2: core blood network
export type SourceMeta = Schemas["SourceMeta"];
export type InventorySummary = Schemas["InventorySummary"];
export type InventoryRow = Schemas["InventoryRow"];
export type ComponentInfo = Schemas["ComponentInfo"];
export type BagOut = Schemas["BagOut"];
export type BagTrace = Schemas["BagTrace"];
export type BagEventOut = Schemas["BagEventOut"];
export type ChainStatus = Schemas["ChainStatus"];
export type DonorLookupResult = Schemas["DonorLookupResult"];
export type RecordDonationRequest = Schemas["RecordDonationRequest"];
export type DonationOut = Schemas["DonationOut"];
export type MyDonations = Schemas["MyDonations"];
export type MyDonation = Schemas["MyDonation"];
export type AvailabilityResponse = Schemas["AvailabilityResponse"];
export type AvailabilityItem = Schemas["AvailabilityItem"];
export type CreateBloodRequest = Schemas["CreateBloodRequest"];
export type BloodRequestOut = Schemas["BloodRequestOut"];
export type AllocatedBag = Schemas["AllocatedBag"];
export type BloodComponent = CreateBloodRequest["component"];
export type BloodGroup = CreateBloodRequest["blood_group"];
// Phase 3: dashboards & live network
export type FacilityDashboard = Schemas["FacilityDashboard"];
export type AdminDashboard = Schemas["AdminDashboard"];
export type ActivityItem = Schemas["ActivityItem"];
export type StatusCount = Schemas["StatusCount"];
export type DayCount = Schemas["DayCount"];
export type MovementDay = Schemas["MovementDay"];
export type ExpiryBucket = Schemas["ExpiryBucket"];
export type NetworkGraph = Schemas["NetworkGraph"];
export type NetworkNode = Schemas["NetworkNode"];
export type NetworkEdge = Schemas["NetworkEdge"];
// Phase 4: synthetic ML demand forecasting (prototype)
export type DemandForecast = Schemas["DemandForecast"];
export type ForecastSummary = Schemas["ForecastSummary"];
export type ForecastSummaryRow = Schemas["SummaryRow"];
export type ForecastPoint = Schemas["ForecastPointOut"];
export type DemandSignal = Schemas["DemandSignal"];
export type ModelCard = Schemas["ModelCard"];
// Phase 5: simulated IoT telemetry & cold chain (prototype)
export type TelemetryDevice = Schemas["DeviceOut"];
export type TelemetrySeries = Schemas["TelemetrySeries"];
export type TelemetryReading = Schemas["ReadingOut"];
export type TelemetrySummary = Schemas["TelemetrySummary"];
export type ColdChainReport = Schemas["ColdChainReport"];
export type ColdChainThresholds = Schemas["ThresholdsOut"];
export type MonitoredList = Schemas["MonitoredList"];
export type MonitoredBag = Schemas["MonitoredBag"];
export type SimulatorResult = Schemas["SimulatorResult"];
// Phase 6: operational intelligence (prototype; not clinical decisions)
export type OpsReason = Schemas["ReasonOut"];
export type OpsPriority = Schemas["PriorityOut"];
export type OpsRequest = Schemas["OpsRequest"];
export type OpsRequestList = Schemas["OpsRequestList"];
export type OpsRecommendation = Schemas["Recommendation"];
export type OpsCandidateBag = Schemas["CandidateBag"];
export type OpsPressureRow = Schemas["PressureRow"];
export type OpsFacilityPressure = Schemas["FacilityPressure"];
export type OpsRoute = Schemas["RouteOut"];
export type OpsRoutingOverview = Schemas["RoutingOverview"];
export type OpsAlert = Schemas["AlertOut"];
export type OpsAlerts = Schemas["AlertsOut"];
export type ChangePriorityBody = Schemas["ChangePriority"];
// Phase 7: simulated logistics (prototype; not real navigation or delivery guarantees)
export type Shipment = Schemas["ShipmentSummary"];
export type ShipmentDetail = Schemas["ShipmentDetail"];
export type ShipmentList = Schemas["ShipmentList"];
export type ShipmentRoute = Schemas["ShipmentRoute"];
export type ShipmentCheckpoint = Schemas["CheckpointOut"];
export type ShipmentEta = Schemas["EtaOut"];
export type ShipmentTimeline = Schemas["ShipmentTimeline"];
export type ShipmentTimelineEvent = Schemas["TimelineEvent"];
export type ShipmentTelemetry = Schemas["ShipmentTelemetry"];
export type ShipmentColdChainBag = Schemas["ColdChainBag"];
// Phase 8: compatibility reference, donation camps, bag QR scanning
export type CompatibilityMatrix = Schemas["CompatibilityMatrix"];
export type ComponentMatrix = Schemas["ComponentMatrix"];
export type CompatibilityCheck = Schemas["CompatibilityCheck"];
export type CampOut = Schemas["CampOut"];
export type CampList = Schemas["CampList"];
export type CampCreate = Schemas["CampCreate"];
export type CampUpdate = Schemas["CampUpdate"];
export type CampStats = Schemas["CampStats"];
export type CampDashboard = Schemas["CampDashboard"];
export type PublicCampOut = Schemas["PublicCampOut"];
export type PublicCampList = Schemas["PublicCampList"];
export type CampRegistrationOut = Schemas["RegistrationOut"];
export type CampRegistrationList = Schemas["RegistrationList"];
export type MyCampRegistration = Schemas["MyRegistration"];
export type MyCampRegistrations = Schemas["MyRegistrations"];
export type BagScanResult = Schemas["BagScanResult"];
export type BagQr = Schemas["BagQr"];
export type LogisticsResult = Schemas["LogisticsResult"];

/** A live event from `GET /api/v1/stream` (Server-Sent Events, fed by the outbox). */
export interface NetworkEvent {
  event_id: string;
  topic: string;
  aggregate_type: string;
  aggregate_id: string;
  created_at: string;
  [key: string]: unknown;
}

export type Role = "DONOR" | "HOSPITAL" | "BLOOD_BANK" | "ADMIN";

/** RFC 9457 problem body returned by every VEYRA API error. */
export interface ProblemDetails {
  type: string;
  title: string;
  status: number;
  code: string;
  detail: string;
  request_id: string | null;
  errors?: { loc: (string | number)[]; msg: string; type: string }[];
}

export function isProblem(value: unknown): value is ProblemDetails {
  return (
    typeof value === "object" &&
    value !== null &&
    "code" in value &&
    "status" in value &&
    typeof (value as { status: unknown }).status === "number"
  );
}

/** Field name → first error message, from a 422 problem (loc: ["body", "<field>"]). */
export function fieldErrors(problem: ProblemDetails | null | undefined): Record<string, string> {
  const out: Record<string, string> = {};
  for (const err of problem?.errors ?? []) {
    const field = err.loc[err.loc.length - 1];
    if (typeof field === "string" && !(field in out)) {
      out[field] = err.msg.replace(/^Value error, /, "");
    }
  }
  return out;
}

/**
 * Create a typed client. In the browser, use the same-origin base ("/"): Next.js proxies
 * /api/* to the API so auth cookies stay first-party. On the server, pass the internal URL.
 */
export function createVeyraClient(baseUrl = "/", options: Omit<ClientOptions, "baseUrl"> = {}) {
  return createClient<paths>({ baseUrl, credentials: "include", ...options });
}

export type VeyraClient = ReturnType<typeof createVeyraClient>;

/** Browser client: CSRF header + silent refresh-and-retry on 401. */
export function createBrowserClient(onSessionExpired?: () => void): VeyraClient {
  const client = createVeyraClient(typeof window === "undefined" ? "http://localhost" : "/");
  client.use(
    sessionMiddleware({
      getCsrfToken: () =>
        typeof document === "undefined" ? null : readCookie(document.cookie, CSRF_COOKIE),
      onSessionExpired,
    }),
  );
  return client;
}

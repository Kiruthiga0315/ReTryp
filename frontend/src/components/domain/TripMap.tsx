import { useEffect, useMemo } from "react";
import { MapContainer, Marker, Polyline, Popup, TileLayer, useMap } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import type { GroundTransport, HotelStay, RecoveryPlan, Segment, TransitNode } from "../../api/types";

/** OpenStreetMap tiles. No API key, no vendor styling. */
const TILE_URL = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";
const TILE_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

function pinIcon(colour: string, glyph: string, filled = false) {
  const background = filled ? colour : "#ffffff";
  const foreground = filled ? "#ffffff" : colour;
  return L.divIcon({
    className: "",
    iconSize: [26, 26],
    iconAnchor: [13, 13],
    html: `<span style="display:flex;align-items:center;justify-content:center;width:26px;height:26px;border-radius:50%;background:${background};border:2px solid ${colour};color:${foreground};font:600 12px/1 Inter,sans-serif;box-shadow:0 1px 3px rgba(14,22,33,.35)">${glyph}</span>`,
  });
}

const ICON_AIRPORT = pinIcon("#0e6f6a", "A", true);
const ICON_STATION = pinIcon("#1a5490", "S", true);
const ICON_HOTEL = pinIcon("#8a5a00", "H", true);
const ICON_CURRENT = pinIcon("#a8231c", "•", true);
const ICON_RAIL_NODE = pinIcon("#1a5490", "R", false);
const ICON_BUS_NODE = pinIcon("#5b6b7c", "B", false);

interface MapPoint {
  code: string;
  name: string;
  latitude: number;
  longitude: number;
  kind: "airport" | "station" | "hotel";
}

function FitBounds({ points }: { points: [number, number][] }) {
  const map = useMap();
  useEffect(() => {
    if (points.length === 0) return;
    if (points.length === 1) {
      map.setView(points[0], 11);
      return;
    }
    map.fitBounds(L.latLngBounds(points.map(([lat, lng]) => L.latLng(lat, lng))), {
      padding: [36, 36],
    });
  }, [map, points]);
  return null;
}

function MapClick({ onPick }: { onPick?: (lat: number, lon: number) => void }) {
  const map = useMap();
  useEffect(() => {
    if (!onPick) return;
    const handler = (event: L.LeafletMouseEvent) => onPick(event.latlng.lat, event.latlng.lng);
    map.on("click", handler);
    return () => {
      map.off("click", handler);
    };
  }, [map, onPick]);
  return null;
}

export function TripMap({
  segments,
  hotels,

  plan,
  currentPlaceCode,
  transitNodes,
  onPick,
}: {
  segments: Segment[];
  hotels: HotelStay[];
  ground: GroundTransport[];
  plan?: RecoveryPlan | null;
  currentPlaceCode?: string | null;
  transitNodes?: TransitNode[];
  onPick?: (lat: number, lon: number) => void;
}) {
  const { points, originalPath, recoveredPath } = useMemo(() => {
    const collected: MapPoint[] = [];
    const original: [number, number][] = [];

    for (const segment of segments) {
      const origin = segment.origin;
      const destination = segment.destination;
      if (origin?.latitude != null && origin?.longitude != null) {
        original.push([origin.latitude, origin.longitude]);
        if (!collected.some((point) => point.code === origin.code)) {
          collected.push({
            code: origin.code,
            name: origin.name,
            latitude: origin.latitude,
            longitude: origin.longitude,
            kind: origin.code.length > 3 ? "station" : "airport",
          });
        }
      }
      if (destination?.latitude != null && destination?.longitude != null) {
        original.push([destination.latitude, destination.longitude]);
        if (!collected.some((point) => point.code === destination.code)) {
          collected.push({
            code: destination.code,
            name: destination.name,
            latitude: destination.latitude,
            longitude: destination.longitude,
            kind: destination.code.length > 3 ? "station" : "airport",
          });
        }
      }
    }

    for (const hotel of hotels) {
      if (hotel.latitude != null && hotel.longitude != null) {
        collected.push({
          code: hotel.city_code,
          name: hotel.name,
          latitude: hotel.latitude,
          longitude: hotel.longitude,
          kind: "hotel",
        });
      }
    }

    // Ground transfers carry no coordinates of their own, so they do not add
    // map points; their pickups happen at places already plotted.

    // Recovered route: the replacement legs, which may use station codes such
    // as FRA_AIR that do not appear on the booked itinerary.
    const byCode = new Map(collected.map((point) => [point.code, point]));
    const resolve = (code: string): MapPoint | undefined => {
      const direct = byCode.get(code);
      if (direct) return direct;
      const base = code.split("_")[0];
      return byCode.get(base);
    };

    const recovered: [number, number][] = [];
    if (plan) {
      for (const leg of plan.segments) {
        const originPoint = resolve(leg.origin_code);
        const destinationPoint = resolve(leg.destination_code);
        if (originPoint) recovered.push([originPoint.latitude, originPoint.longitude]);
        if (destinationPoint) recovered.push([destinationPoint.latitude, destinationPoint.longitude]);
      }
    }

    return { points: collected, originalPath: original, recoveredPath: recovered };
  }, [segments, hotels, plan]);

  const centre: [number, number] =
    points.length > 0
      ? [
          points.reduce((sum, point) => sum + point.latitude, 0) / points.length,
          points.reduce((sum, point) => sum + point.longitude, 0) / points.length,
        ]
      : [50.0379, 8.5622];

  const bounds = points.map((point) => [point.latitude, point.longitude] as [number, number]);
  const current = points.find((point) => point.code === currentPlaceCode);

  return (
    <div className="map-shell">
      <MapContainer center={centre} zoom={5} scrollWheelZoom={false} style={{ height: "100%" }}>
        <TileLayer url={TILE_URL} attribution={TILE_ATTRIBUTION} />
        <FitBounds points={bounds} />
        <MapClick onPick={onPick} />

        {transitNodes
          ? transitNodes.map((node) => (
              <Marker
                key={`osm-${node.osm_id}`}
                position={[node.lat, node.lon]}
                icon={node.kind === "rail" ? ICON_RAIL_NODE : ICON_BUS_NODE}
              >
                <Popup>
                  <strong>{node.name}</strong>
                  <br />
                  <span style={{ color: "#64748b" }}>
                    {node.kind_label}
                    {node.operator ? ` · ${node.operator}` : ""} · OpenStreetMap
                  </span>
                </Popup>
              </Marker>
            ))
          : null}

        {originalPath.length > 1 ? (
          <Polyline
            positions={originalPath}
            pathOptions={{ color: "#64748b", weight: 3, dashArray: "6 6", opacity: 0.85 }}
          />
        ) : null}

        {recoveredPath.length > 1 ? (
          <Polyline
            positions={recoveredPath}
            pathOptions={{ color: "#0e6f6a", weight: 4, opacity: 0.95 }}
          />
        ) : null}

        {points.map((point) => (
          <Marker
            key={`${point.kind}-${point.code}-${point.name}`}
            position={[point.latitude, point.longitude]}
            icon={
              point.kind === "hotel"
                ? ICON_HOTEL
                : point.kind === "station"
                  ? ICON_STATION
                  : ICON_AIRPORT
            }
          >
            <Popup>
              <strong>{point.name}</strong>
              <br />
              <span style={{ color: "#64748b" }}>
                {point.kind === "hotel" ? "Hotel" : point.kind === "station" ? "Rail station" : "Airport"}
                {point.code ? ` · ${point.code}` : ""}
              </span>
            </Popup>
          </Marker>
        ))}

        {current ? (
          <Marker position={[current.latitude, current.longitude]} icon={ICON_CURRENT} zIndexOffset={500}>
            <Popup>
              <strong>Current position</strong>
              <br />
              <span style={{ color: "#64748b" }}>{current.name}</span>
            </Popup>
          </Marker>
        ) : null}
      </MapContainer>

      <div className="map-legend">
        <div className="map-legend__row">
          <span className="map-legend__swatch" style={{ borderTopColor: "#64748b", borderTopStyle: "dashed" }} />
          <span>Original route</span>
        </div>
        {recoveredPath.length > 1 ? (
          <div className="map-legend__row">
            <span className="map-legend__swatch" style={{ borderTopColor: "#0e6f6a" }} />
            <span>Recovered route</span>
          </div>
        ) : null}
        <div className="map-legend__row">
          <span className="map-legend__dot" style={{ background: "#0e6f6a" }} />
          <span>Airport</span>
        </div>
        <div className="map-legend__row">
          <span className="map-legend__dot" style={{ background: "#1a5490" }} />
          <span>Rail station</span>
        </div>
        {transitNodes && transitNodes.length > 0 ? (
          <>
            <div className="map-legend__row">
              <span className="map-legend__dot" style={{ background: "#1a5490" }} />
              <span>OSM rail station</span>
            </div>
            <div className="map-legend__row">
              <span className="map-legend__dot" style={{ background: "#5b6b7c" }} />
              <span>OSM bus stop</span>
            </div>
          </>
        ) : null}
        <div className="map-legend__row">
          <span className="map-legend__dot" style={{ background: "#8a5a00" }} />
          <span>Hotel</span>
        </div>
        <div className="map-legend__row">
          <span className="map-legend__dot map-legend__dot--current" />
          <span>Current position</span>
        </div>
      </div>
    </div>
  );
}

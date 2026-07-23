import { useEffect, useMemo } from "react";
import type { LatLngBoundsExpression } from "leaflet";
import { CircleMarker, MapContainer, Polyline, Popup, TileLayer, useMap } from "react-leaflet";
import type { StoreSummary } from "../types/cart";
import type { FulfillmentOption, RequestedLocation } from "../types/chat";

interface MappedStore {
  store: StoreSummary & { latitude: number; longitude: number };
  option: FulfillmentOption;
}

export interface FulfillmentMapProps {
  options: FulfillmentOption[];
  stores: StoreSummary[];
  requestedLocation: RequestedLocation | null;
}

function hasCoordinates(store: StoreSummary): store is StoreSummary & { latitude: number; longitude: number } {
  return Number.isFinite(store.latitude) && Number.isFinite(store.longitude);
}

function FitBounds({ bounds }: { bounds: LatLngBoundsExpression }): null {
  const map = useMap();
  useEffect(() => {
    map.fitBounds(bounds, { padding: [24, 24], maxZoom: 12 });
  }, [map, bounds]);
  return null;
}

export function FulfillmentMap({ options, stores, requestedLocation }: FulfillmentMapProps): JSX.Element {
  const mappedStores = useMemo(() => {
    const byId = new Map(
      stores.filter(hasCoordinates).map((store) => [store.store_id, store])
    );
    const bestByStore = new Map<string, MappedStore>();
    for (const option of options) {
      if (!option.store_id) continue;
      const store = byId.get(option.store_id);
      if (!store) continue;
      const existing = bestByStore.get(option.store_id);
      if (!existing || option.sellable_quantity > existing.option.sellable_quantity || option.channel === "selected_store") {
        bestByStore.set(option.store_id, { store, option });
      }
    }
    return [...bestByStore.values()];
  }, [options, stores]);

  const fallbackCenter: [number, number] = [45.0725, -93.4557];
  const points = useMemo<[number, number][]>(() => [
    ...(requestedLocation ? [[requestedLocation.latitude, requestedLocation.longitude] as [number, number]] : []),
    ...mappedStores.map(({ store }) => [store.latitude, store.longitude] as [number, number]),
  ], [mappedStores, requestedLocation]);
  const bounds = useMemo<LatLngBoundsExpression>(
    () => (points.length > 0 ? points : [fallbackCenter]),
    [points]
  );
  const bestAvailable = mappedStores
    .filter(({ option }) => option.sellable_quantity > 0)
    .sort((left, right) => (left.option.distance_miles ?? Number.POSITIVE_INFINITY) - (right.option.distance_miles ?? Number.POSITIVE_INFINITY))[0] ?? null;
  const connection: [number, number][] | null = requestedLocation && bestAvailable
    ? [
        [requestedLocation.latitude, requestedLocation.longitude],
        [bestAvailable.store.latitude, bestAvailable.store.longitude],
      ]
    : null;

  return (
    <div className="fulfillment-map-real" aria-label="Verified store location map">
      <MapContainer
        center={fallbackCenter}
        zoom={10}
        scrollWheelZoom={false}
        className="fulfillment-map-real__canvas"
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <FitBounds bounds={bounds} />

        {requestedLocation && (
          <CircleMarker
            center={[requestedLocation.latitude, requestedLocation.longitude]}
            radius={14}
            pathOptions={{ color: "#5836d6", fillColor: "#f1edff", fillOpacity: 0.3, weight: 3 }}
          >
            <Popup>
              <strong>Requested area</strong><br />
              {requestedLocation.label}
            </Popup>
          </CircleMarker>
        )}

        {mappedStores.map(({ store, option }) => {
          const available = option.sellable_quantity > 0;
          const markerColor = available ? "#159455" : "#e5484d";
          return (
            <CircleMarker
              key={store.store_id}
              center={[store.latitude, store.longitude]}
              radius={8}
              pathOptions={{ color: markerColor, fillColor: markerColor, fillOpacity: 0.9, weight: 3 }}
            >
              <Popup>
                <strong>{store.store_name}</strong><br />
                {option.channel === "selected_store" ? "Selected store" : "Nearby store"}<br />
                {store.city}{store.state ? `, ${store.state}` : ""}{store.postal_code ? ` ${store.postal_code}` : ""}<br />
                {available ? `${option.sellable_quantity} in stock` : "Out of stock"}
                {option.distance_miles !== null ? <><br />{option.distance_miles.toFixed(2)} miles away</> : null}
              </Popup>
            </CircleMarker>
          );
        })}

        {connection && (
          <Polyline
            positions={connection}
            pathOptions={{ color: "#7657e8", dashArray: "6 8", weight: 3, opacity: 0.9 }}
          >
            <Popup>Visual connection only — not a driving route.</Popup>
          </Polyline>
        )}
      </MapContainer>
      <p className="fulfillment-map-real__note">
        Markers use Scout&apos;s stored coordinates. The dashed line is a visual connection, not a driving route.
      </p>
    </div>
  );
}

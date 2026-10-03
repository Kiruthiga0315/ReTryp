import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import type { NetworkSummary, TransitNearby } from "../../api/types";
import type { UseQueryResult } from "@tanstack/react-query";
import { Card, CardBody, CardHeader } from "../ui/Card";
import { Chip, ProvenanceBadge } from "../ui/Badge";
import { Icon } from "../ui/Icon";
import { ErrorState, Skeleton } from "../ui/States";

/** What the connectivity graph and the OpenStreetMap transit layer reach.
 *
 * This is the honest answer to "how far does ReTryp's network actually go":
 * counts straight from the loaded datasets, plus an on-demand OpenStreetMap
 * harvest for rail stations and bus stops, which have no global code list.
 *
 * The transit harvest is driven from the map, so its result arrives as a prop
 * rather than being fetched twice.
 */
export function NetworkPanel({
  nearby,
  onPick,
}: {
  nearby: UseQueryResult<TransitNearby>;
  onPick: (lat: number, lon: number) => void;
}) {
  const network = useQuery({
    queryKey: ["journey-network"],
    queryFn: () => api.journeyNetwork(),
    staleTime: 5 * 60 * 1000,
  });

  if (network.isLoading) {
    return (
      <Card>
        <CardBody>
          <Skeleton height={16} width="40%" />
          <div style={{ height: "var(--s-3)" }} />
          <Skeleton height={72} />
        </CardBody>
      </Card>
    );
  }
  if (network.isError || !network.data) {
    return (
      <Card>
        <CardBody>
          <ErrorState
            title="Network coverage unavailable"
            message={(network.error as Error)?.message ?? "The graph did not answer."}
            onRetry={() => void network.refetch()}
          />
        </CardBody>
      </Card>
    );
  }

  const data: NetworkSummary = network.data;

  return (
    <Card>
      <CardHeader
        title="Network coverage"
        subtitle="What the loaded datasets can actually answer for"
        icon="Globe"
        actions={
          <Chip variant={data.live_search ? "done" : "info"} icon={data.live_search ? "Activity" : "Database"}>
            {data.live_search ? "Live search on" : "Catalogue only"}
          </Chip>
        }
      />
      <CardBody className="stack-4">
        <div className="grid grid-3">
          <Metric label="Places" value={data.coverage.nodes.toLocaleString()} />
          <Metric label="Routes" value={data.coverage.edges.toLocaleString()} />
          <Metric label="Airports" value={data.coverage.flight_nodes.toLocaleString()} />
          <Metric label="Rail hubs" value={data.coverage.rail_nodes.toLocaleString()} />
          <Metric label="Pairs seen live" value={data.coverage.live_pairs.toLocaleString()} />
          <Metric label="Flight provider" value={data.flight_provider} />
        </div>

        <div className="stack-2">
          <div className="small muted">Best-connected hubs</div>
          <div className="row row-2 wrap">
            {data.hubs.map((hub) => (
              <span key={hub.code} className="tag">
                {hub.code} · {hub.degree}
              </span>
            ))}
          </div>
        </div>

        <div className="stack-2">
          <div className="small muted">Datasets in this graph</div>
          <ul>
            {data.coverage.sources.map((source) => (
              <li key={source} className="small">
                {source}
              </li>
            ))}
          </ul>
        </div>

        <div className="stack-2">
          <div className="small muted">Rail stations and bus stops on the map</div>
          <p className="tiny muted">
            OpenStreetMap has no global code list for stations, so they are harvested as you look,
            not pre-loaded. Click the map to load what is near a point.
          </p>
          {nearby.isLoading ? (
            <Skeleton height={40} />
          ) : nearby.isError ? (
            <p className="small" style={{ color: "var(--c-disrupted)" }}>
              OpenStreetMap did not answer. Nothing is shown rather than approximated.
            </p>
          ) : nearby.data ? (
            <div className="stack-2">
              <div className="row row-2 wrap">
                <ProvenanceBadge value={nearby.data.provenance} />
                <Chip variant="info" icon="TrainFront">
                  {nearby.data.summary.rail} rail
                </Chip>
                <Chip variant="info" icon="BusFront">
                  {nearby.data.summary.bus} bus
                </Chip>
                <span className="tiny muted">{nearby.data.source}</span>
              </div>
              {nearby.data.notes.map((note) => (
                <p key={note} className="tiny muted">
                  {note}
                </p>
              ))}
              <div className="table-wrap" style={{ maxHeight: 220, overflowY: "auto" }}>
                <table className="table table--compact">
                  <thead>
                    <tr>
                      <th scope="col">Kind</th>
                      <th scope="col">Name</th>
                      <th scope="col">Operator</th>
                    </tr>
                  </thead>
                  <tbody>
                    {nearby.data.nodes.slice(0, 40).map((node) => (
                      <tr key={node.osm_id}>
                        <td>
                          <span className="row row-2">
                            <Icon name={node.kind === "rail" ? "TrainFront" : "BusFront"} size={14} />
                            {node.kind_label}
                          </span>
                        </td>
                        <td>{node.name}</td>
                        <td className="small muted">{node.operator ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : (
            <div className="row row-2 wrap">
              <button
                type="button"
                className="btn btn--ghost btn--sm"
                onClick={() => onPick(52.52, 13.405)}
              >
                Load around Berlin
              </button>
              <span className="tiny muted">Or click anywhere on the map.</span>
            </div>
          )}
        </div>
      </CardBody>
    </Card>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="stack-1">
      <div className="tiny muted">{label}</div>
      <div style={{ fontWeight: 600, fontSize: "var(--text-lg)" }}>{value}</div>
    </div>
  );
}

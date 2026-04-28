import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import * as d3 from "d3";
import { ArrowRightLeft, Clock3, Database, Route, TrendingUp } from "lucide-react";
import "./styles.css";

const isk = new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 2 });
const pct = new Intl.NumberFormat("en", { maximumFractionDigits: 1 });

function formatTime(value) {
  if (!value) return "";
  return new Intl.DateTimeFormat("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    day: "2-digit",
    month: "short",
    timeZone: "UTC",
  }).format(new Date(value));
}

function returnColor(route, maxReturnPct) {
  const maxReturn = Math.max(1, maxReturnPct);
  const normalized = Math.max(0, Math.min(1, route.totalReturnPct / maxReturn));
  return d3.interpolateGreens(0.35 + normalized * 0.6);
}

function useArbitrageData(params) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const query = new URLSearchParams(params).toString();

  useEffect(() => {
    let cancelled = false;
    setError("");
    fetch(`/api/arbitrages?${query}`)
      .then((response) => {
        if (!response.ok) return response.json().then((body) => Promise.reject(body.detail));
        return response.json();
      })
      .then((body) => {
        if (!cancelled) setData(body);
      })
      .catch((err) => {
        if (!cancelled) setError(String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [query]);

  return { data, error };
}

function normalizeLayout(nodes) {
  if (!nodes.length) return new Map();
  const xExtent = d3.extent(nodes, (node) => node.x);
  const yExtent = d3.extent(nodes, (node) => node.y);
  const pad = 72;
  const width = 1100;
  const height = 690;
  const x = d3.scaleLinear().domain(xExtent).range([pad, width - pad]);
  const y = d3.scaleLinear().domain(yExtent).range([height - pad, pad]);
  return new Map(nodes.map((node) => [node.systemId, { ...node, x: x(node.x), y: y(node.y) }]));
}

function drawArrow(ctx, from, to, size) {
  const angle = Math.atan2(to.y - from.y, to.x - from.x);
  ctx.save();
  ctx.translate(to.x, to.y);
  ctx.rotate(angle);
  ctx.beginPath();
  ctx.moveTo(0, 0);
  ctx.lineTo(-size, -size * 0.45);
  ctx.lineTo(-size, size * 0.45);
  ctx.closePath();
  ctx.fill();
  ctx.restore();
}

function distanceToSegment(point, a, b) {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const lengthSq = dx * dx + dy * dy;
  if (lengthSq === 0) return Math.hypot(point.x - a.x, point.y - a.y);
  const t = Math.max(0, Math.min(1, ((point.x - a.x) * dx + (point.y - a.y) * dy) / lengthSq));
  return Math.hypot(point.x - (a.x + t * dx), point.y - (a.y + t * dy));
}

function RouteMap({ data, selectedSnapshot, highlightedRoute, setHighlightedRoute }) {
  const canvasRef = useRef(null);
  const transformRef = useRef(d3.zoomIdentity);
  const positionedNodes = useMemo(() => normalizeLayout(data.nodes), [data.nodes]);
  const selectedMs = new Date(selectedSnapshot ?? data.summary.minTime).getTime();
  const maxReturnPct = data.summary.maxTotalReturnPct ?? 1;

  const visibleRoutes = useMemo(
    () =>
      data.routes.filter((route) => {
        const startMs = new Date(route.snapshotTime).getTime();
        const arrivalMs = new Date(route.arrivalSnapshotTime ?? route.arrivalTime).getTime();
        return startMs <= selectedMs && selectedMs <= arrivalMs;
      }),
    [data.routes, selectedMs],
  );

  const visibleNodeIds = new Set();
  visibleRoutes.forEach((route) => route.path.forEach((systemId) => visibleNodeIds.add(systemId)));
  const visibleNodes = [...positionedNodes.values()].filter((node) => visibleNodeIds.has(node.systemId));
  const routeEndpointIds = new Set();
  visibleRoutes.forEach((route) => {
    routeEndpointIds.add(route.fromSystem);
    routeEndpointIds.add(route.toSystem);
  });

  const profitScale = d3
    .scaleSqrt()
    .domain([0, Math.max(1, d3.max(visibleRoutes, (route) => route.profit) ?? 1)])
    .range([0.9, 4]);

  const draw = () => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const ratio = window.devicePixelRatio || 1;
    const width = Math.max(1, Math.floor(rect.width * ratio));
    const height = Math.max(1, Math.floor(rect.height * ratio));
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
    }

    const ctx = canvas.getContext("2d");
    const transform = transformRef.current;
    const xScale = rect.width / 1100;
    const yScale = rect.height / 690;
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, rect.width, rect.height);
    ctx.save();
    ctx.translate(transform.x, transform.y);
    ctx.scale(transform.k * xScale, transform.k * yScale);

    ctx.lineCap = "round";
    ctx.strokeStyle = "rgba(120, 157, 170, 0.075)";
    ctx.lineWidth = 0.45 / transform.k;
    ctx.beginPath();
    for (const edge of data.galaxyEdges) {
      const source = positionedNodes.get(edge.source);
      const target = positionedNodes.get(edge.target);
      if (!source || !target) continue;
      ctx.moveTo(source.x, source.y);
      ctx.lineTo(target.x, target.y);
    }
    ctx.stroke();

    ctx.fillStyle = "rgba(126, 213, 232, 0.28)";
    for (const node of positionedNodes.values()) {
      ctx.beginPath();
      ctx.arc(node.x, node.y, routeEndpointIds.has(node.systemId) ? 2.1 : 1.15, 0, Math.PI * 2);
      ctx.fill();
    }

    for (const route of visibleRoutes) {
      const color = returnColor(route, maxReturnPct);
      const isActive = highlightedRoute?.id === route.id;
      ctx.strokeStyle = color;
      ctx.fillStyle = color;
      ctx.globalAlpha = isActive ? 1 : 0.72;
      ctx.lineWidth = (isActive ? 5 : profitScale(route.profit)) / transform.k;
      for (let index = 0; index < route.path.length - 1; index += 1) {
        const source = positionedNodes.get(route.path[index]);
        const target = positionedNodes.get(route.path[index + 1]);
        if (!source || !target) continue;
        ctx.beginPath();
        ctx.moveTo(source.x, source.y);
        ctx.lineTo(target.x, target.y);
        ctx.stroke();
        drawArrow(ctx, source, target, 5 / transform.k);
      }
    }
    ctx.globalAlpha = 1;

    for (const node of visibleNodes) {
      const active =
        highlightedRoute &&
        (highlightedRoute.fromSystem === node.systemId || highlightedRoute.toSystem === node.systemId);
      const activeRoute = visibleRoutes.find((route) => route.fromSystem === node.systemId || route.toSystem === node.systemId);
      ctx.fillStyle = activeRoute ? returnColor(activeRoute, maxReturnPct) : "#6bd5ea";
      ctx.strokeStyle = "#eafcff";
      ctx.lineWidth = 1.2 / transform.k;
      ctx.beginPath();
      ctx.arc(node.x, node.y, node.isOrigin || node.isDestination ? 8 : 3.6, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
      if (active || node.routeCount > 1) {
        ctx.font = `${13 / transform.k}px Inter, sans-serif`;
        ctx.lineWidth = 5 / transform.k;
        ctx.strokeStyle = "#05090e";
        ctx.fillStyle = "#d9f9ff";
        ctx.strokeText(node.name, node.x + 11, node.y - 9);
        ctx.fillText(node.name, node.x + 11, node.y - 9);
      }
    }

    ctx.restore();
  };

  useEffect(() => {
    draw();
  });

  useEffect(() => {
    const canvas = d3.select(canvasRef.current);
    const zoom = d3.zoom().scaleExtent([0.45, 4]).on("zoom", (event) => {
      transformRef.current = event.transform;
      draw();
    });
    canvas.call(zoom);
    return () => canvas.on(".zoom", null);
  });

  function handlePointerMove(event) {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const transform = transformRef.current;
    const xScale = rect.width / 1100;
    const yScale = rect.height / 690;
    const point = {
      x: (event.clientX - rect.left - transform.x) / (transform.k * xScale),
      y: (event.clientY - rect.top - transform.y) / (transform.k * yScale),
    };
    const threshold = 10 / transform.k;
    let nearest = null;
    let nearestDistance = threshold;
    for (const route of visibleRoutes) {
      for (let index = 0; index < route.path.length - 1; index += 1) {
        const source = positionedNodes.get(route.path[index]);
        const target = positionedNodes.get(route.path[index + 1]);
        if (!source || !target) continue;
        const distance = distanceToSegment(point, source, target);
        if (distance < nearestDistance) {
          nearestDistance = distance;
          nearest = route;
        }
      }
    }
    if ((nearest?.id ?? null) !== (highlightedRoute?.id ?? null)) {
      setHighlightedRoute(nearest);
    }
  }

  return (
    <div className="map-shell">
      <canvas
        ref={canvasRef}
        aria-label="Arbitrage route map"
        role="img"
        onPointerMove={handlePointerMove}
        onPointerLeave={() => setHighlightedRoute(null)}
      />
      <div className="hover-panel">
        {highlightedRoute ? (
          <>
            <div className="panel-kicker">{formatTime(highlightedRoute.snapshotTime)} UTC</div>
            <strong>{highlightedRoute.itemName}</strong>
            <span>
              {positionedNodes.get(highlightedRoute.fromSystem)?.name ?? highlightedRoute.fromSystem} →{" "}
              {positionedNodes.get(highlightedRoute.toSystem)?.name ?? highlightedRoute.toSystem}
            </span>
            <span>{highlightedRoute.gateJumps} jumps · {pct.format(highlightedRoute.totalReturnPct)}% trade return</span>
            <b>{isk.format(highlightedRoute.profit)} ISK profit</b>
          </>
        ) : (
          <>
            <div className="panel-kicker">{visibleRoutes.length} active routes</div>
            <strong>{formatTime(selectedSnapshot)} UTC snapshot</strong>
            <span>Routes stay lit until their arrival snapshot.</span>
          </>
        )}
      </div>
    </div>
  );
}

function Timeline({ routes, snapshots, selectedSnapshot, setSelectedSnapshot, maxReturnPct }) {
  const ref = useRef(null);
  if (!routes.length || !snapshots.length) {
    return <div className="timeline-block"><div className="loading">No routes match the current filters.</div></div>;
  }
  const selectedIndex = Math.max(0, snapshots.indexOf(selectedSnapshot));
  const selected = snapshots[selectedIndex] ?? snapshots[0];

  function updateFromPointer(event) {
    const rect = ref.current.getBoundingClientRect();
    const t = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
    const nextIndex = Math.round(t * (snapshots.length - 1));
    setSelectedSnapshot(snapshots[nextIndex]);
  }

  const selectedPct = snapshots.length > 1 ? (selectedIndex / (snapshots.length - 1)) * 100 : 0;

  return (
    <div className="timeline-block">
      <div className="timeline-labels">
        <span>{formatTime(snapshots[0])}</span>
        <strong>
          Snapshot {selectedIndex + 1}/{snapshots.length}: {formatTime(selected)} UTC
        </strong>
        <span>{formatTime(snapshots[snapshots.length - 1])}</span>
      </div>
      <div
        ref={ref}
        className="timeline"
        onPointerDown={(event) => {
          event.currentTarget.setPointerCapture(event.pointerId);
          updateFromPointer(event);
        }}
        onPointerMove={(event) => {
          if (event.buttons) updateFromPointer(event);
        }}
      >
        {snapshots.map((snapshot, index) => {
          const left = snapshots.length > 1 ? (index / (snapshots.length - 1)) * 100 : 0;
          return <button key={snapshot} className="snapshot-tick" style={{ left: `${left}%` }} onClick={() => setSelectedSnapshot(snapshot)} aria-label={`Snapshot ${index + 1}`} />;
        })}
        {routes.map((route) => {
          const startIndex = Math.max(0, snapshots.indexOf(route.snapshotTime));
          const arrivalIndex = Math.max(startIndex, snapshots.indexOf(route.arrivalSnapshotTime ?? route.arrivalTime));
          const start = snapshots.length > 1 ? (startIndex / (snapshots.length - 1)) * 100 : 0;
          const end = snapshots.length > 1 ? (arrivalIndex / (snapshots.length - 1)) * 100 : start;
          const width = Math.max(0.8, end - start);
          const height = Math.min(96, 18 + Math.log10(Math.max(10, route.profit)) * 10);
          return <i key={route.id} style={{ left: `${start}%`, width: `${width}%`, height, background: returnColor(route, maxReturnPct) }} title={`${route.itemName}: ${pct.format(route.totalReturnPct)}% return`} />;
        })}
        <button className="timeline-thumb" style={{ left: `${selectedPct}%` }} aria-label="Selected time" />
      </div>
    </div>
  );
}

function Stat({ icon: Icon, label, value }) {
  return (
    <div className="stat">
      <Icon size={18} />
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function App() {
  const [source, setSource] = useState("all");
  const [limit, setLimit] = useState(3000);
  const [rank, setRank] = useState("time");
  const [minProfit, setMinProfit] = useState(0);
  const [selectedSnapshot, setSelectedSnapshot] = useState(null);
  const [highlightedRoute, setHighlightedRoute] = useState(null);
  const { data, error } = useArbitrageData({ source, limit, min_profit: minProfit, feasible_only: true, rank });

  useEffect(() => {
    if (data?.snapshots?.length) setSelectedSnapshot(data.snapshots[0]);
  }, [data?.snapshots]);

  const routes = data?.routes ?? [];
  const snapshots = data?.snapshots ?? [];

  return (
    <main>
      <header>
        <div>
          <p className="eyebrow">EVE market route intelligence</p>
          <h1>Arbitrage Vector Map</h1>
        </div>
        <div className="controls">
          <label>
            <Database size={16} />
            <select value={source} onChange={(event) => setSource(event.target.value)}>
              <option value="day">Day simulation</option>
              <option value="all">All arbitrages</option>
              <option value="top100">Top 100 snapshot</option>
            </select>
          </label>
          <label>
            Rank
            <select
              value={rank}
              onChange={(event) => {
                const nextRank = event.target.value;
                setRank(nextRank);
                if (nextRank === "profit") setLimit(10);
              }}
            >
              <option value="time">Timeline</option>
              <option value="profit">Top profit</option>
            </select>
          </label>
          <label>
            Min profit
            <input type="number" value={minProfit} onChange={(event) => setMinProfit(Number(event.target.value) || 0)} />
          </label>
          <label>
            Routes
            <input type="number" min="20" max="10000" value={limit} onChange={(event) => setLimit(Number(event.target.value) || 100)} />
          </label>
        </div>
      </header>

      {error && <div className="error">{error}</div>}
      {!data && !error && <div className="loading">Loading jump graph and arbitrage routes…</div>}
      {data && (
        <>
          <section className="stats-row">
            <Stat icon={Route} label="Routes" value={data.summary.routeCount} />
            <Stat icon={ArrowRightLeft} label="Directed edges" value={data.summary.edgeCount} />
            <Stat icon={TrendingUp} label="Total profit" value={`${isk.format(data.summary.totalProfit)} ISK`} />
            <Stat icon={Clock3} label="Range" value={`${formatTime(data.summary.minTime)} - ${formatTime(data.summary.maxTime)}`} />
          </section>

          <RouteMap
            data={data}
            selectedSnapshot={selectedSnapshot}
            highlightedRoute={highlightedRoute}
            setHighlightedRoute={setHighlightedRoute}
          />
          <Timeline routes={routes} snapshots={snapshots} selectedSnapshot={selectedSnapshot} setSelectedSnapshot={setSelectedSnapshot} maxReturnPct={data.summary.maxTotalReturnPct ?? 1} />
        </>
      )}
    </main>
  );
}

createRoot(document.getElementById("root")).render(<App />);

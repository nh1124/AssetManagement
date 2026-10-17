import { useEffect, useMemo, useRef, useState, type CSSProperties, type MouseEvent as ReactMouseEvent } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { Controls, Handle, MarkerType, Position, ReactFlow, ReactFlowProvider,
    useNodesInitialized, useReactFlow, type Edge, type Node, type NodeProps } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import './lifeEventDiagram.css';
import type { ConditionEvaluation } from '../../../api/lifeEventConditions';
import type { LifeEventLink } from '../../../api/lifeEventGraph';
import type { LifeScenario } from '../../../api/lifeScenarios';
import type { LifeEvent } from '../../../types';
import { formatCurrency } from '../../../utils/currency';
import { layout } from './graphLayout';
import ContextMenu, { type ContextMenuItem } from './ContextMenu';

type EventData = {
    id: number;
    name: string;
    resolved_date: string | null;
    amount: number;
    currency: string;
    included: boolean;
    evaluation?: ConditionEvaluation;
};
type EventNode = Node<EventData, 'lifeEvent'>;
type LinkEdge = Edge<{ link: LifeEventLink }>;

function LifeEventNode({ data, isConnectable }: NodeProps<EventNode>) {
    const { scenarioId } = useParams();
    const eventBase = scenarioId ? `/goals/scenarios/${scenarioId}/events` : '/goals/events';
    return <div className={`life-event-node ${data.included ? '' : 'life-event-node-excluded'}`}>
        <Handle type="target" position={Position.Left} isConnectable={isConnectable} aria-label={`${data.name}への接続`} title="接続先" />
        <Link to={`${eventBase}/${data.id}`} title={data.name} className="nodrag line-clamp-2 font-medium text-[var(--studio-accent)] hover:underline">{data.name}</Link>
        <div className="mt-auto space-y-1 tabular-nums">
            <div>{data.resolved_date ?? '日付未設定'}</div>
            <div>{formatCurrency(data.amount, data.currency)}</div>
        </div>
        <div className="min-h-4 text-xs text-[var(--studio-text-muted)]">
            {Boolean(data.evaluation?.conditions.length) && <span>前提条件あり</span>}
        </div>
        {!data.included && <span className="text-xs text-[var(--studio-text-muted)]">選択中のシナリオでは対象外</span>}
        <Handle type="source" position={Position.Right} isConnectable={isConnectable} aria-label={`${data.name}からの接続`} title="接続元" />
    </div>;
}

const nodeTypes = { lifeEvent: LifeEventNode };
// No floor on the fit, so a long chain can zoom out far enough to be seen whole;
// the minZoom prop still bounds how far. maxZoom stops a two-node graph from
// being blown up to fill the pane.
const fitOptions = { padding: 0.15, maxZoom: 1 };

/** Refit the viewport whenever the graph changes shape.
 *
 * Positions are recomputed from scratch on every change, so adding one link can
 * move every node; a frame left where it was would then show the wrong part of
 * the graph. The fitView prop only covers the first render, and waiting for
 * nodesInitialized means fitting to measured nodes rather than to nothing.
 */
function FitWhenMeasured({ signature }: { signature: string }) {
    const initialised = useNodesInitialized();
    const { fitView } = useReactFlow();
    useEffect(() => {
        if (initialised) void fitView(fitOptions);
    }, [initialised, signature, fitView]);
    return null;
}
const ariaLabelConfig = {
    'node.a11yDescription.keyboardDisabled': 'イベントの詳細を開くにはリンクを選択してください。',
    'edge.a11yDescription.default': 'Enterキーで接続を開きます。',
    'handle.ariaLabel': 'イベントを接続',
};
const flowStyle = {
    '--xy-background-color': 'var(--studio-bg)',
    '--xy-edge-stroke-selected': 'var(--studio-accent)',
} as CSSProperties;

type MenuTarget = { type: 'pane' } | { type: 'node'; event: LifeEvent } | { type: 'edge'; edge: LifeEventLink };

export default function LifeEventDiagram({ events, links, scenarios, scenario, evaluations, currency, disabled, onAddEvent, onEditEvent, onDeleteEvent, onConditions, onDeleteEdge, onConnect, onEdgeClick }: {
    events: LifeEvent[]; links: LifeEventLink[]; scenarios: LifeScenario[]; scenario?: LifeScenario;
    evaluations: Record<number, ConditionEvaluation>; currency: string; disabled: boolean;
    onAddEvent: (sourceId?: number, handleType?: 'source' | 'target') => void;
    onEditEvent: (event: LifeEvent) => void; onDeleteEvent: (event: LifeEvent) => void; onDeleteEdge: (edge: LifeEventLink) => void;
    onConditions: (event: LifeEvent) => void;
    onConnect: (source: number, target: number) => void; onEdgeClick: (edge: LifeEventLink) => void;
}) {
    const navigate = useNavigate();
    const { scenarioId } = useParams();
    const eventBase = scenarioId ? `/goals/scenarios/${scenarioId}/events` : '/goals/events';
    const container = useRef<HTMLDivElement>(null);
    const dragAllowed = useRef(false);
    const [menu, setMenu] = useState<{ x: number; y: number; target: MenuTarget } | null>(null);
    const openMenu = (event: ReactMouseEvent | MouseEvent, target: MenuTarget) => {
        event.preventDefault();
        event.stopPropagation();
        if (disabled || !container.current) return;
        const bounds = container.current.getBoundingClientRect();
        setMenu({ x: event.clientX - bounds.left - container.current.clientLeft, y: event.clientY - bounds.top - container.current.clientTop, target });
    };
    const simulation: ContextMenuItem = { label: 'シミュレーションへ', onSelect: () => { void navigate(scenarioId ? `/goals/scenarios/${scenarioId}/simulation` : '/goals/scenarios'); } };
    const menuItems = (target: MenuTarget): ContextMenuItem[] => {
        switch (target.type) {
            case 'pane': return [{ label: 'ライフイベントを追加', onSelect: () => onAddEvent() }, simulation];
            case 'node': return [
                { label: '編集', onSelect: () => onEditEvent(target.event) },
                { label: '前提条件', onSelect: () => onConditions(target.event) },
                { label: '詳細を開く', onSelect: () => { void navigate(`${eventBase}/${target.event.id}`); } },
                { label: '削除', onSelect: () => onDeleteEvent(target.event) }, simulation,
            ];
            case 'edge': return [
                { label: '接続の詳細', onSelect: () => onEdgeClick(target.edge) },
                { label: '削除', onSelect: () => onDeleteEdge(target.edge) },
            ];
        }
    };
    const { nodes, edges } = useMemo(() => {
        const selected = new Map(scenario?.events.map((event) => [event.id, event]));
        // Preserve server-resolved dates while event reads await scenario scoping in N2b.
        const fallback = new Map<number, string | null>();
        for (const story of scenarios) for (const event of story.events) {
            if (!fallback.has(event.id)) fallback.set(event.id, event.resolved_date);
        }
        const graph = layout(events.map((event): EventData => ({
            id: event.id, name: event.name,
            resolved_date: selected.has(event.id) ? selected.get(event.id)?.resolved_date ?? null : fallback.has(event.id) ? fallback.get(event.id) ?? null : event.target_date || null,
            amount: event.target_amount, currency, included: !scenario || selected.has(event.id), evaluation: evaluations[event.id],
        })), links);
        return {
            nodes: graph.nodes.map((node): EventNode => ({
                id: node.id, position: { x: node.x, y: node.y }, data: node.data, type: 'lifeEvent',
                ariaLabel: `${node.data.name}・${node.data.resolved_date ?? '日付未設定'}${node.data.included ? '' : '・選択中のシナリオでは対象外'}`,
            })),
            edges: graph.edges.map((edge): LinkEdge => ({
                ...edge, data: { link: edge.data }, type: 'smoothstep',
                style: {
                    stroke: 'var(--studio-text-muted)', strokeWidth: 1.5,
                },
                markerEnd: { type: MarkerType.ArrowClosed, color: 'var(--studio-text-muted)' },
                label: edge.data.offset_months === 0 ? undefined : `${edge.data.offset_months > 0 ? '+' : ''}${edge.data.offset_months}か月`,
                labelStyle: { fill: 'var(--studio-text)', fontSize: 12 },
                labelBgStyle: { fill: 'var(--studio-surface)' }, labelBgPadding: [6, 4],
                interactionWidth: 24,
                domAttributes: { onKeyDown: (event) => {
                    if (!disabled && (event.key === 'Enter' || event.key === ' ')) {
                        event.preventDefault();
                        onEdgeClick(edge.data);
                    }
                } },
                ariaLabel: `${events.find((event) => event.id === edge.data.from_event_id)?.name}から${events.find((event) => event.id === edge.data.to_event_id)?.name}・必ず続く・${edge.data.offset_months}か月`,
            })),
        };
    }, [events, links, scenarios, scenario, evaluations, currency, disabled, onEdgeClick]);

    const signature = `${nodes.map((node) => node.id).join()}|${edges.map((edge) => edge.id).join()}`;
    return <div ref={container} tabIndex={-1} onContextMenu={(event) => event.preventDefault()}
        className="life-event-diagram relative h-[min(65vh,640px)] min-h-96 overflow-hidden rounded-lg border border-[var(--studio-border)]" aria-label="ライフイベントの接続図">
        <ReactFlowProvider>
            <ReactFlow<EventNode, LinkEdge> nodes={nodes} edges={edges} nodeTypes={nodeTypes} style={flowStyle}
                fitView fitViewOptions={fitOptions} minZoom={0.25} maxZoom={1.5}
                nodesDraggable={false} nodesConnectable={!disabled} edgesReconnectable={false} deleteKeyCode={null}
                nodesFocusable={false} edgesFocusable={!disabled} ariaLabelConfig={ariaLabelConfig}
                connectionLineStyle={{ stroke: 'var(--studio-accent)', strokeWidth: 2 }}
                onConnectStart={() => { dragAllowed.current = !disabled; setMenu(null); }}
                onConnect={(connection) => {
                    // Wait for the server before changing edges; its cycle errors leave the diagram intact.
                    if (!disabled) onConnect(Number(connection.source), Number(connection.target));
                }}
                onConnectEnd={(event, connection) => {
                    const allowed = dragAllowed.current;
                    dragAllowed.current = false;
                    if (!allowed || disabled || connection.isValid || connection.toNode || !connection.fromNode || !connection.fromHandle) return;
                    const pointer = 'changedTouches' in event ? event.changedTouches[0] : event;
                    if (!pointer) return;
                    // Invalid drops on node bodies, controls or outside the canvas must not create events.
                    const hit = document.elementFromPoint(pointer.clientX, pointer.clientY);
                    if (!hit?.classList.contains('react-flow__pane') || !container.current?.contains(hit)) return;
                    onAddEvent(Number(connection.fromNode.id), connection.fromHandle.type);
                }}
                onPaneContextMenu={(event) => openMenu(event, { type: 'pane' })}
                onNodeClick={(event, node) => {
                    // Let handles connect and real links retain keyboard and modified-click behavior.
                    if (event.target instanceof Element && event.target.closest('.react-flow__handle, a')) return;
                    void navigate(`${eventBase}/${node.data.id}`);
                }}
                onNodeContextMenu={(event, node) => {
                    const goal = events.find((item) => item.id === node.data.id);
                    if (goal) openMenu(event, { type: 'node', event: goal });
                }}
                onEdgeContextMenu={(event, edge) => { if (edge.data) openMenu(event, { type: 'edge', edge: edge.data.link }); }}
                onEdgeClick={(_, edge) => { if (!disabled && edge.data) onEdgeClick(edge.data.link); }}>
                {/* Zoom belongs to the diagram itself; a wide chain is unreadable without it. */}
                <Controls showInteractive={false} fitViewOptions={{ padding: 0.15 }} />
                <FitWhenMeasured signature={signature} />
            </ReactFlow>
        </ReactFlowProvider>
        {menu && !disabled && <ContextMenu x={menu.x} y={menu.y} items={menuItems(menu.target)} onClose={() => setMenu(null)} />}
    </div>;
}

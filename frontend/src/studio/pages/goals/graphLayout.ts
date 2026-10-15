import type { LifeEventLink } from '../../../api/lifeEventGraph';

const COLUMN_WIDTH = 344;
const ROW_HEIGHT = 180;

type DatedEvent = { id: number; resolved_date: string | null };

export function layout<T extends DatedEvent>(events: readonly T[], links: readonly LifeEventLink[]) {
    // Positions are computed for this prototype, never stored or persisted as layout data.
    // The server owns DAG validation; this traversal only computes longest-path depths.
    const byId = new Map(events.map((event) => [event.id, event]));
    const edges = links.filter((link) => byId.has(link.from_event_id) && byId.has(link.to_event_id))
        .slice().sort((a, b) => a.id - b.id);
    const incoming = new Map<number, number[]>();
    const outgoing = new Map<number, number[]>();
    for (const link of edges) {
        incoming.set(link.to_event_id, [...(incoming.get(link.to_event_id) ?? []), link.from_event_id]);
        outgoing.set(link.from_event_id, [...(outgoing.get(link.from_event_id) ?? []), link.to_event_id]);
    }
    const remaining = new Map(events.map((event) => [event.id, incoming.get(event.id)?.length ?? 0]));
    const depths = new Map(events.map((event) => [event.id, 0]));
    const ready = events.filter((event) => remaining.get(event.id) === 0).map((event) => event.id).sort((a, b) => a - b);
    for (let index = 0; index < ready.length; index++) {
        const id = ready[index];
        for (const child of outgoing.get(id) ?? []) {
            depths.set(child, Math.max(depths.get(child) ?? 0, (depths.get(id) ?? 0) + 1));
            const count = (remaining.get(child) ?? 0) - 1;
            remaining.set(child, count);
            if (count === 0) ready.push(child);
        }
    }

    const lastColumn = Math.max(0, ...depths.values());
    const columns = new Map<number, T[]>();
    for (const event of events) {
        const connected = incoming.has(event.id) || outgoing.has(event.id);
        const depth = connected ? depths.get(event.id) ?? 0 : lastColumn;
        columns.set(depth, [...(columns.get(depth) ?? []), event]);
    }
    const order = new Map<number, number>();
    const nodes: Array<{ id: string; x: number; y: number; data: T }> = [];
    // A shared descendant belongs to its earliest displayed parent for sibling grouping.
    const parentOrder = (id: number) => Math.min(...(incoming.get(id) ?? []).map((parent) => order.get(parent) ?? Infinity));
    for (const [depth, column] of [...columns].sort(([a], [b]) => a - b)) {
        column.sort((a, b) => {
            const parentA = parentOrder(a.id);
            const parentB = parentOrder(b.id);
            if (parentA !== parentB) return parentA < parentB ? -1 : 1;
            const dateA = a.resolved_date ?? '\uffff';
            const dateB = b.resolved_date ?? '\uffff';
            return (dateA < dateB ? -1 : dateA > dateB ? 1 : 0) || a.id - b.id;
        });
        column.forEach((event, row) => {
            order.set(event.id, order.size);
            nodes.push({ id: String(event.id), x: depth * COLUMN_WIDTH, y: row * ROW_HEIGHT, data: event });
        });
    }
    return {
        nodes,
        edges: edges.map((edge) => ({ id: String(edge.id), source: String(edge.from_event_id), target: String(edge.to_event_id), data: edge })),
    };
}

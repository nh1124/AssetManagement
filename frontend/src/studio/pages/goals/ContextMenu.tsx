import { useEffect, useLayoutEffect, useRef } from 'react';

export type ContextMenuItem = { label: string; onSelect: () => void };

export default function ContextMenu({ x, y, items, onClose }: {
    x: number; y: number; items: ContextMenuItem[]; onClose: () => void;
}) {
    const menu = useRef<HTMLDivElement>(null);

    useLayoutEffect(() => {
        const element = menu.current;
        const container = element?.parentElement;
        if (!element || !container) return;
        const place = () => {
            // Measure the rendered menu because labels and browser zoom change its size.
            element.style.maxWidth = `${Math.max(0, container.clientWidth - 8)}px`;
            element.style.maxHeight = `${Math.max(0, container.clientHeight - 8)}px`;
            element.style.left = `${Math.max(4, Math.min(x, container.clientWidth - element.offsetWidth - 4))}px`;
            element.style.top = `${Math.max(4, Math.min(y, container.clientHeight - element.offsetHeight - 4))}px`;
        };
        place();
        element.querySelector<HTMLButtonElement>('[role="menuitem"]')?.focus();
        const observer = new ResizeObserver(place);
        observer.observe(container);
        observer.observe(element);
        return () => observer.disconnect();
    }, [x, y]);

    useEffect(() => {
        const outside = (event: Event) => {
            if (event.target instanceof globalThis.Node && !menu.current?.contains(event.target)) onClose();
        };
        const escape = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                event.preventDefault();
                event.stopPropagation();
                menu.current?.parentElement?.focus();
                onClose();
            }
        };
        document.addEventListener('pointerdown', outside, true);
        document.addEventListener('click', outside, true);
        document.addEventListener('keydown', escape, true);
        return () => {
            document.removeEventListener('pointerdown', outside, true);
            document.removeEventListener('click', outside, true);
            document.removeEventListener('keydown', escape, true);
        };
    }, [onClose]);

    return <div ref={menu} role="menu" aria-label="図の操作" className="absolute z-50 w-52 overflow-auto rounded-md border border-[var(--studio-border)] bg-[var(--studio-surface)] p-1 text-sm shadow-lg"
        onKeyDown={(event) => {
            event.stopPropagation();
            const buttons = [...event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')];
            const index = buttons.findIndex((button) => button === document.activeElement);
            if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
                event.preventDefault();
                buttons[(index + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length]?.focus();
            } else if (event.key === 'Home' || event.key === 'End') {
                event.preventDefault();
                (event.key === 'Home' ? buttons[0] : buttons.at(-1))?.focus();
            } else if (event.key === 'Tab') onClose();
        }}>
        {items.map((item) => <button key={item.label} type="button" role="menuitem" tabIndex={-1}
            className="block w-full rounded px-3 py-2 text-left hover:bg-[var(--studio-accent-soft)] focus:bg-[var(--studio-accent-soft)] focus:outline-none"
            onClick={() => { menu.current?.parentElement?.focus(); onClose(); item.onSelect(); }}>{item.label}</button>)}
    </div>;
}

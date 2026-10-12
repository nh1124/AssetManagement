/** A screen the rebuild has routed but not yet built.
 *
 * It names the wave that fills it, so an empty screen reads as planned work
 * rather than as something broken.
 */
export default function Pending({ wave, children }: { wave: string; children: React.ReactNode }) {
    return (
        <div className="rounded-lg border border-dashed border-[var(--studio-border-strong)] bg-[var(--studio-surface)] p-8">
            <p className="text-xs font-medium tracking-wide text-[var(--studio-text-faint)]">{wave}</p>
            <div className="mt-2 max-w-2xl text-sm leading-relaxed text-[var(--studio-text-muted)]">
                {children}
            </div>
        </div>
    );
}

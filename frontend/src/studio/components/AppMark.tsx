/** The system mark: an A whose crossbar is a rising line. public/icons/mark.svg is the same drawing. */
export default function AppMark({ size = 24, className = '' }: { size?: number; className?: string }) {
    return (
        <svg width={size} height={size} viewBox="0 0 40 40" aria-hidden="true" className={`flex-shrink-0 ${className}`}>
            <rect width="40" height="40" rx="10" fill="var(--studio-mark, #14402f)" />
            <path d="M11 29 L20 11 L29 29" fill="none" stroke="#ffffff" strokeWidth="2.6" strokeLinejoin="round" strokeLinecap="round" />
            <path d="M14.5 23.5 L19 20 L22 22.5 L26 18" fill="none" stroke="#cfe8da" strokeWidth="2.2" strokeLinejoin="round" strokeLinecap="round" />
        </svg>
    );
}

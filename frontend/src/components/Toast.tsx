import { useState, useEffect, createContext, useContext } from 'react';
import type { ReactNode } from 'react';
import { CheckCircle, XCircle, Info, AlertTriangle, X } from 'lucide-react';

type ToastType = 'success' | 'error' | 'info' | 'warning';

interface Toast {
    id: string;
    message: string;
    type: ToastType;
}

interface ToastContextType {
    showToast: (message: string, type?: ToastType) => void;
}

const ToastContext = createContext<ToastContextType | null>(null);

export const useToast = () => {
    const context = useContext(ToastContext);
    if (!context) throw new Error('useToast must be used within ToastProvider');
    return context;
};

export function ToastProvider({ children }: { children: ReactNode }) {
    const [toasts, setToasts] = useState<Toast[]>([]);

    const showToast = (message: string, type: ToastType = 'success') => {
        const id = Date.now().toString();
        setToasts((prev) => [...prev, { id, message, type }]);
    };

    const removeToast = (id: string) => {
        setToasts((prev) => prev.filter((t) => t.id !== id));
    };

    return (
        <ToastContext.Provider value={{ showToast }}>
            {children}
            <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2">
                {toasts.map((toast) => (
                    <ToastItem key={toast.id} toast={toast} onClose={() => removeToast(toast.id)} />
                ))}
            </div>
        </ToastContext.Provider>
    );
}

function ToastItem({ toast, onClose }: { toast: Toast; onClose: () => void }) {
    useEffect(() => {
        const timer = setTimeout(onClose, 3000);
        return () => clearTimeout(timer);
    }, [onClose]);

    const icons = {
        success: <CheckCircle size={14} className="text-emerald-400" />,
        error: <XCircle size={14} className="text-rose-400" />,
        info: <Info size={14} className="text-cyan-400" />,
        warning: <AlertTriangle size={14} className="text-amber-400" />,
    };

    const bgColors = {
        success: 'border-emerald-800/50 bg-emerald-900/20',
        error: 'border-rose-800/50 bg-rose-900/20',
        info: 'border-cyan-800/50 bg-cyan-900/20',
        warning: 'border-amber-800/50 bg-amber-900/20',
    };

    return (
        <div className={`flex items-center gap-2 px-3 py-2 border ${bgColors[toast.type]} backdrop-blur-sm animate-slide-in min-w-[200px] max-w-[300px]`}>
            {icons[toast.type]}
            <span className="text-xs flex-1">{toast.message}</span>
            <button onClick={onClose} className="text-slate-500 hover:text-white">
                <X size={12} />
            </button>
        </div>
    );
}
